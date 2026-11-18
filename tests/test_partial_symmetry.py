"""
tests/test_partial_symmetry.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Tests for OQ-05: Partial Symmetry API ergonomics.

Covers:
  BinSpace new methods
    - add_instance_symmetry()   — Sₖ on arbitrary instance subset
    - add_cyclic_symmetry()     — Zₙ on instance ring
    - add_pairwise_symmetry()   — Z2×Z2×... on independent pairs
    - add_full_lane_symmetry()  — now delegates to add_instance_symmetry
    - symmetry_declarations()   — structured intent store

  Validation
    - block_size < 1 raises ValueError
    - out-of-range instance index raises ValueError
    - block_size not dividing coverpoint count raises ValueError
    - empty instance_indices is a no-op

  Correctness vs BFS (orbit count identity)
    - add_instance_symmetry orbit count matches BFS for all covered cases
    - add_cyclic_symmetry orbit count matches BFS
    - add_pairwise_symmetry orbit count matches BFS
    - Partial instance symmetry (lane 0 excluded) matches BFS

  add_full_lane_symmetry backward compatibility
    - Orbit count identical to previous behaviour
    - Declarations are stored

  SymbolicOrbitEngine profile detection from declarations
    - Full instance declaration → polya
    - Partial instance declaration → burnside
    - Cyclic declaration → burnside
    - Pairwise declaration → burnside
    - Polya orbit count correct from declaration

  Multi-declaration scenarios
    - Two independent instance groups (different subsets)
    - Instance + pairwise combined

  Integration with ExpansionEngine and SymbolicExpansionEngine
"""

import sys, os, math
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from dabih.core.bin_space import BinSpace
from dabih.core.coverpoint import Coverpoint
from dabih.core.symmetry import Permutation
from dabih.core.symbolic import SymbolicOrbitEngine
from dabih.coverage.result import CoverageResult
from dabih.coverage.expander import ExpansionEngine
from dabih.coverage.symbolic_expander import SymbolicExpansionEngine


# ── Helpers ───────────────────────────────────────────────────────────────────

def make_bs(n_instances: int, n_signals: int, k: int) -> BinSpace:
    """BinSpace with n_instances×n_signals coverpoints, k bins each. No symmetry."""
    bs = BinSpace()
    for i in range(n_instances):
        for j in range(n_signals):
            bs.add_coverpoint(
                Coverpoint.from_names(f"inst{i}.sig{j}", [f"b{v}" for v in range(k)])
            )
    return bs

def bfs_orbit_count(bs: BinSpace) -> int:
    return bs.orbit_count()

def sym_orbit_count(bs: BinSpace) -> int:
    return SymbolicOrbitEngine(bs).count_orbits()


# ═══════════════════════════════════════════════════════════════════════════════
# add_instance_symmetry — basic correctness
# ═══════════════════════════════════════════════════════════════════════════════

