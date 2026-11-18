"""
dabih.coverage.expander
~~~~~~~~~~~~~~~~~~~~~~~~
The core of Idea C: expand a compressed simulation coverage result to its
full implied coverage using the orbit partition from Idea B.

Algorithm
---------
1.  Build a label → index map for each coverpoint in the BinSpace.
2.  Translate each hit label-tuple from the CoverageResult into a BinTuple.
3.  For each orbit, check whether its representative was hit.
4.  Propagate: every member of a hit orbit is marked as covered (with the
    same hit count as the representative).
5.  Compute statistics and collect unresolved / unhit records.

Key invariant (correctness guarantee)
--------------------------------------
Hitting the orbit representative implies coverage for all orbit members
*if and only if* the symmetry group declared in the BinSpace is a valid
symmetry of the design under verification.  Dabih does not verify this
claim; that is the responsibility of Idea D (formal verification pass).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..core.bin_space import BinSpace, BinTuple, Orbit
from .result import CoverageResult, LabelTuple


# ── Resolution helpers ────────────────────────────────────────────────────────

def _build_label_index_maps(bin_space: BinSpace) -> list[dict[str, int]]:
    """
    For each coverpoint, build a mapping  bin_label → bin_index.
    Used to translate CoverageResult label-tuples into BinTuples.
    """
    maps = []
    for cp in bin_space._coverpoints:
        m = {bl.name: idx for idx, bl in enumerate(cp.bins)}
        maps.append(m)
    return maps


def _label_to_bin_tuple(
    labels: LabelTuple,
    label_maps: list[dict[str, int]],
) -> BinTuple | None:
    """
    Translate a label-tuple into a BinTuple.

    Returns None if any label is not found in its coverpoint's bin list,
    or if the label-tuple length does not match the number of coverpoints.
    """
    if len(labels) != len(label_maps):
        return None
    indices = []
    for label, lmap in zip(labels, label_maps):
        idx = lmap.get(label)
        if idx is None:
            return None
        indices.append(idx)
    return tuple(indices)


# ── ExpansionResult ───────────────────────────────────────────────────────────

@dataclass
class ExpansionResult:
    """
    The output of the ExpansionEngine: full implied coverage across the
    entire cross-coverage bin space.

    Attributes
    ----------
    bin_space       : The BinSpace used for expansion (holds orbit structure)
    raw_result      : The original CoverageResult before expansion
    coverage_map    : BinTuple → hit_count for every bin in the space.
                      Count is 0 for uncovered bins; ≥ 1 for covered bins.
                      Covered-by-implication bins carry the representative's count.
    orbits_hit      : Orbits whose representative was observed in simulation
    orbits_missed   : Orbits whose representative was never observed
    unresolved_labels : Label-tuples from the result file that could not be
                      mapped to any BinTuple in the BinSpace
    """
    bin_space        : BinSpace
    raw_result       : CoverageResult
    coverage_map     : dict[BinTuple, int]
    orbits_hit       : list[Orbit]
    orbits_missed    : list[Orbit]
    unresolved_labels: list[LabelTuple] = field(default_factory=list)
    _provenance      : dict[BinTuple, list[str]] | None = field(
        default=None, repr=False
    )

    # ── Statistics ────────────────────────────────────────────────────────────

    def n_orbits(self) -> int:
        return len(self.orbits_hit) + len(self.orbits_missed)

    def n_orbits_hit(self) -> int:
        return len(self.orbits_hit)

    def class_coverage_pct(self) -> float:
        n = self.n_orbits()
        return 100 * self.n_orbits_hit() / n if n else 0.0

    def n_bins_total(self) -> int:
        return len(self.coverage_map)

    def n_bins_covered(self) -> int:
        return sum(1 for c in self.coverage_map.values() if c > 0)

    def bin_coverage_pct(self) -> float:
        total = self.n_bins_total()
        return 100 * self.n_bins_covered() / total if total else 0.0

    def compression_ratio(self) -> float:
        return self.bin_space.compression_ratio()

    def is_complete(self) -> bool:
        """True when all equivalence classes have been covered."""
        return len(self.orbits_missed) == 0

    # ── Access helpers ────────────────────────────────────────────────────────

    def is_covered(self, labels: LabelTuple) -> bool:
        """Check coverage for a bin identified by its label-tuple."""
        maps = _build_label_index_maps(self.bin_space)
        bt = _label_to_bin_tuple(labels, maps)
        if bt is None:
            return False
        return self.coverage_map.get(bt, 0) > 0

    def hit_count(self, labels: LabelTuple) -> int:
        """Hit count for a bin identified by its label-tuple."""
        maps = _build_label_index_maps(self.bin_space)
        bt = _label_to_bin_tuple(labels, maps)
        if bt is None:
            return 0
        return self.coverage_map.get(bt, 0)

    def covered_bins(self) -> list[BinTuple]:
        """All BinTuples with at least one hit (direct or implied)."""
        return [bt for bt, c in self.coverage_map.items() if c > 0]

    def uncovered_bins(self) -> list[BinTuple]:
        """All BinTuples with zero hits."""
        return [bt for bt, c in self.coverage_map.items() if c == 0]

    def missed_representatives(self) -> list[BinTuple]:
        """Representatives of orbits that were not covered."""
        return [o.representative for o in self.orbits_missed]

    # ── Provenance queries (OQ-06) ────────────────────────────────────────────

    @property
    def has_provenance(self) -> bool:
        """True when merge_and_expand was called with track_provenance=True."""
        return self._provenance is not None

    def orbit_run_ids(self, labels: LabelTuple) -> list[str]:
        """
        Return the list of run_ids that covered the orbit containing `labels`.

        Returns [] if provenance is not tracked or the orbit is uncovered.
        """
        if not self.has_provenance:
            return []
        maps = _build_label_index_maps(self.bin_space)
        bt   = _label_to_bin_tuple(labels, maps)
        if bt is None:
            return []
        # Find the orbit representative for this bin
        for orbit in self.orbits_hit:
            if bt in orbit.members or bt == orbit.representative:
                return list(self._provenance.get(orbit.representative, []))
        return []

    def coverage_count(self, labels: LabelTuple) -> int:
        """
        Return how many distinct simulation runs covered the orbit containing
        `labels`.  Returns 0 if uncovered or provenance not tracked.
        """
        return len(self.orbit_run_ids(labels))

    def single_coverage_orbits(self) -> list[BinTuple]:
        """
        Representatives of orbits covered by exactly one simulation run.

        These are fragile coverage points — covered by only one seed in the
        regression.  They warrant additional targeted stimulus.

        Returns [] when provenance is not tracked.
        """
        if not self.has_provenance:
            return []
        return [
            rep for rep, run_ids in self._provenance.items()
            if len(run_ids) == 1
        ]

    def coverage_histogram(self) -> dict[int, int]:
        """
        Return a distribution of orbit coverage counts:
            {1: n_orbits_covered_by_1_run,
             2: n_orbits_covered_by_2_runs, ...}

        Uncovered orbits (count=0) are not included.
        Returns {} when provenance is not tracked.

        Use to assess regression robustness: a histogram shifting right
        over successive regression builds means coverage is getting stronger.
        """
        if not self.has_provenance:
            return {}
        hist: dict[int, int] = {}
        for run_ids in self._provenance.values():
            c = len(run_ids)
            hist[c] = hist.get(c, 0) + 1
        return dict(sorted(hist.items()))

    def fragile_orbits(self, threshold: int = 2) -> list[BinTuple]:
        """
        Representatives of orbits covered by fewer than `threshold` runs.

        Default threshold=2: returns orbits covered by exactly 1 run.
        Raise threshold for stricter robustness requirements.

        Returns [] when provenance is not tracked.
        """
        if not self.has_provenance:
            return []
        return [
            rep for rep, run_ids in self._provenance.items()
            if len(run_ids) < threshold
        ]

    # ── Report ────────────────────────────────────────────────────────────────

    def report(self, show_holes: bool = True, max_holes: int = 20) -> str:
        """Return a formatted expansion and coverage report."""
        W = 68
        meta = self.raw_result
        lines = [
            "═" * W,
            "  Dabih — Coverage Expansion Report  (Idea C)",
            "═" * W,
        ]
        if meta.run_id:     lines.append(f"  Run ID     : {meta.run_id}")
        if meta.simulator:  lines.append(f"  Simulator  : {meta.simulator}")
        if meta.timestamp:  lines.append(f"  Timestamp  : {meta.timestamp}")
        if meta.covergroup: lines.append(f"  Covergroup : {meta.covergroup}")
        lines.append("─" * W)

        # Simulation input summary
        lines += [
            "  Simulation input (compressed model)",
            f"    Bins observed in simulation  : {len(self.raw_result):>8,}",
            f"    Total simulation hits        : {self.raw_result.total_hits():>8,}",
            f"    Unresolved label-tuples      : {len(self.unresolved_labels):>8,}",
            "─" * W,
        ]

        # Equivalence class coverage
        lines += [
            "  Equivalence class coverage",
            f"    Orbits (equivalence classes) : {self.n_orbits():>8,}",
            f"    Orbits hit                   : {self.n_orbits_hit():>8,}",
            f"    Orbits missed                : {len(self.orbits_missed):>8,}",
            f"    Class coverage               : {self.class_coverage_pct():>7.2f}%",
            "─" * W,
        ]

        # Implied bin coverage
        raw_covered = len(self.raw_result)
        implied     = self.n_bins_covered() - raw_covered
        lines += [
            "  Implied bin coverage (after expansion)",
            f"    Total bins in space          : {self.n_bins_total():>8,}",
            f"    Directly observed            : {raw_covered:>8,}",
            f"    Implied by symmetry          : {implied:>8,}",
            f"    Total bins covered           : {self.n_bins_covered():>8,}",
            f"    Bin coverage                 : {self.bin_coverage_pct():>7.2f}%",
            f"    Compression ratio            : {self.compression_ratio():>7.2f}×",
        ]

        if self.is_complete():
            lines += ["─" * W, "  ✓  COMPLETE — all equivalence classes covered"]
        elif show_holes:
            lines.append("─" * W)
            n_shown = min(max_holes, len(self.orbits_missed))
            lines.append(
                f"  Holes — uncovered orbits"
                f" (showing {n_shown} of {len(self.orbits_missed)}):"
            )
            for orbit in self.orbits_missed[:max_holes]:
                rep_label = self.bin_space.bin_label(orbit.representative)
                lines.append(
                    f"    orbit {orbit.id:>4d}  rep={rep_label}"
                    f"  ({orbit.size()} bins implied)"
                )
            if len(self.orbits_missed) > max_holes:
                lines.append(
                    f"    ... {len(self.orbits_missed) - max_holes} more holes not shown ..."
                )

        if self.has_provenance:
            hist     = self.coverage_histogram()
            fragile  = self.fragile_orbits(threshold=2)
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
            lines.append("─" * W)
            lines.append(f"  ⚠ Unresolved label-tuples ({len(self.unresolved_labels)}):")
            for lt in self.unresolved_labels[:5]:
                lines.append(f"    {lt}")
            if len(self.unresolved_labels) > 5:
                lines.append(f"    ... {len(self.unresolved_labels) - 5} more ...")

        lines.append("═" * W)
        return "\n".join(lines)

    def to_dict(self) -> dict:
        """Serialise as a machine-readable dict (JSON-safe)."""
        bs = self.bin_space
        d = {
            "run_id"         : self.raw_result.run_id,
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
                    "orbit_id"   : o.id,
                    "rep_labels" : list(bs.bin_label(o.representative)),
                    "orbit_size" : o.size(),
                }
                for o in self.orbits_missed
            ],
            "unresolved": [list(lt) for lt in self.unresolved_labels],
        }
        if self.has_provenance:
            hist    = self.coverage_histogram()
            fragile = self.fragile_orbits(threshold=2)
            d["provenance"] = {
                "histogram"      : {str(k): v for k, v in hist.items()},
                "fragile_count"  : len(fragile),
                "fragile_reps"   : [list(bs.bin_label(r)) for r in fragile[:50]],
                "well_covered"   : sum(v for k,v in hist.items() if k >= 3),
            }
        return d


# ── ExpansionEngine ───────────────────────────────────────────────────────────

class ExpansionEngine:
    """
    Expands a compressed simulation coverage result to full implied coverage.

    Usage
    -----
        engine = ExpansionEngine(bin_space)
        result = engine.expand(coverage_result)
        print(result.report())

    The engine is stateless after construction — `expand()` may be called
    multiple times with different CoverageResult objects (e.g. multiple
    simulation runs or incremental regression results).
    """

    def __init__(self, bin_space: BinSpace):
        self.bin_space = bin_space
        # Pre-compute orbits and label maps once
        self._orbits      = bin_space.compute_orbits()
        self._label_maps  = _build_label_index_maps(bin_space)
        self._rep_to_orbit: dict[BinTuple, Orbit] = {
            o.representative: o for o in self._orbits
        }
        # All-bins-to-orbit map for fast lookup of any arbitrary hit bin
        self._bin_to_orbit: dict[BinTuple, Orbit] = {}
        for o in self._orbits:
            for m in o.members:
                self._bin_to_orbit[m] = o

    # ── Core expansion ────────────────────────────────────────────────────────

    def expand(
        self,
        result: CoverageResult,
        track_provenance: bool = False,
    ) -> ExpansionResult:
        """
        Expand a CoverageResult against the BinSpace orbit partition.

        Any hit bin (representative or non-representative) will cause its
        entire orbit to be marked covered.

        Parameters
        ----------
        result          : Raw simulation output.
        track_provenance: When True, populate provenance data on the result
                          (trivial for a single run — all covered orbits are
                          attributed to this run's run_id).
        """
        hit_map: dict[BinTuple, int] = {}
        unresolved: list[LabelTuple] = []

        for binhit in result.hits:
            bt = _label_to_bin_tuple(binhit.labels, self._label_maps)
            if bt is None:
                unresolved.append(binhit.labels)
                continue
            hit_map[bt] = hit_map.get(bt, 0) + binhit.count

        covered_orbit_ids: set[int] = set()
        orbit_counts: dict[int, int] = {}

        for bt, count in hit_map.items():
            orbit = self._bin_to_orbit.get(bt)
            if orbit is not None:
                if orbit.id not in covered_orbit_ids:
                    covered_orbit_ids.add(orbit.id)
                    orbit_counts[orbit.id] = count
                else:
                    orbit_counts[orbit.id] = max(orbit_counts[orbit.id], count)

        coverage_map: dict[BinTuple, int] = {}
        orbits_hit:   list[Orbit] = []
        orbits_missed: list[Orbit] = []

        for orbit in self._orbits:
            if orbit.id in covered_orbit_ids:
                count = orbit_counts[orbit.id]
                for member in orbit.members:
                    coverage_map[member] = count
                orbits_hit.append(orbit)
            else:
                for member in orbit.members:
                    coverage_map[member] = 0
                orbits_missed.append(orbit)

        provenance = None
        if track_provenance:
            run_id = result.run_id or "run_0"
            provenance = {o.representative: [run_id] for o in orbits_hit}

        return ExpansionResult(
            bin_space         = self.bin_space,
            raw_result        = result,
            coverage_map      = coverage_map,
            orbits_hit        = orbits_hit,
            orbits_missed     = orbits_missed,
            unresolved_labels = unresolved,
            _provenance       = provenance,
        )

    def merge_and_expand(
        self,
        results: list[CoverageResult],
        track_provenance: bool = False,
    ) -> ExpansionResult:
        """
        Merge multiple simulation runs before expansion.

        Parameters
        ----------
        results          : One CoverageResult per simulation run.
        track_provenance : When True, record which run_id(s) covered each
                           orbit.  Enables coverage_histogram(),
                           fragile_orbits(), and orbit_run_ids() on the
                           returned ExpansionResult.
                           Default False — zero overhead for standard
                           regression merge workflows.
        """
        merged_hits: dict[LabelTuple, int] = {}
        meta = results[0] if results else CoverageResult()

        # Provenance: orbit representative → sorted list of run_ids that hit it
        prov_build: dict[BinTuple, set[str]] = {} if track_provenance else {}

        for r in results:
            run_id = r.run_id or f"run_{results.index(r)}"
            for binhit in r.hits:
                merged_hits[binhit.labels] = (
                    merged_hits.get(binhit.labels, 0) + binhit.count
                )
                if track_provenance:
                    bt = _label_to_bin_tuple(binhit.labels, self._label_maps)
                    if bt is None:
                        continue
                    orbit = self._bin_to_orbit.get(bt)
                    if orbit is None:
                        continue
                    rep = orbit.representative
                    if rep not in prov_build:
                        prov_build[rep] = set()
                    prov_build[rep].add(run_id)

        from .result import BinHit
        merged = CoverageResult(
            hits       = [BinHit(l, c) for l, c in merged_hits.items()],
            run_id     = f"merged({len(results)} runs)",
            simulator  = meta.simulator,
            covergroup = meta.covergroup,
        )
        er = self.expand(merged)

        provenance = (
            {rep: sorted(run_ids) for rep, run_ids in prov_build.items()}
            if track_provenance else None
        )
        # Replace with provenance-annotated result
        from dataclasses import replace
        return replace(er, _provenance=provenance)
