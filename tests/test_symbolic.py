"""
tests/test_symbolic.py
~~~~~~~~~~~~~~~~~~~~~~~
Tests for Idea E: symbolic orbit engine.

Covers:
  SymbolicOrbitEngine
    - Method selection (polya / burnside / limit error)
    - Pólya count correctness vs BFS for small spaces
    - Burnside count correctness vs BFS for partial-symmetry groups
    - Closed-form formula verification: C(n+K-1, n)
    - Block-symmetric spaces (multi-signal)
    - Previously infeasible large spaces (8-lane × 2-signal)
    - canonical() — sorted block-value tuple
    - orbit_of() — full orbit enumeration
    - is_same_orbit() — equivalence check
    - representatives() — Sₙ enumeration via combinations_with_replacement
    - compression_ratio() — analytic

  SymbolicExpansionEngine
    - Full coverage (all reps hit)
    - Partial coverage
    - Non-rep hit propagation
    - Unresolved labels
    - merge_and_expand
    - is_covered / orbit_coverage_of
    - SymbolicExpansionResult statistics
    - report() content
    - to_dict() structure
    - Compatibility with RTL bridge hint

  Integration
    - BFS orbit count == Symbolic orbit count for all small cases
    - Bridge hint propagation end-to-end
    - Large space (8-lane, previously infeasible with BFS)
"""

import sys, os, math
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from itertools import combinations_with_replacement

from dabih.core.bin_space import BinSpace
from dabih.core.coverpoint import Coverpoint
from dabih.core.symmetry import Permutation
from dabih.core.symbolic import (
    SymbolicOrbitEngine, SymmetryProfile, SymbolicLimitError,
    _cycle_count_direct, _cycle_count_blocks, BURNSIDE_LIMIT,
)
from dabih.coverage.result import CoverageResult
from dabih.coverage.symbolic_expander import (
    SymbolicExpansionEngine, SymbolicExpansionResult,
)

FIXTURES = os.path.join(os.path.dirname(__file__), "..", "examples", "rtl")
def fx(n): return os.path.join(FIXTURES, n)


# ── BinSpace factories ────────────────────────────────────────────────────────

def make_direct_sn(n: int, k: int) -> BinSpace:
    """Direct Sₙ on n coverpoints of k bins each."""
    bs = BinSpace(name=f"S{n}_k{k}")
    bins = [f"b{i}" for i in range(k)]
    for i in range(n):
        bs.add_coverpoint(Coverpoint.from_names(f"cp{i}", bins))
    bs.add_full_lane_symmetry(n)
    return bs

def make_block_sn(n: int, k_per_signal: list[int]) -> BinSpace:
    """Block Sₙ on n instances, each with len(k_per_signal) signals."""
    from dabih.rtl.bridge import BinSpaceBuilder, CoverSpec
    from dabih.rtl.generate_array import GenerateArray

    # Build a synthetic GenerateArray
    arr = GenerateArray(
        parent_module="top", block_label="gen",
        module_type="mod", instance_base="u",
        genvar="i", bound_kind="literal", bound_value=n,
        bound_param=None, param_default=None,
        source_file="synthetic.sv",
    )
    specs = [
        CoverSpec(f"sig{j}", [f"b{v}" for v in range(k_per_signal[j])])
        for j in range(len(k_per_signal))
    ]
    results = BinSpaceBuilder([arr]).cover_specs(specs).build()
    return results[0].bin_space

def make_partial_swap(n_cps: int, swap_i: int, swap_j: int, k: int) -> BinSpace:
    """Group Z2: only swap coverpoints swap_i and swap_j."""
    bs = BinSpace(name=f"partial_swap({swap_i},{swap_j})")
    bins = [f"b{v}" for v in range(k)]
    for i in range(n_cps):
        bs.add_coverpoint(Coverpoint.from_names(f"cp{i}", bins))
    perm = list(range(n_cps))
    perm[swap_i], perm[swap_j] = perm[swap_j], perm[swap_i]
    bs.add_symmetry(perm)
    return bs


# ═══════════════════════════════════════════════════════════════════════════════
# Cycle count helpers
# ═══════════════════════════════════════════════════════════════════════════════

