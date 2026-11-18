"""
tests/test_core.py
~~~~~~~~~~~~~~~~~~
Unit tests for the Dabih orbit engine.

Tests verify:
  - Permutation algebra (apply, compose, inverse, identity)
  - Group generation (closure, order, trivial group)
  - Orbit correctness (partition completeness, orbit size formulas)
  - Compression ratio math
  - Coverage expansion logic
  - Edge cases (single coverpoint, no symmetry, single bin)
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from dabih.core.symmetry import Permutation, SymmetryGroup
from dabih.core.coverpoint import Coverpoint
from dabih.core.bin_space import BinSpace


# ═══════════════════════════════════════════════════════════════════════════════
# Permutation tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestPermutation:

    def test_identity_apply(self):
        p = Permutation.identity(4)
        assert p.apply((10, 20, 30, 40)) == (10, 20, 30, 40)

    def test_transposition_apply(self):
        p = Permutation.transposition(3, 0, 1)
        assert p.apply((10, 20, 30)) == (20, 10, 30)

    def test_full_cycle_apply(self):
        # 3-cycle: pos i draws from pos (i+1)%3
        # perm = [1, 2, 0]  → result[i] = t[perm[i]]
        # result[0] = t[1], result[1] = t[2], result[2] = t[0]
        p = Permutation.full_cycle(3)
        assert p.apply((10, 20, 30)) == (20, 30, 10)

    def test_invalid_permutation(self):
        with pytest.raises(ValueError):
            Permutation([0, 0, 2])   # 1 is missing, 0 is repeated

    def test_compose_swap_then_swap_is_identity(self):
        swap = Permutation.transposition(3, 0, 1)
        composed = swap.compose(swap)
        assert composed == Permutation.identity(3)

    def test_compose_non_commutative(self):
        g = Permutation.transposition(3, 0, 1)   # swap 0,1
        h = Permutation.transposition(3, 1, 2)   # swap 1,2
        # g∘h: apply h first (0,1)→(0,2), then g swaps indices 0,1
        gh = g.compose(h)
        hg = h.compose(g)
        assert gh != hg

    def test_inverse_cancels(self):
        p = Permutation([2, 0, 1])
        assert p.compose(p.inverse()) == Permutation.identity(3)
        assert p.inverse().compose(p) == Permutation.identity(3)

    def test_cycle_notation_identity(self):
        assert Permutation.identity(4).cycle_notation() == "(identity)"

    def test_cycle_notation_transposition(self):
        p = Permutation.transposition(4, 1, 3)
        assert "1" in p.cycle_notation() and "3" in p.cycle_notation()

    def test_order_of_transposition(self):
        p = Permutation.transposition(5, 0, 1)
        assert p.order() == 2

    def test_order_of_3_cycle(self):
        p = Permutation.full_cycle(3)
        assert p.order() == 3


# ═══════════════════════════════════════════════════════════════════════════════
# SymmetryGroup tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestSymmetryGroup:

    def test_trivial_group_has_order_1(self):
        g = SymmetryGroup(degree=4)
        assert g.order() == 1
        assert g.is_trivial()

    def test_s2_generated_by_one_transposition(self):
        g = SymmetryGroup(degree=2)
        g.add_generator(Permutation.transposition(2, 0, 1))
        assert g.order() == 2  # {id, swap}

    def test_s3_order(self):
        g = SymmetryGroup(degree=3)
        g.add_generator(Permutation.transposition(3, 0, 1))
        g.add_generator(Permutation.full_cycle(3))
        assert g.order() == 6   # 3!

    def test_s4_order(self):
        g = SymmetryGroup(degree=4)
        g.add_generator(Permutation.transposition(4, 0, 1))
        g.add_generator(Permutation.full_cycle(4))
        assert g.order() == 24  # 4!

    def test_s5_order(self):
        g = SymmetryGroup(degree=5)
        g.add_generator(Permutation.transposition(5, 0, 1))
        g.add_generator(Permutation.full_cycle(5))
        assert g.order() == 120  # 5!

    def test_z2_subgroup(self):
        """Z2 subgroup of S4: only swap(0,1), not the full S4."""
        g = SymmetryGroup(degree=4)
        g.add_generator(Permutation.transposition(4, 0, 1))
        # Generated group = {id, swap(0,1)} — order 2
        assert g.order() == 2

    def test_generators_and_inverses_deduplicates_involution(self):
        """A transposition equals its own inverse — should not duplicate."""
        g = SymmetryGroup(degree=3)
        swap = Permutation.transposition(3, 0, 1)
        g.add_generator(swap)
        gens = g.generators_and_inverses()
        # swap is self-inverse, so only one unique element
        assert len(gens) == 1


# ═══════════════════════════════════════════════════════════════════════════════
# BinSpace / Orbit tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestBinSpace:

    def _make_lane_space(self, n_lanes: int, n_bins: int) -> BinSpace:
        bins = [f"b{i}" for i in range(n_bins)]
        bs = BinSpace()
        for i in range(n_lanes):
            bs.add_coverpoint(Coverpoint.from_names(f"cp{i}", bins))
        bs.add_full_lane_symmetry(n_lanes=n_lanes)
        return bs

    # ── Orbit partition correctness ───────────────────────────────────────────

    def test_no_symmetry_all_bins_are_orbits(self):
        """Without symmetry, every bin is its own equivalence class."""
        bs = BinSpace()
        bs.add_coverpoint(Coverpoint.from_names("cp0", ["A", "B", "C"]))
        bs.add_coverpoint(Coverpoint.from_names("cp1", ["X", "Y"]))
        orbits = bs.compute_orbits()
        assert len(orbits) == 6  # 3 × 2
        assert all(o.size() == 1 for o in orbits)

    def test_orbits_partition_the_space(self):
        """Union of all orbit members = full bin space, no overlaps."""
        bs = self._make_lane_space(3, 4)
        orbits = bs.compute_orbits()
        all_members = []
        for o in orbits:
            all_members.extend(o.members)
        assert len(all_members) == bs.total_bin_count()
        assert len(set(all_members)) == len(all_members)  # no duplicates

    def test_representative_is_in_orbit(self):
        bs = self._make_lane_space(3, 4)
        for orbit in bs.compute_orbits():
            assert orbit.representative in orbit.members

    def test_representative_is_lex_min(self):
        bs = self._make_lane_space(3, 4)
        for orbit in bs.compute_orbits():
            assert orbit.representative == min(orbit.members)

    # ── Orbit count formula (multisets) ───────────────────────────────────────
    # Under S_n with k bins per coverpoint, orbit count = C(n+k-1, k)

    def test_s2_2bins_orbits(self):
        # C(2+2-1, 2) = C(3,2) = 3
        bs = self._make_lane_space(2, 2)
        assert bs.orbit_count() == 3

    def test_s3_4bins_orbits(self):
        # C(3+4-1, 4) = C(6,4) = 15  -- wait, let me recalculate
        # Multisets of size n from k symbols = C(n+k-1, n)
        # n=3 lanes, k=4 bin states: C(4+3-1, 3) = C(6,3) = 20
        bs = self._make_lane_space(3, 4)
        assert bs.orbit_count() == 20

    def test_s8_4bins_orbits(self):
        # C(4+8-1, 8) = C(11,8) = C(11,3) = 165
        bs = self._make_lane_space(8, 4)
        assert bs.orbit_count() == 165

    def test_s2_4bins_orbits(self):
        # C(4+2-1, 2) = C(5,2) = 10
        bs = self._make_lane_space(2, 4)
        assert bs.orbit_count() == 10

    # ── Compression metrics ───────────────────────────────────────────────────

    def test_compression_ratio_s3_4bins(self):
        bs = self._make_lane_space(3, 4)
        # 4^3 = 64 total, 20 orbits
        assert bs.total_bin_count() == 64
        assert abs(bs.compression_ratio() - 64 / 20) < 0.01

    def test_compression_ratio_no_symmetry_is_1(self):
        bs = BinSpace()
        bs.add_coverpoint(Coverpoint.from_names("cp", ["A", "B", "C"]))
        assert bs.compression_ratio() == 1.0

    # ── Partial symmetry ──────────────────────────────────────────────────────

    def test_partial_symmetry_swap_two_of_four(self):
        """Only coverpoints 1 and 2 are symmetric — 50% of pairs, not S4."""
        bs = BinSpace()
        for i in range(4):
            bs.add_coverpoint(Coverpoint.from_names(f"cp{i}", ["A", "B"]))
        # Only swap coverpoints 1 ↔ 2
        bs.add_symmetry([0, 2, 1, 3])

        # Full space: 2^4 = 16 bins.  Swap(cp1, cp2): (a,b,c,d) ~ (a,c,b,d)
        #
        # Fixed points (b = c): a∈{0,1}, b=c∈{0,1}, d∈{0,1} → 2×2×2 = 8 orbits of size 1
        # Non-fixed  (b ≠ c): 16 - 8 = 8 bins, each forming a 2-element orbit
        #                      → 4 orbits of size 2
        # Total: 8 + 4 = 12 orbits
        assert bs.orbit_count() == 12

    # ── Coverage expansion ────────────────────────────────────────────────────

    def test_expand_coverage_full(self):
        """Hitting all representatives should mark all bins as covered."""
        bs = self._make_lane_space(3, 4)
        all_reps = set(bs.select_representatives())
        full_map = bs.expand_coverage(all_reps)
        assert all(full_map.values())
        assert len(full_map) == bs.total_bin_count()

    def test_expand_coverage_empty(self):
        """Hitting no representatives: nothing covered."""
        bs = self._make_lane_space(3, 4)
        empty_map = bs.expand_coverage(set())
        assert not any(empty_map.values())

    def test_expand_coverage_one_rep(self):
        """Hitting one representative covers exactly its orbit."""
        bs = self._make_lane_space(3, 4)
        orbits = bs.compute_orbits()
        target_orbit = orbits[5]  # arbitrary
        hit = {target_orbit.representative}
        cov_map = bs.expand_coverage(hit)

        covered = {bt for bt, v in cov_map.items() if v}
        assert covered == set(target_orbit.members)

    def test_coverage_stats_accuracy(self):
        bs = self._make_lane_space(3, 4)
        reps = bs.select_representatives()
        # Hit half of representatives (round down)
        hit = set(reps[:10])
        stats = bs.coverage_stats(hit)
        assert stats["classes_hit"] == 10
        assert stats["classes_total"] == 20
        assert abs(stats["class_coverage_pct"] - 50.0) < 0.01

    # ── Edge cases ────────────────────────────────────────────────────────────

    def test_single_coverpoint_no_cross(self):
        bs = BinSpace()
        bs.add_coverpoint(Coverpoint.from_names("cp", ["A", "B", "C", "D"]))
        orbits = bs.compute_orbits()
        assert len(orbits) == 4  # no cross, each bin is its own class

    def test_single_bin_per_coverpoint(self):
        bs = self._make_lane_space(5, 1)
        assert bs.total_bin_count() == 1
        assert bs.orbit_count() == 1
        assert bs.compression_ratio() == 1.0

    def test_builder_chaining(self):
        """Verify fluent builder API returns self."""
        bs = BinSpace()
        result = (bs
                  .add_coverpoint(Coverpoint.from_names("cp0", ["A", "B"]))
                  .add_coverpoint(Coverpoint.from_names("cp1", ["A", "B"]))
                  .add_symmetry([1, 0]))
        assert result is bs

    def test_cache_invalidated_on_new_coverpoint(self):
        bs = BinSpace()
        bs.add_coverpoint(Coverpoint.from_names("cp0", ["A", "B"]))
        first = bs.compute_orbits()
        bs.add_coverpoint(Coverpoint.from_names("cp1", ["A", "B"]))
        bs.add_symmetry([1, 0])
        second = bs.compute_orbits()
        assert len(first) != len(second)


# ═══════════════════════════════════════════════════════════════════════════════
# Coverpoint convenience constructors
# ═══════════════════════════════════════════════════════════════════════════════

class TestCoverpoint:

    def test_from_names(self):
        cp = Coverpoint.from_names("sig", ["A", "B", "C"])
        assert cp.bin_count() == 3
        assert cp.bin_label(1) == "B"

    def test_from_range(self):
        cp = Coverpoint.from_range("addr", 0, 7)
        assert cp.bin_count() == 8
        assert cp.bin_label(0) == "addr_0"
        assert cp.bin_label(7) == "addr_7"

    def test_value_class_bins(self):
        cp = Coverpoint.value_class_bins("data")
        assert cp.bin_count() == 6
        assert cp.bin_label(0) == "ZERO"
        assert cp.bin_label(5) == "ALL_ONES"

    def test_builder_add_bins(self):
        cp = Coverpoint("test").add_bins(["X", "Y", "Z"])
        assert cp.bin_count() == 3


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
