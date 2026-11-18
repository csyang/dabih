"""
dabih.core.bin_space
~~~~~~~~~~~~~~~~~~~~
Core orbit engine: partitions a cross-coverage bin space into equivalence
classes (orbits) under a symmetry group and selects minimal representatives.

Algorithm
---------
Orbit computation uses BFS over the generator set (plus inverses) rather
than the full group.  This is correct because the orbit of any element x
under G equals the orbit of x under any generating set for G, and BFS
over generators explores every orbit member in O(|orbit|) generator
applications rather than O(|orbit| × |G|).

For a cross-coverage space of size B and a generator set of size k,
total work is O(k × B) — linear in the bin space regardless of group size.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from itertools import product as cartesian_product
from typing import Callable

from .coverpoint import Coverpoint
from .symmetry import Permutation, SymmetryGroup


# ── Types ─────────────────────────────────────────────────────────────────────

# A cross-coverage bin is a tuple of bin indices, one per coverpoint.
BinTuple = tuple[int, ...]

# Human-readable form: tuple of bin label strings.
BinLabel = tuple[str, ...]


# ── Orbit ─────────────────────────────────────────────────────────────────────

@dataclass
class Orbit:
    """
    One equivalence class of cross-coverage bins.

    All members are behaviorally equivalent under the declared symmetry group.
    Hitting the representative bin during simulation is sufficient to claim
    coverage for every member.
    """
    id: int
    members: list[BinTuple]
    representative: BinTuple

    def size(self) -> int:
        return len(self.members)

    def __repr__(self) -> str:
        return (
            f"Orbit(id={self.id}, size={self.size()}, "
            f"representative={self.representative})"
        )


# ── BinSpace ──────────────────────────────────────────────────────────────────

class BinSpace:
    """
    The Dabih orbit engine: Coverage Model Compression via Equivalence Classes.

    Workflow
    --------
    1.  Add coverpoints            →  define the cross-coverage space
    2.  Add symmetry generators    →  declare which permutations are valid
    3.  compute_orbits()           →  partition the space into equivalence classes
    4.  select_representatives()   →  the compressed coverage model
    5.  report()                   →  human-readable compression summary

    Example
    -------
        from dabih.core.coverpoint import Coverpoint
        from dabih.core.bin_space import BinSpace
        from dabih.core.symmetry import Permutation

        state_bins = ["IDLE", "ACTIVE", "STALL", "ERROR"]
        bs = BinSpace(name="3-lane interface")
        for i in range(3):
            bs.add_coverpoint(Coverpoint.from_names(f"lane{i}_state", state_bins))

        # All three lanes are structurally symmetric (S3)
        bs.add_symmetry([1, 0, 2])   # swap lane 0 ↔ lane 1
        bs.add_symmetry([1, 2, 0])   # rotate lane 0 → 1 → 2

        print(bs.report())
    """

    def __init__(self, name: str = ""):
        self.name = name
        self._coverpoints: list[Coverpoint] = []
        self._group: SymmetryGroup | None = None
        self._orbits: list[Orbit] | None = None
        # Structured intent log — read by Idea D (formal verification pass)
        # and by SymbolicOrbitEngine profile detection.
        self._symmetry_declarations: list[dict] = []

    # ── Construction ─────────────────────────────────────────────────────────

    def add_coverpoint(self, cp: Coverpoint) -> BinSpace:
        """Append a coverpoint dimension to the cross-coverage space."""
        self._invalidate_all()
        self._coverpoints.append(cp)
        return self

    def add_symmetry(self, perm: list[int] | Permutation) -> BinSpace:
        """
        Add a symmetry generator expressed as a permutation of coverpoint indices.

        perm[i] = j  means  "coverpoint i may be exchanged with coverpoint j
                             without changing verification semantics."

        Example:  [1, 0, 2]  swaps coverpoints 0 and 1.

        Prefer the higher-level methods (add_instance_symmetry, etc.) when
        working with instance-indexed hardware structures — they are more
        readable, less error-prone, and preserve structured intent for Idea D.
        """
        self._invalidate_orbits()
        if self._group is None:
            self._group = SymmetryGroup(degree=len(self._coverpoints))
        if isinstance(perm, list):
            perm = Permutation(perm)
        self._group.add_generator(perm)
        return self

    def add_full_lane_symmetry(self, n_lanes: int) -> BinSpace:
        """
        Declare the full symmetric group Sₙ over the first n_lanes instances.

        Convenience wrapper around add_instance_symmetry for the common case
        where ALL instances are symmetric (clean generate-for arrays).
        block_size is inferred as len(coverpoints) / n_lanes.

        For partial symmetry (only some instances equivalent) use
        add_instance_symmetry(instance_indices=[...]) instead.
        """
        if n_lanes < 2:
            return self
        block_size = len(self._coverpoints) // n_lanes
        return self.add_instance_symmetry(
            instance_indices=list(range(n_lanes)),
            block_size=block_size,
        )

    # ── Ergonomic partial-symmetry API (OQ-05) ────────────────────────────────

    def add_instance_symmetry(
        self,
        instance_indices: list[int],
        block_size: int = 1,
    ) -> BinSpace:
        """
        Declare that a specific subset of instances are mutually symmetric,
        generating the full symmetric group Sₖ on those k instances.

        This is the primary API for partial symmetry: use it when only some
        instances in a generate-for array are behaviourally equivalent (e.g.
        lane 0 has special management logic, lanes 1–N are uniform).

        Parameters
        ----------
        instance_indices :
            Which instances are mutually symmetric, as a list of integer
            instance indices (0-based).  Must have at least 2 entries.
            The instances need not be contiguous.
        block_size :
            Number of coverpoints per instance (number of signals declared
            per instance).  Default 1 for single-signal spaces.
            Must satisfy: max(instance_indices) * block_size < len(coverpoints).

        Examples
        --------
        # 4-stage pipeline: only stages 1 and 2 are equivalent
        bs.add_instance_symmetry(instance_indices=[1, 2], block_size=2)

        # 8-lane array: lane 0 is special, lanes 1-7 are symmetric
        bs.add_instance_symmetry(instance_indices=list(range(1, 8)))

        # All 4 lanes symmetric (equivalent to add_full_lane_symmetry(4))
        bs.add_instance_symmetry(instance_indices=[0, 1, 2, 3])

        Notes
        -----
        Generates Sₖ using two generators: transposition(indices[0], indices[1])
        and k-cycle(indices[0] → indices[1] → ... → indices[k-1]).  Two
        generators suffice for any Sₖ regardless of k.
        """
        if len(instance_indices) < 2:
            return self

        self._validate_instance_indices(instance_indices, block_size)
        n = len(self._coverpoints)

        def _block_swap(ia: int, ib: int) -> list[int]:
            perm = list(range(n))
            for k in range(block_size):
                perm[ia * block_size + k] = ib * block_size + k
                perm[ib * block_size + k] = ia * block_size + k
            return perm

        def _block_cycle(indices: list[int]) -> list[int]:
            perm = list(range(n))
            m = len(indices)
            for step in range(m):
                src = indices[step]
                dst = indices[(step + 1) % m]
                for k in range(block_size):
                    perm[src * block_size + k] = dst * block_size + k
            return perm

        # Sₖ generated by: swap(indices[0], indices[1]) + k-cycle
        self.add_symmetry(_block_swap(instance_indices[0], instance_indices[1]))
        if len(instance_indices) >= 3:
            self.add_symmetry(_block_cycle(instance_indices))

        # Record structured declaration for Idea D and symbolic engine
        self._symmetry_declarations.append({
            "type"             : "instance",
            "instance_indices" : list(instance_indices),
            "block_size"       : block_size,
            "group"            : f"S{len(instance_indices)}",
            "n_generators"     : 2 if len(instance_indices) >= 3 else 1,
        })
        return self

    def add_cyclic_symmetry(
        self,
        instance_indices: list[int],
        block_size: int = 1,
    ) -> BinSpace:
        """
        Declare cyclic symmetry Zₙ on a set of instances.

        Use when instances form a ring — each is the "next" of the previous
        — so only rotations are valid symmetries, not arbitrary permutations.
        This generates a smaller group than add_instance_symmetry (Zₙ vs Sₙ),
        giving a valid but not maximally compressed coverage model.

        Parameters
        ----------
        instance_indices :
            Instances forming the cycle, in cycle order:
            indices[0] → indices[1] → ... → indices[-1] → indices[0].
        block_size :
            Coverpoints per instance.

        Example
        -------
        # 4-node ring interconnect
        bs.add_cyclic_symmetry(instance_indices=[0, 1, 2, 3])
        """
        if len(instance_indices) < 2:
            return self

        self._validate_instance_indices(instance_indices, block_size)
        n = len(self._coverpoints)

        def _block_cycle(indices: list[int]) -> list[int]:
            perm = list(range(n))
            m = len(indices)
            for step in range(m):
                src = indices[step]
                dst = indices[(step + 1) % m]
                for k in range(block_size):
                    perm[src * block_size + k] = dst * block_size + k
            return perm

        # Zₙ generated by a single n-cycle
        self.add_symmetry(_block_cycle(instance_indices))

        self._symmetry_declarations.append({
            "type"             : "cyclic",
            "instance_indices" : list(instance_indices),
            "block_size"       : block_size,
            "group"            : f"Z{len(instance_indices)}",
            "n_generators"     : 1,
        })
        return self

    def add_pairwise_symmetry(
        self,
        pairs: list[tuple[int, int]],
        block_size: int = 1,
    ) -> BinSpace:
        """
        Declare independent pairwise symmetry between specific instance pairs.

        Each pair (ia, ib) generates an independent Z₂ swap.  The combined
        group is Z₂ × Z₂ × ... (one factor per pair) — smaller than the
        full symmetric group over all involved instances.

        Use when instances cluster into symmetric pairs that are not
        interchangeable across cluster boundaries.

        Parameters
        ----------
        pairs :
            List of (ia, ib) instance index pairs.  Each pair is symmetric
            with each other but not with instances in other pairs.
        block_size :
            Coverpoints per instance.

        Example
        -------
        # Lanes 0↔1 are symmetric, lanes 2↔3 are symmetric,
        # but lane 0 is NOT equivalent to lane 2.
        bs.add_pairwise_symmetry(pairs=[(0, 1), (2, 3)])

        # A single pair (equivalent to add_instance_symmetry([ia, ib]))
        bs.add_pairwise_symmetry(pairs=[(1, 3)])
        """
        if not pairs:
            return self

        all_indices = [i for pair in pairs for i in pair]
        self._validate_instance_indices(all_indices, block_size)
        n = len(self._coverpoints)

        for ia, ib in pairs:
            perm = list(range(n))
            for k in range(block_size):
                perm[ia * block_size + k] = ib * block_size + k
                perm[ib * block_size + k] = ia * block_size + k
            self.add_symmetry(perm)

        self._symmetry_declarations.append({
            "type"      : "pairwise",
            "pairs"     : [list(p) for p in pairs],
            "block_size": block_size,
            "group"     : "×".join(["Z2"] * len(pairs)),
            "n_generators": len(pairs),
        })
        return self

    def symmetry_declarations(self) -> list[dict]:
        """
        Return the structured symmetry declarations made on this BinSpace.

        Each entry records the high-level intent (type, instance indices,
        block size, group name) rather than raw permutation indices.  Used
        by Idea D (formal verification pass) to generate named properties
        and by SymbolicOrbitEngine to determine the symmetry profile.

        Returns a copy — the internal list is not exposed directly.
        """
        return list(self._symmetry_declarations)

    # ── Validation ────────────────────────────────────────────────────────────

    def _validate_instance_indices(
        self,
        instance_indices: list[int],
        block_size: int,
    ) -> None:
        """Raise ValueError if instance_indices or block_size are inconsistent."""
        n_cps = len(self._coverpoints)
        if block_size < 1:
            raise ValueError(f"block_size must be ≥ 1, got {block_size}")
        if n_cps == 0:
            raise ValueError(
                "Cannot declare symmetry before adding coverpoints."
            )
        if n_cps % block_size != 0:
            raise ValueError(
                f"block_size={block_size} does not divide "
                f"coverpoint count={n_cps} evenly."
            )
        n_instances = n_cps // block_size
        for idx in instance_indices:
            if idx < 0 or idx >= n_instances:
                raise ValueError(
                    f"Instance index {idx} out of range [0, {n_instances - 1}] "
                    f"(block_size={block_size}, coverpoints={n_cps})."
                )

    # ── Core engine ───────────────────────────────────────────────────────────

    def _invalidate_orbits(self):
        """Clear cached orbits only (symmetry group is preserved)."""
        self._orbits = None

    def _invalidate_all(self):
        """Clear both cached orbits and the symmetry group (structural change)."""
        self._orbits = None
        self._group = None

    def _get_group(self) -> SymmetryGroup:
        if self._group is None:
            self._group = SymmetryGroup(degree=len(self._coverpoints))
        return self._group

    def _all_bins(self) -> list[BinTuple]:
        """Enumerate the full Cartesian product cross-coverage space."""
        ranges = [range(cp.bin_count()) for cp in self._coverpoints]
        return list(cartesian_product(*ranges))

    def total_bin_count(self) -> int:
        """Size of the full cross-coverage space before compression."""
        result = 1
        for cp in self._coverpoints:
            result *= cp.bin_count()
        return result

    def compute_orbits(self) -> list[Orbit]:
        """
        Partition the cross-coverage bin space into equivalence classes.

        Uses BFS over the generator set (plus inverses) — O(k × |B|) where
        k = number of generators and |B| = total cross bins.  Does NOT
        require enumerating the full group.

        Returns a stable list of Orbit objects sorted by representative.
        Caches the result; re-computed only when the space or group changes.
        """
        if self._orbits is not None:
            return self._orbits

        group = self._get_group()
        gens = group.generators_and_inverses()  # generators + inverses only
        trivial = group.is_trivial()

        all_bins = self._all_bins()
        visited: set[BinTuple] = set()
        orbits: list[Orbit] = []

        for start in all_bins:
            if start in visited:
                continue

            if trivial:
                # No symmetry declared: every bin is its own equivalence class
                orbit_members = [start]
            else:
                # BFS over generators to discover the orbit
                orbit_set: set[BinTuple] = {start}
                frontier: list[BinTuple] = [start]
                while frontier:
                    current = frontier.pop()
                    for g in gens:
                        neighbor = g.apply(current)
                        if neighbor not in orbit_set:
                            orbit_set.add(neighbor)
                            frontier.append(neighbor)
                orbit_members = sorted(orbit_set)

            visited.update(orbit_members)
            rep = orbit_members[0]  # lex-min as canonical representative
            orbits.append(
                Orbit(id=len(orbits), members=orbit_members, representative=rep)
            )

        self._orbits = orbits
        return orbits

    # ── Coverage expansion (back-end / post-simulation) ───────────────────────

    def expand_coverage(
        self, hit_representatives: set[BinTuple]
    ) -> dict[BinTuple, bool]:
        """
        Given the set of representative bins hit during simulation, expand to
        the full coverage map: every member of each hit orbit is marked covered.

        This is the Idea C back-end: pure data transformation, no simulator
        integration needed.

        Parameters
        ----------
        hit_representatives :
            BinTuples of representatives observed during simulation.

        Returns
        -------
        dict mapping every BinTuple in the full space → covered (bool).
        """
        orbits = self.compute_orbits()
        rep_to_orbit: dict[BinTuple, Orbit] = {o.representative: o for o in orbits}

        result: dict[BinTuple, bool] = {}
        for orbit in orbits:
            covered = orbit.representative in hit_representatives
            for member in orbit.members:
                result[member] = covered
        return result

    def coverage_stats(
        self, hit_representatives: set[BinTuple]
    ) -> dict:
        """
        Compute coverage statistics from a set of hit representatives.

        Returns a dict with keys:
            classes_hit, classes_total, bins_implied_covered,
            bins_total, class_coverage_pct, bin_coverage_pct
        """
        orbits = self.compute_orbits()
        classes_hit = sum(
            1 for o in orbits if o.representative in hit_representatives
        )
        bins_implied = sum(
            o.size() for o in orbits if o.representative in hit_representatives
        )
        total_bins = self.total_bin_count()

        return {
            "classes_hit": classes_hit,
            "classes_total": len(orbits),
            "bins_implied_covered": bins_implied,
            "bins_total": total_bins,
            "class_coverage_pct": 100 * classes_hit / len(orbits) if orbits else 0,
            "bin_coverage_pct": 100 * bins_implied / total_bins if total_bins else 0,
        }

    # ── Accessors ─────────────────────────────────────────────────────────────

    def select_representatives(self) -> list[BinTuple]:
        """The minimal set of bins that must be hit to achieve full coverage."""
        return [o.representative for o in self.compute_orbits()]

    def orbit_count(self) -> int:
        return len(self.compute_orbits())

    def compression_ratio(self) -> float:
        """total_bins / orbit_count — higher is better."""
        n = self.orbit_count()
        return self.total_bin_count() / n if n > 0 else 1.0

    def compression_pct(self) -> float:
        """Percentage of bins eliminated by compression."""
        total = self.total_bin_count()
        reduced = self.orbit_count()
        return 100 * (1 - reduced / total) if total > 0 else 0.0

    # ── Formatting helpers ────────────────────────────────────────────────────

    def bin_label(self, bt: BinTuple) -> BinLabel:
        """Convert a BinTuple of indices to a tuple of human-readable names."""
        return tuple(
            self._coverpoints[i].bin_label(v) for i, v in enumerate(bt)
        )

    # ── Report ────────────────────────────────────────────────────────────────

    def report(self, max_orbits: int = 40) -> str:
        """Return a formatted compression report."""
        orbits = self.compute_orbits()
        group = self._get_group()
        total = self.total_bin_count()
        n_orbits = len(orbits)
        ratio = self.compression_ratio()
        eliminated = total - n_orbits

        W = 64
        lines = [
            "═" * W,
            f"  Dabih — Coverage Compression Report",
            f"  {'  ' + self.name if self.name else ''}",
            "═" * W,
        ]

        lines.append("  Coverpoints:")
        for cp in self._coverpoints:
            lines.append(f"    {cp.name:<35s}  {cp.bin_count():>4d} bins")

        lines += [
            "─" * W,
            f"  Symmetry group order       :  {group.order():>12,}",
            f"  Generators declared        :  {len(group.generators):>12}",
            "─" * W,
            f"  Total cross-coverage bins  :  {total:>12,}",
            f"  Equivalence classes        :  {n_orbits:>12,}",
            f"  Bins eliminated            :  {eliminated:>12,}  ({self.compression_pct():.1f}%)",
            f"  Compression ratio          :  {ratio:>11.2f}×",
            "─" * W,
        ]

        shown = min(max_orbits, n_orbits)
        lines.append(
            f"  Representatives  (showing {shown} of {n_orbits}):"
        )

        for orbit in orbits[:shown]:
            rep_label = str(self.bin_label(orbit.representative))
            size_str = f"covers {orbit.size():>4d} bins"
            lines.append(f"    [{orbit.id:>4d}]  {rep_label:<42s}  {size_str}")

        if n_orbits > shown:
            lines.append(f"    ... {n_orbits - shown} more orbits not shown ...")

        lines.append("═" * W)
        return "\n".join(lines)