class TestCycleCountHelpers:

    def test_cycle_count_identity(self):
        p = Permutation.identity(4)
        assert _cycle_count_direct(p) == 4

    def test_cycle_count_transposition(self):
        p = Permutation.transposition(4, 0, 1)
        # Cycles: (0,1)(2)(3) → 3
        assert _cycle_count_direct(p) == 3

    def test_cycle_count_full_cycle_n3(self):
        p = Permutation.full_cycle(3)
        # One 3-cycle → 1 cycle
        assert _cycle_count_direct(p) == 1

    def test_block_cycle_count_identity_block2(self):
        # Identity on 4 = 2 blocks of 2: two block-cycles
        p = Permutation.identity(4)
        assert _cycle_count_blocks(p, 2) == 2

    def test_block_cycle_count_swap_blocks(self):
        # Swap blocks 0,1 of size 2: perm = [2,3,0,1]
        p = Permutation([2, 3, 0, 1])
        # Block perm: 0→1, 1→0 → one 2-cycle → 1 block-cycle
        assert _cycle_count_blocks(p, 2) == 1


# ═══════════════════════════════════════════════════════════════════════════════
# SymbolicOrbitEngine — method selection
# ═══════════════════════════════════════════════════════════════════════════════

class TestMethodSelection:

    def test_full_sn_uses_polya(self):
        bs = make_direct_sn(4, 4)
        eng = SymbolicOrbitEngine(bs)
        assert eng.method_used() == "polya"

    def test_block_sn_uses_polya(self):
        bs = make_block_sn(4, [4, 2])
        eng = SymbolicOrbitEngine(bs)
        assert eng.method_used() == "polya"

    def test_partial_symmetry_uses_burnside(self):
        bs = make_partial_swap(4, 1, 2, 3)
        eng = SymbolicOrbitEngine(bs)
        # Group order = 2, well within Burnside limit
        assert eng.method_used() == "burnside"

    def test_trivial_group_uses_burnside(self):
        bs = BinSpace()
        bs.add_coverpoint(Coverpoint.from_names("cp", ["A","B","C"]))
        eng = SymbolicOrbitEngine(bs)
        assert eng.method_used() == "burnside"


# ═══════════════════════════════════════════════════════════════════════════════
# Pólya count correctness
# ═══════════════════════════════════════════════════════════════════════════════

class TestPolyaCount:
    """Verify C(n+k-1, n) for direct Sₙ and C(n+K-1, n) for block Sₙ."""

    def _bfs_count(self, bs: BinSpace) -> int:
        return bs.orbit_count()

    def _sym_count(self, bs: BinSpace) -> int:
        return SymbolicOrbitEngine(bs).count_orbits()

    # ── Direct Sₙ ─────────────────────────────────────────────────────────────

    def test_s2_k2(self):
        bs = make_direct_sn(2, 2)
        assert self._sym_count(bs) == math.comb(2+2-1, 2) == 3

    def test_s2_k4(self):
        bs = make_direct_sn(2, 4)
        expected = math.comb(2+4-1, 2)   # C(5,2) = 10
        assert self._sym_count(bs) == expected
        assert self._sym_count(bs) == self._bfs_count(bs)

    def test_s3_k4(self):
        bs = make_direct_sn(3, 4)
        expected = math.comb(3+4-1, 3)   # C(6,3) = 20
        assert self._sym_count(bs) == expected
        assert self._sym_count(bs) == self._bfs_count(bs)

    def test_s4_k4(self):
        bs = make_direct_sn(4, 4)
        expected = math.comb(4+4-1, 4)   # C(7,4) = 35
        assert self._sym_count(bs) == expected
        assert self._sym_count(bs) == self._bfs_count(bs)

    def test_s5_k3(self):
        bs = make_direct_sn(5, 3)
        expected = math.comb(5+3-1, 5)   # C(7,5) = 21
        assert self._sym_count(bs) == expected
        assert self._sym_count(bs) == self._bfs_count(bs)

    def test_s8_k4(self):
        # 4^8 = 65,536 bins → 165 orbits  (previously needed BFS)
        bs = make_direct_sn(8, 4)
        expected = math.comb(8+4-1, 8)   # C(11,8) = 165
        assert self._sym_count(bs) == expected

    # ── Block Sₙ ──────────────────────────────────────────────────────────────

    def test_block_s2_k42(self):
        # 2 instances, signals: 4-bin + 2-bin → K=8
        bs = make_block_sn(2, [4, 2])
        K = 4 * 2
        expected = math.comb(2+K-1, 2)   # C(9,2) = 36
        assert self._sym_count(bs) == expected
        assert self._sym_count(bs) == self._bfs_count(bs)

    def test_block_s4_k42(self):
        # 4 instances, signals: 4-bin + 2-bin → K=8
        bs = make_block_sn(4, [4, 2])
        K = 8
        expected = math.comb(4+K-1, 4)   # C(11,4) = 330
        assert self._sym_count(bs) == expected
        assert self._sym_count(bs) == self._bfs_count(bs)

    def test_block_s3_k43(self):
        # 3 instances, signals: 4-bin + 3-bin → K=12
        bs = make_block_sn(3, [4, 3])
        K = 12
        expected = math.comb(3+K-1, 3)   # C(14,3) = 364
        assert self._sym_count(bs) == expected

    # ── Previously infeasible: 8 lanes × 2 signals ───────────────────────────

    def test_block_s8_k42_previously_infeasible(self):
        """
        8 lanes × (4-bin state + 2-bin ready) = (4×2)^8 = 16,777,216 bins.
        BFS OOMs.  Pólya: C(8+8-1, 8) = C(15,8) = 6,435 orbits.
        """
        bs = make_block_sn(8, [4, 2])
        K = 8
        expected = math.comb(8+K-1, 8)   # C(15,8) = 6435
        assert self._sym_count(bs) == expected
        assert expected == 6435

    def test_block_s8_k46_value_classes_infeasible(self):
        """
        8 lanes × (4-bin state + 6-bin value_class) = (4×6)^8 ≈ 110B bins.
        BFS impossible.  Pólya: C(8+24-1, 8) = C(31,8) = 7,888,725 orbits.
        """
        bs = make_block_sn(8, [4, 6])
        K = 24
        expected = math.comb(8+K-1, 8)
        assert SymbolicOrbitEngine(bs).count_orbits() == expected