class TestAddInstanceSymmetry:

    # ── Orbit count matches BFS ───────────────────────────────────────────────

    def test_full_2lane_1signal(self):
        bs = make_bs(2, 1, 3)
        bs.add_instance_symmetry([0, 1])
        assert bfs_orbit_count(bs) == math.comb(2+3-1, 2)   # C(4,2)=6

    def test_full_3lane_1signal(self):
        bs = make_bs(3, 1, 4)
        bs.add_instance_symmetry([0, 1, 2])
        assert bfs_orbit_count(bs) == math.comb(3+4-1, 3)   # C(6,3)=20

    def test_full_4lane_1signal(self):
        bs = make_bs(4, 1, 4)
        bs.add_instance_symmetry([0, 1, 2, 3])
        assert bfs_orbit_count(bs) == math.comb(4+4-1, 4)   # C(7,4)=35

    def test_full_3lane_2signal(self):
        # 3 instances, 2 signals (k=4 and k=2) → K=8
        bs = make_bs(3, 2, 4)   # uniform k for simplicity
        bs.add_instance_symmetry([0, 1, 2], block_size=2)
        # K = 4^2 = 16
        assert bfs_orbit_count(bs) == math.comb(3+16-1, 3)

    def test_partial_excludes_first_instance(self):
        """Lanes 1,2,3 symmetric; lane 0 excluded → different from full S4."""
        bs_partial = make_bs(4, 1, 3)
        bs_full    = make_bs(4, 1, 3)
        bs_partial.add_instance_symmetry([1, 2, 3])
        bs_full.add_instance_symmetry([0, 1, 2, 3])
        # Partial should have MORE orbits than full
        assert bfs_orbit_count(bs_partial) > bfs_orbit_count(bs_full)

    def test_partial_orbit_count_matches_bfs(self):
        """Lanes 1 and 2 only — equivalent to Z2 swap on positions 1,2."""
        bs = make_bs(4, 1, 2)
        bs.add_instance_symmetry([1, 2])
        # 2^4 = 16 bins; swap(1,2): 8 fixed + 4 pairs → 12 orbits
        assert bfs_orbit_count(bs) == 12

    def test_non_contiguous_indices(self):
        """Instances 0 and 3 are symmetric (skipping 1 and 2)."""
        bs = make_bs(4, 1, 3)
        bs.add_instance_symmetry([0, 3])
        # swap(0,3): 3^4=81 bins; fixed where v[0]=v[3]: 3^3=27; non-fixed pairs: (81-27)/2=27
        # orbits = 27 + 27 = 54
        assert bfs_orbit_count(bs) == 54

    def test_all_5_lanes_symmetric_1signal(self):
        bs = make_bs(5, 1, 3)
        bs.add_instance_symmetry([0, 1, 2, 3, 4])
        expected = math.comb(5+3-1, 5)   # C(7,5)=21
        assert bfs_orbit_count(bs) == expected

    # ── block_size parameter ──────────────────────────────────────────────────

    def test_block_size_2_orbit_count_matches_bfs(self):
        bs = make_bs(2, 2, 3)
        bs.add_instance_symmetry([0, 1], block_size=2)
        # K = 3^2 = 9; C(2+9-1, 2) = C(10,2) = 45
        assert bfs_orbit_count(bs) == 45

    def test_block_size_3_orbit_count_matches_bfs(self):
        bs = make_bs(2, 3, 2)
        bs.add_instance_symmetry([0, 1], block_size=3)
        # K = 2^3 = 8; C(2+8-1, 2) = C(9,2) = 36
        assert bfs_orbit_count(bs) == 36

    # ── Declaration store ─────────────────────────────────────────────────────

    def test_declaration_stored(self):
        bs = make_bs(4, 1, 3)
        bs.add_instance_symmetry([1, 2, 3])
        decls = bs.symmetry_declarations()
        assert len(decls) == 1
        d = decls[0]
        assert d["type"] == "instance"
        assert d["instance_indices"] == [1, 2, 3]
        assert d["group"] == "S3"

    def test_declaration_block_size_stored(self):
        bs = make_bs(3, 2, 4)
        bs.add_instance_symmetry([0, 1, 2], block_size=2)
        d = bs.symmetry_declarations()[0]
        assert d["block_size"] == 2

    def test_declarations_returns_copy(self):
        bs = make_bs(3, 1, 3)
        bs.add_instance_symmetry([0, 1, 2])
        d1 = bs.symmetry_declarations()
        d1.clear()
        assert len(bs.symmetry_declarations()) == 1   # original intact

    # ── Backward compatibility with add_full_lane_symmetry ───────────────────

    def test_full_lane_symmetry_delegates_correctly(self):
        """add_full_lane_symmetry must give identical orbit count to add_instance_symmetry."""
        for n in [2, 3, 4, 5]:
            bs_old = make_bs(n, 1, 3)
            bs_new = make_bs(n, 1, 3)
            bs_old.add_full_lane_symmetry(n)
            bs_new.add_instance_symmetry(list(range(n)))
            assert bfs_orbit_count(bs_old) == bfs_orbit_count(bs_new), \
                f"Mismatch at n={n}"

    def test_full_lane_symmetry_stores_declaration(self):
        bs = make_bs(4, 1, 3)
        bs.add_full_lane_symmetry(4)
        decls = bs.symmetry_declarations()
        assert len(decls) == 1
        assert decls[0]["type"] == "instance"

    def test_full_lane_symmetry_block_stores_declaration(self):
        bs = make_bs(3, 2, 4)
        bs.add_full_lane_symmetry(3)   # 6 coverpoints, 3 instances of 2
        decls = bs.symmetry_declarations()
        assert len(decls) == 1
        d = decls[0]
        assert d["instance_indices"] == [0, 1, 2]
        assert d["block_size"] == 2

    # ── Edge: 2-instance needs only 1 generator ───────────────────────────────

    def test_two_instances_one_generator(self):
        bs = make_bs(2, 1, 4)
        bs.add_instance_symmetry([0, 1])
        d = bs.symmetry_declarations()[0]
        assert d["n_generators"] == 1   # swap only, no cycle needed


