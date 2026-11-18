"""
dabih.rtl.bridge
~~~~~~~~~~~~~~~~
Wires GenerateArray descriptors (from the RTL extractor) to BinSpace
instances (from the orbit engine), closing the loop between Idea A and Idea B.

The bridge answers one question: given that this generate-for loop creates N
symmetric instances of module M, and given that the user wants to cover
signal S on each instance, what is the compressed BinSpace?

Two entry points
----------------
BinSpaceBuilder
    Fluent builder — user specifies coverpoints once per module type and the
    builder applies them to all matching GenerateArrays.

auto_build(arrays, coverpoint_specs, ...)
    Convenience function for the common case.

Design note
-----------
The bridge deliberately does NOT invent coverpoint bins from the RTL.  
Bin semantics (what values matter for verification) are a verification 
intent decision, not a structural property of the RTL.  The RTL tells 
Dabih *which signals are symmetric*; the user tells Dabih *what to cover*.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from ..core.bin_space import BinSpace
from ..core.coverpoint import Coverpoint
from .generate_array import GenerateArray


# ── CoverSpec ────────────────────────────────────────────────────────────────

@dataclass
class CoverSpec:
    """
    A user-supplied specification of what to cover on each instance of
    a replicated module.

    Attributes
    ----------
    module_type  : Module type this spec targets (e.g. "rx_lane").
                   Use None to apply to all module types.
    signal_name  : Base name for the coverpoint (e.g. "state", "opcode").
    bins         : List of bin names for that signal.
    """
    signal_name : str
    bins        : list[str]
    module_type : str | None = None

    @classmethod
    def from_coverpoint(cls, cp: Coverpoint, module_type: str | None = None) -> CoverSpec:
        return cls(
            signal_name = cp.name,
            bins        = [b.name for b in cp.bins],
            module_type = module_type,
        )


# ── BridgeResult ─────────────────────────────────────────────────────────────

@dataclass
class BridgeResult:
    """
    One BinSpace produced for one GenerateArray.

    Carries the source array and the wired BinSpace together so callers
    can trace which compression came from which RTL structure.
    """
    array      : GenerateArray
    bin_space  : BinSpace
    n_instances: int

    def compression_ratio(self) -> float:
        return self.bin_space.compression_ratio()

    def compression_pct(self) -> float:
        return self.bin_space.compression_pct()

    def __str__(self) -> str:
        return (
            f"{self.array.parent_module}.{self.array.module_type} ×{self.n_instances}"
            f"  →  {self.bin_space.total_bin_count():,} bins"
            f"  →  {self.bin_space.orbit_count():,} orbits"
            f"  ({self.compression_pct():.1f}% reduction)"
        )


# ── BinSpaceBuilder ───────────────────────────────────────────────────────────

class BinSpaceBuilder:
    """
    Fluent builder that maps CoverSpecs onto GenerateArrays to produce
    compressed BinSpaces.

    Usage
    -----
        results = (BinSpaceBuilder(arrays)
                   .cover("state", ["IDLE","ACTIVE","STALL","ERROR"],
                          module_type="rx_lane")
                   .cover("credit", ["ZERO","ONE","MANY"],
                          module_type="rx_lane")
                   .cover("valid", ["LO","HI"])       # applies to all types
                   .build(param_overrides={"N_LANES": 8}))

        for r in results:
            print(r)
            print(r.bin_space.report())
    """

    def __init__(self, arrays: list[GenerateArray]):
        self._arrays = arrays
        self._specs: list[CoverSpec] = []

    # ── Builder methods ───────────────────────────────────────────────────────

    def cover(
        self,
        signal_name: str,
        bins: list[str],
        module_type: str | None = None,
    ) -> BinSpaceBuilder:
        """
        Declare a coverage intent: cover `signal_name` with `bins` on every
        instance of `module_type` (or all module types if None).
        """
        self._specs.append(CoverSpec(signal_name, bins, module_type))
        return self

    def cover_spec(self, spec: CoverSpec) -> BinSpaceBuilder:
        self._specs.append(spec)
        return self

    def cover_specs(self, specs: Iterable[CoverSpec]) -> BinSpaceBuilder:
        for s in specs:
            self._specs.append(s)
        return self

    def cover_value_classes(
        self, signal_name: str, module_type: str | None = None
    ) -> BinSpaceBuilder:
        """
        Shortcut: cover `signal_name` with the standard six value equivalence
        classes (ZERO, ONE_HOT, BOUNDARY_LO, BOUNDARY_HI, INTERIOR, ALL_ONES).
        """
        return self.cover(
            signal_name,
            ["ZERO", "ONE_HOT", "BOUNDARY_LO", "BOUNDARY_HI", "INTERIOR", "ALL_ONES"],
            module_type,
        )

    # ── Build ─────────────────────────────────────────────────────────────────

    def build(
        self,
        param_overrides: dict[str, int] | None = None,
    ) -> list[BridgeResult]:
        """
        Build one BridgeResult per GenerateArray that has at least one
        matching CoverSpec and a resolvable instance count.

        Arrays with unresolvable counts are skipped with a warning.

        Parameters
        ----------
        param_overrides :
            Passed to GenerateArray.count() to resolve parameter-based bounds.
        """
        results = []
        for arr in self._arrays:
            n = arr.count(param_overrides or {})
            if n is None:
                _warn(
                    f"Skipping {arr.parent_module}.{arr.module_type}: "
                    f"instance count unresolvable "
                    f"(parameter {arr.bound_param!r} has no default or override)"
                )
                continue

            matching = [
                s for s in self._specs
                if s.module_type is None or s.module_type == arr.module_type
            ]
            if not matching:
                continue  # no coverage intent for this module type

            bs = self._build_bin_space(arr, n, matching)
            results.append(BridgeResult(array=arr, bin_space=bs, n_instances=n))

        return results

    def _build_bin_space(
        self,
        arr: GenerateArray,
        n: int,
        specs: list[CoverSpec],
    ) -> BinSpace:
        """
        Construct a BinSpace for one GenerateArray.

        Coverpoint naming convention:
            {instance_base}[{i}].{signal_name}

        The per-instance coverpoints are added in signal order, then repeated
        for each instance.  That is, for 3 instances and 2 signals (state, valid):

            cp[0]  = inst[0].state
            cp[1]  = inst[0].valid
            cp[2]  = inst[1].state
            cp[3]  = inst[1].valid
            cp[4]  = inst[2].state
            cp[5]  = inst[2].valid

        The symmetry permutation swaps all coverpoints belonging to instance i
        with those belonging to instance j, keeping the intra-instance signal
        order intact.  This is a block permutation with block size len(specs).
        """
        n_sigs = len(specs)
        bs = BinSpace(name=str(arr))

        # Add coverpoints: instance × signal
        for i in range(n):
            for spec in specs:
                cp = Coverpoint.from_names(
                    f"{arr.instance_base}[{i}].{spec.signal_name}",
                    spec.bins,
                )
                bs.add_coverpoint(cp)

        # Declare full Sₙ symmetry on all n instances using the ergonomic API.
        # add_instance_symmetry() both adds the group generators AND records
        # the declaration in _symmetry_declarations for Idea D (formal emission).
        if n >= 2:
            bs.add_instance_symmetry(
                instance_indices = list(range(n)),
                block_size       = n_sigs,
            )

        # Annotate with symbolic hint so SymbolicOrbitEngine skips auto-detection
        bs._symbolic_hint = {
            "type"       : "block_symmetric",
            "n_blocks"   : n,
            "block_size" : n_sigs,
            "k_per_signal": [len(s.bins) for s in specs],
            "is_full_sn" : True,
        }

        return bs


# ── Convenience function ──────────────────────────────────────────────────────

def auto_build(
    arrays: list[GenerateArray],
    cover_specs: list[CoverSpec] | None = None,
    param_overrides: dict[str, int] | None = None,
) -> list[BridgeResult]:
    """
    One-call convenience wrapper around BinSpaceBuilder.

    Parameters
    ----------
    arrays        : From RtlExtractor.extract()
    cover_specs   : List of CoverSpec objects.  If None, a placeholder
                    4-bin state coverpoint is used for every module type.
    param_overrides : Parameter name → integer value overrides.
    """
    builder = BinSpaceBuilder(arrays)
    if cover_specs:
        builder.cover_specs(cover_specs)
    else:
        # Sensible default: 4-bin state machine coverpoint per instance
        builder.cover(
            "state",
            ["IDLE", "ACTIVE", "STALL", "ERROR"],
            module_type=None,
        )
    return builder.build(param_overrides)


# ── Reporting helper ──────────────────────────────────────────────────────────

def bridge_report(results: list[BridgeResult]) -> str:
    """Formatted summary of all BridgeResults."""
    W = 72
    lines = [
        "═" * W,
        "  Dabih — RTL → Coverage Compression Bridge Report",
        "═" * W,
        f"  {'Module Array':<38} {'N':>3}  {'Raw':>8}  {'Orbits':>7}  {'Ratio':>6}",
        "  " + "-" * (W - 2),
    ]

    total_raw = 0
    total_orbits = 0
    for r in results:
        raw    = r.bin_space.total_bin_count()
        orbits = r.bin_space.orbit_count()
        ratio  = r.compression_ratio()
        label  = f"{r.array.parent_module}.{r.array.module_type}"
        total_raw += raw
        total_orbits += orbits
        lines.append(
            f"  {label:<38} {r.n_instances:>3}  {raw:>8,}  {orbits:>7,}  {ratio:>5.1f}×"
        )

    if results:
        overall = total_raw / total_orbits if total_orbits else 1.0
        pct = 100 * (1 - total_orbits / total_raw) if total_raw else 0.0
        lines += [
            "  " + "-" * (W - 2),
            f"  {'TOTAL':<38} {'':>3}  {total_raw:>8,}  {total_orbits:>7,}  {overall:>5.1f}×",
            f"  Overall reduction: {pct:.1f}% of cross-coverage bins eliminated",
        ]

    lines.append("═" * W)
    return "\n".join(lines)


# ── Internal ──────────────────────────────────────────────────────────────────

def _warn(msg: str) -> None:
    import sys
    print(f"[dabih warning] {msg}", file=sys.stderr)