# ═══════════════════════════════════════════════════════════════════════════════
# Burnside count correctness
# ═══════════════════════════════════════════════════════════════════════════════

class TestBurnsideCount:
    """Burnside for partial-symmetry and trivial groups."""

    def _sym_count(self, bs): return SymbolicOrbitEngine(bs).count_orbits()
    def _bfs_count(self, bs): return bs.orbit_count()

    def test_no_symmetry_each_bin_own_orbit(self):
        bs = BinSpace()
        bs.add_coverpoint(Coverpoint.from_names("cp", ["A","B","C"]))
        assert self._sym_count(bs) == 3  # trivial group
        assert self._sym_count(bs) == self._bfs_count(bs)

    def test_partial_swap_2cp_2bin(self):
        # 2 coverpoints, swap(0,1), 2 bins each
        # C(4,2)=6... wait: Z2 on 2^2=4 bins:
        # identity fixes all 4; swap fixes where cp0=cp1 → 2 fixed → (4+2)/2=3
        bs = make_partial_swap(2, 0, 1, 2)
        assert self._sym_count(bs) == 3
        assert self._sym_count(bs) == self._bfs_count(bs)

    def test_partial_swap_4cp_2bin(self):
        # 4 coverpoints, swap only positions 1 and 2, 2 bins each
        # Expected: 12  (verified by BFS in test_core.py)
        bs = make_partial_swap(4, 1, 2, 2)
        assert self._sym_count(bs) == 12
        assert self._sym_count(bs) == self._bfs_count(bs)

    def test_burnside_matches_bfs_s3_partial(self):
        # Z2: only swap(0,1) on 3 coverpoints of 3 bins
        bs = BinSpace()
        for i in range(3):
            bs.add_coverpoint(Coverpoint.from_names(f"cp{i}", ["A","B","C"]))
        bs.add_symmetry([1, 0, 2])   # swap 0↔1 only → Z2
        assert self._sym_count(bs) == self._bfs_count(bs)


# ═══════════════════════════════════════════════════════════════════════════════
# Canonical form
# ═══════════════════════════════════════════════════════════════════════════════