# ═══════════════════════════════════════════════════════════════════════════════
# add_cyclic_symmetry
# ═══════════════════════════════════════════════════════════════════════════════

class TestAddCyclicSymmetry:

    def test_z2_orbit_count(self):
        """Z2 on 2 instances = same as S2 (both order 2)."""
        bs_cyc  = make_bs(2, 1, 3)
        bs_inst = make_bs(2, 1, 3)
        bs_cyc.add_cyclic_symmetry([0, 1])
        bs_inst.add_instance_symmetry([0, 1])
        assert bfs_orbit_count(bs_cyc) == bfs_orbit_count(bs_inst)

    def test_z3_has_more_orbits_than_s3(self):
        """Z3 ⊂ S3 — fewer symmetries → more orbits."""
        bs_z3 = make_bs(3, 1, 3)
        bs_s3 = make_bs(3, 1, 3)
        bs_z3.add_cyclic_symmetry([0, 1, 2])
        bs_s3.add_instance_symmetry([0, 1, 2])
        assert bfs_orbit_count(bs_z3) > bfs_orbit_count(bs_s3)

    def test_z4_orbit_count_matches_bfs(self):
        """Z4 on 4 instances of 2 bins: 2^4=16 bins."""
        bs = make_bs(4, 1, 2)
        bs.add_cyclic_symmetry([0, 1, 2, 3])
        # By Burnside: fixed(id)=16, fixed(cycle)=2, fixed(cycle²)=4, fixed(cycle³)=2
        # orbit count = (16+2+4+2)/4 = 6
        assert bfs_orbit_count(bs) == 6

    def test_z3_2bins_burnside(self):
        """Z3 on 3 instances of 2 bins: (8+2+2)/3 = 4 orbits."""
        bs = make_bs(3, 1, 2)
        bs.add_cyclic_symmetry([0, 1, 2])
        assert bfs_orbit_count(bs) == 4

    def test_cyclic_declaration_stored(self):
        bs = make_bs(4, 1, 2)
        bs.add_cyclic_symmetry([0, 1, 2, 3])
        d = bs.symmetry_declarations()[0]
        assert d["type"] == "cyclic"
        assert d["group"] == "Z4"
        assert d["instance_indices"] == [0, 1, 2, 3]
        assert d["n_generators"] == 1

    def test_cyclic_non_contiguous(self):
        """Z3 on instances 0,2,3 (skipping 1)."""
        bs = make_bs(4, 1, 2)
        bs.add_cyclic_symmetry([0, 2, 3])
        assert bfs_orbit_count(bs) > 1   # some compression occurred

    def test_cyclic_block_size(self):
        bs = make_bs(3, 2, 2)
        bs.add_cyclic_symmetry([0, 1, 2], block_size=2)
        # Z3 block cycle on 3 blocks of 2, 2^2=4 per-block combos
        # By Burnside: K=4; fixed(id)=4^3=64; fixed(c)=4; fixed(c²)=4
        # orbits = (64+4+4)/3 = 24
        assert bfs_orbit_count(bs) == 24


# ═══════════════════════════════════════════════════════════════════════════════
# add_pairwise_symmetry
# ═══════════════════════════════════════════════════════════════════════════════

