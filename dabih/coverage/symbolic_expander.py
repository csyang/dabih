"""
dabih.coverage.symbolic_expander
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Symbolic expansion engine: Idea C post-processor for large bin spaces.

Replaces the BFS-based `ExpansionEngine` when the cross-coverage space is
too large for explicit enumeration (>~1M bins).  Uses canonical forms from
the SymbolicOrbitEngine instead of materialising every bin.

Key difference from ExpansionEngine
-------------------------------------
ExpansionEngine (BFS):
  - Pre-computes ALL orbits by BFS over the full bin space
  - Stores a dict mapping every BinTuple → hit count
  - Memory: O(|B|), CPU: O(k × |B|)
  - Ceiling: ~1M bins in pure Python

SymbolicExpansionEngine:
  - Never touches the full bin space
  - Translates each hit label-tuple to its canonical form
  - Tracks covered orbits as a set of canonical BinTuples
  - Representatives are enumerated from the Sₙ formula — O(C(n+K−1,n))
  - Memory: O(orbit_count), CPU: O(hits × cycle_computation)
  - Ceiling: none for Sₙ; Burnside limit for other groups

Compatibility
-------------
SymbolicExpansionResult has the same statistics interface as ExpansionResult
(class_coverage_pct, is_complete, n_orbits_hit, etc.) but does NOT provide
a full coverage_map dict — that would re-introduce the memory problem.
Use is_covered(labels) for per-bin queries.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from itertools import permutations

from ..core.bin_space import BinSpace, BinTuple
from ..core.symbolic import SymbolicOrbitEngine
from .result import CoverageResult, LabelTuple
from .expander import _build_label_index_maps, _label_to_bin_tuple


# ── SymbolicExpansionResult ───────────────────────────────────────────────────

@dataclass
class SymbolicExpansionResult:
    """
    Coverage expansion result for large bin spaces.

    Uses canonical orbit representatives rather than a full BinTuple→count map.

    Attributes
    ----------
    engine           : The SymbolicOrbitEngine used (carries profile + BinSpace)
    raw_result       : The original CoverageResult before expansion
    covered_canonicals : Set of canonical representatives of covered orbits
    unresolved_labels  : Label-tuples from the result file that could not be
                         mapped to any BinTuple in the BinSpace
    """
    engine             : SymbolicOrbitEngine
    raw_result         : CoverageResult
    covered_canonicals : frozenset[BinTuple]
    unresolved_labels  : list[LabelTuple] = field(default_factory=list)
    _provenance        : dict[BinTuple, list[str]] | None = field(
        default=None, repr=False
    )

    # ── Statistics ────────────────────────────────────────────────────────────

    def n_orbits(self) -> int:
        return self.engine.count_orbits()

    def n_orbits_hit(self) -> int:
        return len(self.covered_canonicals)

    def class_coverage_pct(self) -> float:
        n = self.n_orbits()
        return 100 * self.n_orbits_hit() / n if n else 0.0

    def n_bins_total(self) -> int:
        return self.engine._profile.total_bins()

    def n_bins_covered(self) -> int:
        """
        Number of bins implied covered (sum of orbit sizes for covered orbits).

        For Sₙ, each orbit size = n! / Π(repetition counts).
        Computed exactly by enumerating orbit members of each covered canonical.
        """
        total = 0
        for canon in self.covered_canonicals:
            total += len(self.engine.orbit_of(canon))
        return total

    def bin_coverage_pct(self) -> float:
        total = self.n_bins_total()
        return 100 * self.n_bins_covered() / total if total else 0.0

    def compression_ratio(self) -> float:
        return self.engine.compression_ratio()

    def is_complete(self) -> bool:
        return len(self.covered_canonicals) == self.n_orbits()

    # ── Per-bin queries ───────────────────────────────────────────────────────

    def is_covered(self, labels: LabelTuple) -> bool:
        """
        Check if the bin identified by `labels` is covered (directly or
        by orbit implication).
        """
        maps = _build_label_index_maps(self.engine.bin_space)
        bt = _label_to_bin_tuple(labels, maps)
        if bt is None:
            return False
        return self.engine.canonical(bt) in self.covered_canonicals

    def orbit_coverage_of(self, labels: LabelTuple) -> bool:
        """True if the orbit containing `labels` is covered."""
        return self.is_covered(labels)

    # ── Holes ─────────────────────────────────────────────────────────────────

    def missed_representatives(self) -> list[BinTuple]:
        """
        List of canonical representatives of uncovered orbits.
        Enumerates all representatives via the symbolic engine and returns
        those not in covered_canonicals.
        """
        all_reps = set(self.engine.representatives())
        return sorted(all_reps - set(self.covered_canonicals))

    def n_missed(self) -> int:
        return self.n_orbits() - self.n_orbits_hit()

    # ── Provenance queries (OQ-06) ────────────────────────────────────────────

    @property
    def has_provenance(self) -> bool:
        """True when merge_and_expand was called with track_provenance=True."""
        return self._provenance is not None

    def orbit_run_ids(self, labels: LabelTuple) -> list[str]:
        """Run_ids that covered the orbit containing `labels`."""
        if not self.has_provenance:
            return []
        from .expander import _build_label_index_maps, _label_to_bin_tuple
        maps = _build_label_index_maps(self.engine.bin_space)
        bt   = _label_to_bin_tuple(labels, maps)
        if bt is None:
            return []
        canon = self.engine.canonical(bt)
        return list(self._provenance.get(canon, []))

    def coverage_count(self, labels: LabelTuple) -> int:
        """How many distinct runs covered the orbit containing `labels`."""
        return len(self.orbit_run_ids(labels))

    def single_coverage_orbits(self) -> list[BinTuple]:
        """Canonical reps of orbits covered by exactly one run."""
        if not self.has_provenance:
            return []
        return [rep for rep, run_ids in self._provenance.items()
                if len(run_ids) == 1]

    def coverage_histogram(self) -> dict[int, int]:
        """Distribution of orbit coverage counts {n_runs: n_orbits}."""
        if not self.has_provenance:
            return {}
        hist: dict[int, int] = {}
        for run_ids in self._provenance.values():
            c = len(run_ids)
            hist[c] = hist.get(c, 0) + 1
        return dict(sorted(hist.items()))

    def fragile_orbits(self, threshold: int = 2) -> list[BinTuple]:
        """Canonical reps of orbits covered by fewer than `threshold` runs."""
        if not self.has_provenance:
            return []
        return [rep for rep, run_ids in self._provenance.items()
                if len(run_ids) < threshold]

    # ── Report ────────────────────────────────────────────────────────────────

    def report(self, show_holes: bool = True, max_holes: int = 20) -> str:
        W = 68
        meta    = self.raw_result
        profile = self.engine._profile
        method  = self.engine.method_used()

        lines = [
            "═" * W,
            "  Dabih — Symbolic Coverage Expansion Report  (Idea E + C)",
            "═" * W,
        ]
        if meta.run_id:     lines.append(f"  Run ID     : {meta.run_id}")
        if meta.simulator:  lines.append(f"  Simulator  : {meta.simulator}")
        if meta.covergroup: lines.append(f"  Covergroup : {meta.covergroup}")
        lines += [
            f"  Method     : {method}",
            f"  n={profile.n_blocks}, K={profile.K}, "
            f"total bins={profile.total_bins():,}",
            "─" * W,
            "  Simulation input",
            f"    Bins observed          : {len(self.raw_result):>8,}",
            f"    Total hits             : {self.raw_result.total_hits():>8,}",
            f"    Unresolved labels      : {len(self.unresolved_labels):>8,}",
            "─" * W,
            "  Equivalence class coverage",
            f"    Orbits total           : {self.n_orbits():>8,}",
            f"    Orbits hit             : {self.n_orbits_hit():>8,}",
            f"    Orbits missed          : {self.n_missed():>8,}",
            f"    Class coverage         : {self.class_coverage_pct():>7.2f}%",
            "─" * W,
            "  Implied bin coverage",
            f"    Total bins             : {self.n_bins_total():>8,}",
            f"    Bins covered           : {self.n_bins_covered():>8,}",
            f"    Bin coverage           : {self.bin_coverage_pct():>7.2f}%",
            f"    Compression ratio      : {self.compression_ratio():>7.2f}×",
        ]

        if self.is_complete():
            lines += ["─" * W, "  ✓  COMPLETE — all equivalence classes covered"]
        elif show_holes:
            missed = self.missed_representatives()
            n_shown = min(max_holes, len(missed))
            lines += [
                "─" * W,
                f"  Holes — uncovered orbits (showing {n_shown} of {len(missed)}):",
            ]
            bs = self.engine.bin_space
            for rep in missed[:max_holes]:
                label = bs.bin_label(rep)
                orbit_sz = len(self.engine.orbit_of(rep))
                lines.append(
                    f"    rep={label}  ({orbit_sz} bins implied)"
                )
            if len(missed) > max_holes:
                lines.append(f"    ... {len(missed) - max_holes} more ...")

        if self.has_provenance:
            hist    = self.coverage_histogram()
            fragile = self.fragile_orbits(threshold=2)
            n_robust = sum(v for k, v in hist.items() if k >= 3)
            lines += [
                "─" * W,
                "  Coverage confidence  (provenance tracking)",
                f"    Single-seed orbits  (fragile)  : {len(fragile):>8,}  ⚠",
                f"    Two-seed orbits                : {hist.get(2, 0):>8,}",
                f"    Well-covered (≥3 seeds)        : {n_robust:>8,}  ✓",
                "    Histogram  (seeds → orbits)    : "
                + "  ".join(f"{k}×{v}" for k, v in hist.items()),
            ]

        if self.unresolved_labels:
            lines += [
                "─" * W,
                f"  ⚠ Unresolved label-tuples ({len(self.unresolved_labels)}):",
            ]
            for lt in self.unresolved_labels[:5]:
                lines.append(f"    {lt}")
            if len(self.unresolved_labels) > 5:
                lines.append(f"    ... {len(self.unresolved_labels) - 5} more ...")

        lines.append("═" * W)
        return "\n".join(lines)

    def to_dict(self) -> dict:
        """Machine-readable summary dict."""
        bs = self.engine.bin_space
        missed = self.missed_representatives()
        d = {
            "run_id"         : self.raw_result.run_id,
            "method"         : self.engine.method_used(),
            "class_coverage" : round(self.class_coverage_pct(), 4),
            "bin_coverage"   : round(self.bin_coverage_pct(), 4),
            "orbits_total"   : self.n_orbits(),
            "orbits_hit"     : self.n_orbits_hit(),
            "bins_total"     : self.n_bins_total(),
            "bins_covered"   : self.n_bins_covered(),
            "compression"    : round(self.compression_ratio(), 4),
            "complete"       : self.is_complete(),
            "holes": [
                {
                    "rep_labels" : list(bs.bin_label(r)),
                    "orbit_size" : len(self.engine.orbit_of(r)),
                }
                for r in missed[:100]
            ],
            "unresolved": [list(lt) for lt in self.unresolved_labels],
        }
        if self.has_provenance:
            hist    = self.coverage_histogram()
            fragile = self.fragile_orbits(threshold=2)
            d["provenance"] = {
                "histogram"    : {str(k): v for k, v in hist.items()},
                "fragile_count": len(fragile),
                "fragile_reps" : [list(bs.bin_label(r)) for r in fragile[:50]],
                "well_covered" : sum(v for k, v in hist.items() if k >= 3),
            }
        return d


# ── SymbolicExpansionEngine ───────────────────────────────────────────────────

class SymbolicExpansionEngine:
    """
    Coverage expansion for large bin spaces using canonical orbit forms.

    Drop-in complement to ExpansionEngine:
    - Use ExpansionEngine        when total bins ≤ ~1M  (BFS, full map)
    - Use SymbolicExpansionEngine when total bins > ~1M  (symbolic, no full map)

    Both can be used for small spaces — SymbolicExpansionEngine is correct
    for any size, just less information-dense than ExpansionEngine for small
    spaces where a full coverage_map is useful.

    Usage
    -----
        engine = SymbolicExpansionEngine(bin_space)
        result = engine.expand(coverage_result)
        print(result.report())
        print(result.class_coverage_pct())
        print(result.is_covered(("IDLE", "ACTIVE", "STALL", "ERROR",
                                  "IDLE", "IDLE",   "IDLE",  "IDLE")))
    """

    def __init__(self, bin_space: BinSpace):
        self.bin_space      = bin_space
        self._sym_engine    = SymbolicOrbitEngine(bin_space)
        self._label_maps    = _build_label_index_maps(bin_space)

    # ── Core expansion ────────────────────────────────────────────────────────

    def expand(
        self,
        result: CoverageResult,
        track_provenance: bool = False,
    ) -> SymbolicExpansionResult:
        """
        Expand a CoverageResult using canonical forms.

        Parameters
        ----------
        result           : Raw simulation output.
        track_provenance : When True, attribute each covered orbit to this
                           run's run_id (trivial for single-run expansion).
        """
        covered_canonicals: set[BinTuple] = set()
        unresolved: list[LabelTuple] = []

        for binhit in result.hits:
            bt = _label_to_bin_tuple(binhit.labels, self._label_maps)
            if bt is None:
                unresolved.append(binhit.labels)
                continue
            canon = self._sym_engine.canonical(bt)
            covered_canonicals.add(canon)

        provenance = None
        if track_provenance:
            run_id = result.run_id or "run_0"
            provenance = {canon: [run_id] for canon in covered_canonicals}

        return SymbolicExpansionResult(
            engine             = self._sym_engine,
            raw_result         = result,
            covered_canonicals = frozenset(covered_canonicals),
            unresolved_labels  = unresolved,
            _provenance        = provenance,
        )

    def merge_and_expand(
        self,
        results: list[CoverageResult],
        track_provenance: bool = False,
    ) -> SymbolicExpansionResult:
        """
        Expand multiple simulation runs: union of covered orbits.

        Parameters
        ----------
        results          : One CoverageResult per simulation run.
        track_provenance : When True, record which run_id(s) covered each
                           orbit canonical representative.  Enables
                           coverage_histogram(), fragile_orbits(), etc.
        """
        all_canonicals: set[BinTuple]       = set()
        prov_build: dict[BinTuple, set[str]] = {} if track_provenance else {}
        unresolved: list[LabelTuple]         = []
        meta = results[0] if results else CoverageResult()

        for idx, r in enumerate(results):
            run_id = r.run_id or f"run_{idx}"
            for binhit in r.hits:
                bt = _label_to_bin_tuple(binhit.labels, self._label_maps)
                if bt is None:
                    if binhit.labels not in unresolved:
                        unresolved.append(binhit.labels)
                    continue
                canon = self._sym_engine.canonical(bt)
                all_canonicals.add(canon)
                if track_provenance:
                    if canon not in prov_build:
                        prov_build[canon] = set()
                    prov_build[canon].add(run_id)

        from .result import BinHit
        merged_result = CoverageResult(
            hits       = [
                BinHit(labels=self.bin_space.bin_label(c), count=1)
                for c in sorted(all_canonicals)
            ],
            run_id     = f"merged({len(results)} runs)",
            simulator  = meta.simulator,
            covergroup = meta.covergroup,
        )

        provenance = (
            {rep: sorted(run_ids) for rep, run_ids in prov_build.items()}
            if track_provenance else None
        )

        return SymbolicExpansionResult(
            engine             = self._sym_engine,
            raw_result         = merged_result,
            covered_canonicals = frozenset(all_canonicals),
            unresolved_labels  = unresolved,
            _provenance        = provenance,
        )