class TestCanonical:

    def test_sorted_tuple_is_canonical_for_sn(self):
        bs = make_direct_sn(3, 4)
        eng = SymbolicOrbitEngine(bs)
        assert eng.canonical((2, 0, 1)) == (0, 1, 2)
        assert eng.canonical((3, 3, 0)) == (0, 3, 3)
        assert eng.canonical((1, 1, 1)) == (1, 1, 1)

    def test_canonical_already_sorted(self):
        bs = make_direct_sn(4, 4)
        eng = SymbolicOrbitEngine(bs)
        bt = (0, 1, 2, 3)
        assert eng.canonical(bt) == bt

    def test_canonical_idempotent(self):
        bs = make_direct_sn(4, 4)
        eng = SymbolicOrbitEngine(bs)
        bt = (3, 1, 0, 2)
        c1 = eng.canonical(bt)
        c2 = eng.canonical(c1)
        assert c1 == c2

    def test_canonical_block_sn(self):
        # 2 instances, 2 signals (k=2 each) → blocks = (v0, v1)
        bs = make_block_sn(2, [2, 2])
        eng = SymbolicOrbitEngine(bs)
        # Block 0 = (1,0), Block 1 = (0,1) → sorted blocks: (0,1) then (1,0)
        bt = (1, 0, 0, 1)   # inst0.sig0=1, inst0.sig1=0, inst1.sig0=0, inst1.sig1=1
        c = eng.canonical(bt)
        assert c == (0, 1, 1, 0)   # sorted: (0,1) before (1,0)

    def test_canonical_same_for_orbit_members(self):
        bs = make_direct_sn(3, 3)
        eng = SymbolicOrbitEngine(bs)
        bt = (2, 0, 1)
        for member in eng.orbit_of(bt):
            assert eng.canonical(member) == eng.canonical(bt)

    def test_canonical_burnside_lex_min(self):
        # For partial symmetry (non-Sₙ), canonical = lex-min
        bs = make_partial_swap(3, 0, 1, 2)
        eng = SymbolicOrbitEngine(bs)
        # Orbit of (1,0,0): swap gives (0,1,0) — lex-min is (0,1,0)
        bt = (1, 0, 0)
        c = eng.canonical(bt)
        assert c == min(eng.orbit_of(bt))


# ═══════════════════════════════════════════════════════════════════════════════
# orbit_of
# ═══════════════════════════════════════════════════════════════════════════════

class TestOrbitOf:

    def test_orbit_all_same_is_singleton(self):
        bs = make_direct_sn(3, 4)
        eng = SymbolicOrbitEngine(bs)
        # (2,2,2) — all same → orbit size 1
        assert eng.orbit_of((2, 2, 2)) == frozenset({(2, 2, 2)})

    def test_orbit_all_distinct_is_n_factorial(self):
        bs = make_direct_sn(3, 4)
        eng = SymbolicOrbitEngine(bs)
        orbit = eng.orbit_of((0, 1, 2))
        assert len(orbit) == math.factorial(3)   # 6

    def test_orbit_two_same_one_diff(self):
        bs = make_direct_sn(3, 4)
        eng = SymbolicOrbitEngine(bs)
        orbit = eng.orbit_of((0, 0, 1))
        # Multinomial: 3!/(2!1!) = 3
        assert len(orbit) == 3
        assert (0, 0, 1) in orbit
        assert (0, 1, 0) in orbit
        assert (1, 0, 0) in orbit

    def test_orbit_of_matches_bfs_orbit(self):
        bs = make_direct_sn(3, 4)
        bfs_orbits = {o.representative: frozenset(o.members)
                      for o in bs.compute_orbits()}
        eng = SymbolicOrbitEngine(bs)
        for rep, members in bfs_orbits.items():
            assert eng.orbit_of(rep) == members

    def test_orbit_of_block_sn(self):
        # 2 instances, 2 signals: swap means permute blocks
        bs = make_block_sn(2, [2, 2])
        eng = SymbolicOrbitEngine(bs)
        # (1,0, 0,1) → blocks (1,0) and (0,1) — swap gives (0,1, 1,0)
        orbit = eng.orbit_of((1, 0, 0, 1))
        assert (0, 1, 1, 0) in orbit
        assert (1, 0, 0, 1) in orbit


# ═══════════════════════════════════════════════════════════════════════════════
# is_same_orbit
# ═══════════════════════════════════════════════════════════════════════════════