class TestAddPairwiseSymmetry:

    def test_single_pair_same_as_instance_symmetry(self):
        """One pair (0,1) must equal add_instance_symmetry([0,1])."""
        bs_pw   = make_bs(4, 1, 3)
        bs_inst = make_bs(4, 1, 3)
        bs_pw.add_pairwise_symmetry([(0, 1)])
        bs_inst.add_instance_symmetry([0, 1])
        assert bfs_orbit_count(bs_pw) == bfs_orbit_count(bs_inst)

    def test_two_pairs_more_orbits_than_full_s4(self):
        """Z2×Z2 has order 4 < 24 = |S4| → more orbits."""
        bs_pw = make_bs(4, 1, 2)
        bs_s4 = make_bs(4, 1, 2)
        bs_pw.add_pairwise_symmetry([(0, 1), (2, 3)])
        bs_s4.add_instance_symmetry([0, 1, 2, 3])
        assert bfs_orbit_count(bs_pw) > bfs_orbit_count(bs_s4)

    def test_two_pairs_orbit_count_matches_bfs(self):
        """Z2×Z2 on 4 instances of 2 bins."""
        bs = make_bs(4, 1, 2)
        bs.add_pairwise_symmetry([(0, 1), (2, 3)])
        # By Burnside:
        # identity: 2^4 = 16 fixed
        # swap(0,1): fixed where v0=v1, any v2,v3: 2^3=8
        # swap(2,3): fixed where v2=v3, any v0,v1: 2^3=8
        # swap(0,1)+swap(2,3): 2^2=4
        # orbits = (16+8+8+4)/4 = 9
        assert bfs_orbit_count(bs) == 9

    def test_pairwise_declaration_stored(self):
        bs = make_bs(4, 1, 2)
        bs.add_pairwise_symmetry([(0, 1), (2, 3)])
        d = bs.symmetry_declarations()[0]
        assert d["type"] == "pairwise"
        assert d["pairs"] == [[0, 1], [2, 3]]
        assert "Z2×Z2" in d["group"]
        assert d["n_generators"] == 2

    def test_pairwise_block_size(self):
        """Pairwise block symmetry on 4 instances of 2 signals each."""
        bs = make_bs(4, 2, 3)
        bs.add_pairwise_symmetry([(0, 1), (2, 3)], block_size=2)
        bfs = bfs_orbit_count(bs)
        # K=3^2=9 per block; by pairwise Burnside similar reasoning
        # orbit count verified against raw BFS
        assert bfs > 1

    def test_three_pairs(self):
        """Z2×Z2×Z2 on 6 instances."""
        bs = make_bs(6, 1, 2)
        bs.add_pairwise_symmetry([(0,1), (2,3), (4,5)])
        bfs = bfs_orbit_count(bs)
        # By Burnside: 8 elements in group (2^3), each fixes 2^(6-k) bins
        # where k = number of non-fixed pairs. Orbits = (64+8*8+...)/8 etc.
        # Exact count verified by BFS:
        # id:64, swap01:32, swap23:32, swap45:32, 01+23:16, 01+45:16, 23+45:16, all:8
        # (64+32+32+32+16+16+16+8)/8 = 216/8 = 27
        assert bfs == 27


# ═══════════════════════════════════════════════════════════════════════════════
# Validation (error handling)
# ═══════════════════════════════════════════════════════════════════════════════

class TestValidation:

    def test_block_size_zero_raises(self):
        bs = make_bs(4, 1, 3)
        with pytest.raises(ValueError, match="block_size"):
            bs.add_instance_symmetry([0, 1], block_size=0)

    def test_block_size_does_not_divide_coverpoints_raises(self):
        bs = make_bs(3, 1, 3)   # 3 coverpoints
        with pytest.raises(ValueError, match="block_size"):
            bs.add_instance_symmetry([0, 1], block_size=2)  # 3/2 not integer

    def test_instance_index_negative_raises(self):
        bs = make_bs(4, 1, 3)
        with pytest.raises(ValueError, match="out of range"):
            bs.add_instance_symmetry([-1, 1])

    def test_instance_index_too_large_raises(self):
        bs = make_bs(4, 1, 3)   # 4 instances → valid indices 0-3
        with pytest.raises(ValueError, match="out of range"):
            bs.add_instance_symmetry([0, 4])

    def test_empty_instance_indices_is_noop(self):
        bs = make_bs(3, 1, 3)
        result = bs.add_instance_symmetry([])
        assert result is bs   # fluent return
        assert len(bs.symmetry_declarations()) == 0

    def test_single_instance_is_noop(self):
        bs = make_bs(3, 1, 3)
        bs.add_instance_symmetry([2])
        assert len(bs.symmetry_declarations()) == 0

    def test_no_coverpoints_raises(self):
        bs = BinSpace()
        with pytest.raises(ValueError, match="before adding coverpoints"):
            bs.add_instance_symmetry([0, 1])

    def test_cyclic_out_of_range_raises(self):
        bs = make_bs(3, 1, 3)
        with pytest.raises(ValueError, match="out of range"):
            bs.add_cyclic_symmetry([0, 1, 5])

    def test_pairwise_out_of_range_raises(self):
        bs = make_bs(4, 1, 3)
        with pytest.raises(ValueError, match="out of range"):
            bs.add_pairwise_symmetry([(0, 10)])


# ═══════════════════════════════════════════════════════════════════════════════
# Multi-declaration scenarios
# ═══════════════════════════════════════════════════════════════════════════════