class TestIsSameOrbit:

    def test_permutation_of_same_values_is_same_orbit(self):
        bs = make_direct_sn(3, 4)
        eng = SymbolicOrbitEngine(bs)
        assert eng.is_same_orbit((0, 1, 2), (2, 0, 1))
        assert eng.is_same_orbit((0, 0, 1), (1, 0, 0))

    def test_different_multisets_different_orbits(self):
        bs = make_direct_sn(3, 4)
        eng = SymbolicOrbitEngine(bs)
        assert not eng.is_same_orbit((0, 0, 1), (0, 1, 1))
        assert not eng.is_same_orbit((0, 1, 2), (0, 1, 3))

    def test_same_element_same_orbit(self):
        bs = make_direct_sn(4, 4)
        eng = SymbolicOrbitEngine(bs)
        bt = (3, 1, 2, 0)
        assert eng.is_same_orbit(bt, bt)


# ═══════════════════════════════════════════════════════════════════════════════
# Representative enumeration
# ═══════════════════════════════════════════════════════════════════════════════

class TestRepresentatives:

    def test_count_matches_polya(self):
        for n, k in [(2, 3), (3, 4), (4, 4), (5, 3)]:
            bs = make_direct_sn(n, k)
            eng = SymbolicOrbitEngine(bs)
            reps = eng.representatives()
            assert len(reps) == eng.count_orbits(), f"Failed for n={n}, k={k}"

    def test_reps_are_sorted_non_decreasing(self):
        bs = make_direct_sn(4, 4)
        eng = SymbolicOrbitEngine(bs)
        for r in eng.representatives():
            assert list(r) == sorted(r)

    def test_reps_unique(self):
        bs = make_direct_sn(3, 4)
        eng = SymbolicOrbitEngine(bs)
        reps = eng.representatives()
        assert len(reps) == len(set(reps))

    def test_reps_are_canonical(self):
        bs = make_direct_sn(3, 4)
        eng = SymbolicOrbitEngine(bs)
        for r in eng.representatives():
            assert eng.canonical(r) == r

    def test_reps_cover_all_orbits(self):
        """Every BFS orbit's representative must appear in symbolic reps."""
        bs = make_direct_sn(3, 4)
        eng = SymbolicOrbitEngine(bs)
        sym_reps = set(eng.representatives())
        for bfs_orbit in bs.compute_orbits():
            c = eng.canonical(bfs_orbit.representative)
            assert c in sym_reps

    def test_block_sn_rep_count(self):
        # 4 instances, K=8 → C(11,4) = 330
        bs = make_block_sn(4, [4, 2])
        eng = SymbolicOrbitEngine(bs)
        reps = eng.representatives()
        assert len(reps) == math.comb(4+8-1, 4)

    def test_block_s8_k8_reps_count_no_oom(self):
        # 8 instances, K=8 → C(15,8) = 6435 reps
        # Previously: BFS on 16M bins OOM'd
        bs = make_block_sn(8, [4, 2])
        eng = SymbolicOrbitEngine(bs)
        reps = eng.representatives()
        assert len(reps) == 6435


# ═══════════════════════════════════════════════════════════════════════════════
# Compression metrics
# ═══════════════════════════════════════════════════════════════════════════════

class TestCompressionMetrics:

    def test_compression_ratio_matches_bfs(self):
        bs = make_direct_sn(3, 4)
        eng = SymbolicOrbitEngine(bs)
        assert abs(eng.compression_ratio() - bs.compression_ratio()) < 0.01

    def test_s8_compression_ratio(self):
        # 65536 / 165 ≈ 397.2×
        bs = make_direct_sn(8, 4)
        eng = SymbolicOrbitEngine(bs)
        assert abs(eng.compression_ratio() - 65536/165) < 0.1

    def test_block_s8_k8_compression_ratio(self):
        # (8^8) / 6435 ≈ 2607×
        bs = make_block_sn(8, [4, 2])
        eng = SymbolicOrbitEngine(bs)
        expected_total = 8**8
        expected_ratio = expected_total / 6435
        assert abs(eng.compression_ratio() - expected_ratio) < 1.0

    def test_trivial_group_ratio_is_1(self):
        bs = BinSpace()
        bs.add_coverpoint(Coverpoint.from_names("cp", ["A","B"]))
        eng = SymbolicOrbitEngine(bs)
        assert eng.compression_ratio() == 1.0


# ═══════════════════════════════════════════════════════════════════════════════
# SymbolicExpansionEngine
# ═══════════════════════════════════════════════════════════════════════════════

class TestSymbolicExpansionEngine:

    def _bs_3lane(self):
        return make_direct_sn(3, 4)

    def _label_hit(self, bs, bt):
        """Create a single-hit CoverageResult from a BinTuple."""
        label = bs.bin_label(bt)
        return CoverageResult.from_hits([(label, 1)])

    # ── Full coverage ─────────────────────────────────────────────────────────

    def test_full_coverage_is_complete(self):
        bs = self._bs_3lane()
        eng = SymbolicExpansionEngine(bs)
        sym_eng = SymbolicOrbitEngine(bs)
        all_reps = sym_eng.representatives()
        hits = [(bs.bin_label(r), 1) for r in all_reps]
        result = CoverageResult.from_hits(hits)
        er = eng.expand(result)
        assert er.is_complete()
        assert er.n_orbits_hit() == er.n_orbits()
        assert er.class_coverage_pct() == 100.0

    def test_zero_coverage(self):
        bs = self._bs_3lane()
        eng = SymbolicExpansionEngine(bs)
        er = eng.expand(CoverageResult())
        assert not er.is_complete()
        assert er.n_orbits_hit() == 0
        assert er.class_coverage_pct() == 0.0

    def test_partial_coverage_orbit_count(self):
        bs = self._bs_3lane()
        sym_eng = SymbolicOrbitEngine(bs)
        reps = sym_eng.representatives()[:7]
        hits = [(bs.bin_label(r), 1) for r in reps]
        result = CoverageResult.from_hits(hits)
        er = SymbolicExpansionEngine(bs).expand(result)
        assert er.n_orbits_hit() == 7
        assert not er.is_complete()

    # ── Non-rep hit ───────────────────────────────────────────────────────────

    def test_non_rep_hit_covers_orbit(self):
        bs = self._bs_3lane()
        eng = SymbolicExpansionEngine(bs)
        # (2, 0, 1) is a non-sorted bin → canonical is (0, 1, 2)
        non_rep_label = bs.bin_label((2, 0, 1))
        result = CoverageResult.from_hits([(non_rep_label, 1)])
        er = eng.expand(result)
        assert er.n_orbits_hit() == 1
        # The canonical (0,1,2) should be covered
        assert er.is_covered(bs.bin_label((0, 1, 2)))
        assert er.is_covered(bs.bin_label((1, 0, 2)))

    # ── Unresolved labels ─────────────────────────────────────────────────────

    def test_unresolved_wrong_label(self):
        bs = self._bs_3lane()
        result = CoverageResult.from_hits([
            (("b0","b1","b2"), 1),
            (("BOGUS","b0","b1"), 1),
        ])
        er = SymbolicExpansionEngine(bs).expand(result)
        assert len(er.unresolved_labels) == 1
        assert ("BOGUS","b0","b1") in er.unresolved_labels

    def test_unresolved_wrong_arity(self):
        bs = self._bs_3lane()
        result = CoverageResult.from_hits([(("b0","b1","b2","b3"), 1)])
        er = SymbolicExpansionEngine(bs).expand(result)
        assert len(er.unresolved_labels) == 1

    # ── is_covered ───────────────────────────────────────────────────────────

    def test_is_covered_by_orbit_member(self):
        bs = self._bs_3lane()
        sym_eng = SymbolicOrbitEngine(bs)
        rep = sym_eng.representatives()[5]
        rep_label = bs.bin_label(rep)
        result = CoverageResult.from_hits([(rep_label, 1)])
        er = SymbolicExpansionEngine(bs).expand(result)
        # Every orbit member should be covered
        for member in sym_eng.orbit_of(rep):
            assert er.is_covered(bs.bin_label(member))

    # ── merge_and_expand ─────────────────────────────────────────────────────

    def test_merge_two_disjoint_runs(self):
        bs = self._bs_3lane()
        sym_eng = SymbolicOrbitEngine(bs)
        all_reps = sym_eng.representatives()
        half = len(all_reps) // 2
        run1 = CoverageResult.from_hits(
            [(bs.bin_label(r), 1) for r in all_reps[:half]])
        run2 = CoverageResult.from_hits(
            [(bs.bin_label(r), 1) for r in all_reps[half:]])
        er = SymbolicExpansionEngine(bs).merge_and_expand([run1, run2])
        assert er.is_complete()

    def test_merge_empty_is_zero_coverage(self):
        bs = self._bs_3lane()
        er = SymbolicExpansionEngine(bs).merge_and_expand([])
        assert er.n_orbits_hit() == 0

    # ── missed_representatives ────────────────────────────────────────────────

    def test_missed_reps_count(self):
        bs = self._bs_3lane()
        sym_eng = SymbolicOrbitEngine(bs)
        reps = sym_eng.representatives()
        n_hit = 5
        result = CoverageResult.from_hits(
            [(bs.bin_label(r), 1) for r in reps[:n_hit]])
        er = SymbolicExpansionEngine(bs).expand(result)
        missed = er.missed_representatives()
        assert len(missed) == er.n_orbits() - n_hit

    # ── n_bins_covered ────────────────────────────────────────────────────────

    def test_n_bins_covered_formula(self):
        """Covered bins = sum of orbit sizes for covered orbits."""
        bs = self._bs_3lane()
        sym_eng = SymbolicOrbitEngine(bs)
        # Hit the (0,0,0) orbit — size 1, and the (0,1,2) orbit — size 6
        result = CoverageResult.from_hits([
            (bs.bin_label((0, 0, 0)), 1),
            (bs.bin_label((0, 1, 2)), 1),
        ])
        er = SymbolicExpansionEngine(bs).expand(result)
        assert er.n_bins_covered() == 1 + 6   # 7

    # ── report / to_dict ─────────────────────────────────────────────────────

    def test_report_contains_key_fields(self):
        bs = self._bs_3lane()
        sym_eng = SymbolicOrbitEngine(bs)
        reps = sym_eng.representatives()[:10]
        result = CoverageResult.from_hits(
            [(bs.bin_label(r), 1) for r in reps],
            run_id="sym_test"
        )
        er = SymbolicExpansionEngine(bs).expand(result)
        report = er.report()
        assert "Dabih" in report
        assert "sym_test" in report
        assert "polya" in report
        assert "50.00%" in report   # 10/20

    def test_report_complete_flag(self):
        bs = self._bs_3lane()
        sym_eng = SymbolicOrbitEngine(bs)
        all_reps = sym_eng.representatives()
        result = CoverageResult.from_hits([(bs.bin_label(r), 1) for r in all_reps])
        er = SymbolicExpansionEngine(bs).expand(result)
        assert er.is_complete()
        assert "COMPLETE" in er.report()

    def test_to_dict_structure(self):
        bs = self._bs_3lane()
        sym_eng = SymbolicOrbitEngine(bs)
        result = CoverageResult.from_hits(
            [(bs.bin_label(sym_eng.representatives()[0]), 1)],
            run_id="dict_test"
        )
        er = SymbolicExpansionEngine(bs).expand(result)
        d = er.to_dict()
        assert "method" in d
        assert d["method"] == "polya"
        assert "orbits_total" in d
        assert "holes" in d
        assert d["run_id"] == "dict_test"