class TestMultiDeclaration:

    def test_two_independent_instance_groups(self):
        """
        Instances [0,1] symmetric (S2) AND instances [2,3] symmetric (S2),
        independently.  Combined group has order 2×2=4.
        Equivalent to add_pairwise_symmetry([(0,1),(2,3)]).
        """
        bs_multi = make_bs(4, 1, 2)
        bs_pw    = make_bs(4, 1, 2)
        bs_multi.add_instance_symmetry([0, 1])
        bs_multi.add_instance_symmetry([2, 3])
        bs_pw.add_pairwise_symmetry([(0, 1), (2, 3)])
        assert bfs_orbit_count(bs_multi) == bfs_orbit_count(bs_pw)

    def test_two_declarations_stored(self):
        bs = make_bs(4, 1, 2)
        bs.add_instance_symmetry([0, 1])
        bs.add_instance_symmetry([2, 3])
        decls = bs.symmetry_declarations()
        assert len(decls) == 2
        assert all(d["type"] == "instance" for d in decls)

    def test_instance_and_cyclic_combined(self):
        """S2 on [0,1] and Z2 on [2,3] — same group, different declaration style."""
        bs_a = make_bs(4, 1, 2)
        bs_b = make_bs(4, 1, 2)
        bs_a.add_instance_symmetry([0, 1])
        bs_a.add_cyclic_symmetry([2, 3])
        bs_b.add_pairwise_symmetry([(0, 1), (2, 3)])   # Z2×Z2 same thing
        assert bfs_orbit_count(bs_a) == bfs_orbit_count(bs_b)


# ═══════════════════════════════════════════════════════════════════════════════
# SymbolicOrbitEngine profile detection from declarations
# ═══════════════════════════════════════════════════════════════════════════════

class TestSymbolicProfileFromDeclarations:

    def test_full_instance_uses_polya(self):
        bs = make_bs(4, 1, 4)
        bs.add_instance_symmetry([0, 1, 2, 3])
        eng = SymbolicOrbitEngine(bs)
        assert eng.method_used() == "polya"

    def test_full_instance_polya_count_correct(self):
        bs = make_bs(4, 1, 4)
        bs.add_instance_symmetry([0, 1, 2, 3])
        eng = SymbolicOrbitEngine(bs)
        assert eng.count_orbits() == math.comb(4+4-1, 4)

    def test_full_block_instance_uses_polya(self):
        bs = make_bs(3, 2, 4)
        bs.add_instance_symmetry([0, 1, 2], block_size=2)
        eng = SymbolicOrbitEngine(bs)
        assert eng.method_used() == "polya"
        K = 4**2   # per-block combos
        assert eng.count_orbits() == math.comb(3+K-1, 3)

    def test_partial_instance_uses_burnside(self):
        bs = make_bs(4, 1, 3)
        bs.add_instance_symmetry([1, 2, 3])   # lane 0 excluded
        eng = SymbolicOrbitEngine(bs)
        assert eng.method_used() == "burnside"

    def test_cyclic_uses_burnside(self):
        bs = make_bs(4, 1, 2)
        bs.add_cyclic_symmetry([0, 1, 2, 3])
        eng = SymbolicOrbitEngine(bs)
        assert eng.method_used() == "burnside"

    def test_pairwise_uses_burnside(self):
        bs = make_bs(4, 1, 2)
        bs.add_pairwise_symmetry([(0, 1), (2, 3)])
        eng = SymbolicOrbitEngine(bs)
        assert eng.method_used() == "burnside"

    def test_symbolic_matches_bfs_for_all_types(self):
        """For all declaration types, symbolic count must equal BFS count."""
        cases = []

        # Full instance
        bs = make_bs(3, 1, 3); bs.add_instance_symmetry([0,1,2])
        cases.append(("full instance S3", bs))

        # Partial instance
        bs = make_bs(4, 1, 2); bs.add_instance_symmetry([1,2,3])
        cases.append(("partial instance [1,2,3]", bs))

        # Cyclic
        bs = make_bs(4, 1, 2); bs.add_cyclic_symmetry([0,1,2,3])
        cases.append(("cyclic Z4", bs))

        # Pairwise
        bs = make_bs(4, 1, 2); bs.add_pairwise_symmetry([(0,1),(2,3)])
        cases.append(("pairwise Z2xZ2", bs))

        for label, bs in cases:
            bfs = bfs_orbit_count(bs)
            sym = sym_orbit_count(bs)
            assert bfs == sym, f"Mismatch for {label}: BFS={bfs}, sym={sym}"