# ═══════════════════════════════════════════════════════════════════════════════
# Integration: BFS vs Symbolic agreement
# ═══════════════════════════════════════════════════════════════════════════════

class TestBFSvsSymbolicAgreement:
    """For all small spaces, BFS orbit count must equal symbolic orbit count."""

    @pytest.mark.parametrize("n,k", [
        (2,2),(2,3),(2,4),(3,2),(3,3),(3,4),(4,2),(4,3),(4,4),(5,3)
    ])
    def test_direct_sn_count_agrees(self, n, k):
        bs = make_direct_sn(n, k)
        bfs = bs.orbit_count()
        sym = SymbolicOrbitEngine(bs).count_orbits()
        assert bfs == sym, f"Mismatch n={n}, k={k}: BFS={bfs}, sym={sym}"

    @pytest.mark.parametrize("n,ks", [
        (2,[2,2]),(2,[4,2]),(3,[3,2]),(3,[4,2]),(4,[2,2]),(4,[3,2])
    ])
    def test_block_sn_count_agrees(self, n, ks):
        bs = make_block_sn(n, ks)
        bfs = bs.orbit_count()
        sym = SymbolicOrbitEngine(bs).count_orbits()
        assert bfs == sym, f"Mismatch n={n}, ks={ks}: BFS={bfs}, sym={sym}"

    def test_burnside_partial_agrees(self):
        for n_total, i, j, k in [(3,0,1,2),(4,1,2,3),(4,0,3,2)]:
            bs = make_partial_swap(n_total, i, j, k)
            bfs = bs.orbit_count()
            sym = SymbolicOrbitEngine(bs).count_orbits()
            assert bfs == sym


# ═══════════════════════════════════════════════════════════════════════════════
# Integration: Bridge hint + Symbolic end-to-end
# ═══════════════════════════════════════════════════════════════════════════════

class TestBridgeSymbolicIntegration:

    def test_bridge_sets_symbolic_hint(self):
        from dabih.rtl import RtlExtractor, BinSpaceBuilder
        ext = (RtlExtractor()
               .add_file(fx("serdes_top.sv"))
               .add_param("N_LANES", 4))
        arrays = [a for a in ext.extract() if a.module_type == "rx_lane"]
        results = (BinSpaceBuilder(arrays)
                   .cover("state", ["IDLE","ACTIVE","STALL","ERROR"])
                   .build(ext.param_overrides))
        bs = results[0].bin_space
        assert hasattr(bs, "_symbolic_hint")
        hint = bs._symbolic_hint
        assert hint["type"] == "block_symmetric"
        assert hint["n_blocks"] == 4
        assert hint["is_full_sn"] is True

    def test_bridge_hint_selects_polya(self):
        from dabih.rtl import RtlExtractor, BinSpaceBuilder
        ext = (RtlExtractor()
               .add_file(fx("serdes_top.sv"))
               .add_param("N_LANES", 4))
        arrays = [a for a in ext.extract() if a.module_type == "rx_lane"]
        results = (BinSpaceBuilder(arrays)
                   .cover("state", ["IDLE","ACTIVE","STALL","ERROR"])
                   .build(ext.param_overrides))
        bs = results[0].bin_space
        eng = SymbolicOrbitEngine(bs)
        assert eng.method_used() == "polya"
        assert eng.count_orbits() == math.comb(4+4-1, 4)  # 35

    def test_8lane_2signal_end_to_end(self):
        """
        Full pipeline for previously infeasible space:
        8 lanes × (4-bin state + 2-bin ready) → 16,777,216 bins → 6,435 orbits.
        """
        from dabih.rtl import RtlExtractor, BinSpaceBuilder
        ext = (RtlExtractor()
               .add_file(fx("serdes_top.sv"))
               .add_param("N_LANES", 8))
        arrays = [a for a in ext.extract() if a.module_type == "rx_lane"]
        results = (BinSpaceBuilder(arrays)
                   .cover("state", ["IDLE","ACTIVE","STALL","ERROR"])
                   .cover("ready", ["LO","HI"])
                   .build(ext.param_overrides))
        bs = results[0].bin_space

        sym_eng = SymbolicOrbitEngine(bs)
        assert sym_eng.count_orbits() == 6435
        assert sym_eng.method_used() == "polya"

        # Expansion: hit half the representatives
        reps = sym_eng.representatives()
        half = len(reps) // 2
        hits = [(bs.bin_label(r), 1) for r in reps[:half]]
        result = CoverageResult.from_hits(hits, run_id="8lane_test")

        exp_eng = SymbolicExpansionEngine(bs)
        er = exp_eng.expand(result)

        assert er.n_orbits_hit() == half
        assert not er.is_complete()
        assert abs(er.class_coverage_pct() - 50.0) < 0.1
        assert len(er.missed_representatives()) == 6435 - half

    def test_incremental_regression_closes_8lane(self):
        """Three simulation runs close 6,435 orbits across 8 lanes."""
        from dabih.rtl import RtlExtractor, BinSpaceBuilder
        ext = (RtlExtractor()
               .add_file(fx("serdes_top.sv"))
               .add_param("N_LANES", 8))
        arrays = [a for a in ext.extract() if a.module_type == "rx_lane"]
        results = (BinSpaceBuilder(arrays)
                   .cover("state", ["IDLE","ACTIVE","STALL","ERROR"])
                   .cover("ready", ["LO","HI"])
                   .build(ext.param_overrides))
        bs = results[0].bin_space

        sym_eng = SymbolicOrbitEngine(bs)
        reps = sym_eng.representatives()  # 6435 reps
        n = len(reps)

        run1 = CoverageResult.from_hits([(bs.bin_label(r), 1) for r in reps[:n//3]])
        run2 = CoverageResult.from_hits([(bs.bin_label(r), 1) for r in reps[n//3:2*n//3]])
        run3 = CoverageResult.from_hits([(bs.bin_label(r), 1) for r in reps[2*n//3:]])

        er = SymbolicExpansionEngine(bs).merge_and_expand([run1, run2, run3])
        assert er.is_complete()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