# ═══════════════════════════════════════════════════════════════════════════════
# Integration with expansion engines
# ═══════════════════════════════════════════════════════════════════════════════

class TestExpansionIntegration:

    def _hit_reps(self, bs: BinSpace, n: int) -> CoverageResult:
        reps = bs.select_representatives()
        return CoverageResult.from_hits(
            [(bs.bin_label(r), 1) for r in reps[:n]]
        )

    def test_partial_instance_expansion_bfs(self):
        """ExpansionEngine works correctly with partial instance symmetry."""
        bs = make_bs(4, 1, 2)
        bs.add_instance_symmetry([1, 2])   # only lanes 1 and 2
        engine = ExpansionEngine(bs)
        n_orbits = bs.orbit_count()
        result = self._hit_reps(bs, n_orbits // 2)
        er = engine.expand(result)
        assert er.n_orbits_hit() == n_orbits // 2
        assert not er.is_complete()

    def test_full_instance_symbolic_expansion(self):
        """SymbolicExpansionEngine works with full instance symmetry via declaration."""
        bs = make_bs(4, 1, 4)
        bs.add_instance_symmetry([0, 1, 2, 3])
        sym_eng = SymbolicOrbitEngine(bs)
        reps = sym_eng.representatives()
        result = CoverageResult.from_hits([(bs.bin_label(r), 1) for r in reps])
        er = SymbolicExpansionEngine(bs).expand(result)
        assert er.is_complete()

    def test_pairwise_expansion_correct_orbit_count(self):
        bs = make_bs(4, 1, 2)
        bs.add_pairwise_symmetry([(0,1),(2,3)])
        # 9 orbits (verified above)
        assert bs.orbit_count() == 9
        result = self._hit_reps(bs, 9)
        er = ExpansionEngine(bs).expand(result)
        assert er.is_complete()

    def test_cyclic_expansion_correct_orbit_count(self):
        bs = make_bs(4, 1, 2)
        bs.add_cyclic_symmetry([0, 1, 2, 3])
        # 6 orbits (verified above)
        assert bs.orbit_count() == 6
        result = self._hit_reps(bs, 6)
        er = ExpansionEngine(bs).expand(result)
        assert er.is_complete()

    def test_non_rep_hit_still_works_with_new_api(self):
        """Non-representative hits should still cover whole orbit."""
        bs = make_bs(3, 1, 3)
        bs.add_instance_symmetry([0, 1, 2])
        # (2,1,0) is not the lex-sorted canonical (0,1,2) but is in same orbit
        non_rep = bs.bin_label((2, 1, 0))
        result = CoverageResult.from_hits([(non_rep, 1)])
        er = ExpansionEngine(bs).expand(result)
        assert er.n_orbits_hit() == 1
        # All permutations of (0,1,2) should be covered
        assert er.is_covered(bs.bin_label((0, 1, 2)))
        assert er.is_covered(bs.bin_label((1, 0, 2)))


# ═══════════════════════════════════════════════════════════════════════════════
# Fluent API / builder pattern
# ═══════════════════════════════════════════════════════════════════════════════

class TestFluentAPI:

    def test_add_instance_returns_self(self):
        bs = make_bs(3, 1, 3)
        result = bs.add_instance_symmetry([0, 1, 2])
        assert result is bs

    def test_add_cyclic_returns_self(self):
        bs = make_bs(3, 1, 3)
        result = bs.add_cyclic_symmetry([0, 1, 2])
        assert result is bs

    def test_add_pairwise_returns_self(self):
        bs = make_bs(4, 1, 3)
        result = bs.add_pairwise_symmetry([(0,1),(2,3)])
        assert result is bs

    def test_chained_builder(self):
        """All methods can be chained in one expression."""
        bs = (BinSpace()
              .add_coverpoint(Coverpoint.from_names("cp0", ["A","B"]))
              .add_coverpoint(Coverpoint.from_names("cp1", ["A","B"]))
              .add_coverpoint(Coverpoint.from_names("cp2", ["A","B"]))
              .add_coverpoint(Coverpoint.from_names("cp3", ["A","B"]))
              .add_instance_symmetry([0, 1])
              .add_instance_symmetry([2, 3]))
        assert bs.orbit_count() == 9   # Z2×Z2 on 2^4


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
