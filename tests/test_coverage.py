"""
tests/test_coverage.py
~~~~~~~~~~~~~~~~~~~~~~~
Tests for Idea C: coverage DB post-processor / expansion engine.

Covers:
  CoverageResult
    - construction from hits, from_json, from_file, round-trip serialisation
    - hit_labels, hit_count, total_hits

  ExpansionEngine
    - full coverage (all reps hit → all bins covered)
    - zero coverage (no reps hit → nothing covered)
    - partial coverage (subset of orbits hit)
    - non-rep hit implies the whole orbit
    - unresolved label-tuples (wrong name, wrong arity)
    - merge_and_expand across multiple runs
    - ExpansionResult statistics correctness
    - is_complete flag
    - holes report (missed representatives)
    - to_dict serialisation

  Integration
    - RTL extractor → BinSpaceBuilder → ExpansionEngine end-to-end
"""

import sys, os, json, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from dabih.core.bin_space import BinSpace
from dabih.core.coverpoint import Coverpoint
from dabih.core.symmetry import Permutation
from dabih.coverage.result import CoverageResult, BinHit
from dabih.coverage.expander import ExpansionEngine, ExpansionResult

FIXTURES = os.path.join(os.path.dirname(__file__), "..", "examples", "rtl")
def fx(name): return os.path.join(FIXTURES, name)


# ── Shared fixtures ───────────────────────────────────────────────────────────

def make_3lane_bs() -> BinSpace:
    """3-lane S3 BinSpace — 4-bin state per lane. 64 bins → 20 orbits."""
    bs = BinSpace(name="3-lane S3")
    for i in range(3):
        bs.add_coverpoint(Coverpoint.from_names(f"lane{i}", ["IDLE","ACTIVE","STALL","ERROR"]))
    bs.add_full_lane_symmetry(3)
    return bs

def make_2lane_bs() -> BinSpace:
    """2-lane S2 BinSpace — 3-bin state per lane. 9 bins → 6 orbits."""
    bs = BinSpace(name="2-lane S2")
    for i in range(2):
        bs.add_coverpoint(Coverpoint.from_names(f"lane{i}", ["IDLE","ACTIVE","ERROR"]))
    bs.add_full_lane_symmetry(2)
    return bs

def all_reps(bs: BinSpace) -> list:
    """Label-tuples for all orbit representatives."""
    return [bs.bin_label(r) for r in bs.select_representatives()]


# ═══════════════════════════════════════════════════════════════════════════════
# CoverageResult tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestCoverageResult:

    def test_from_hits_tuple_with_count(self):
        r = CoverageResult.from_hits([
            (("IDLE","IDLE","IDLE"), 5),
            (("ACTIVE","IDLE","ACTIVE"), 2),
        ])
        assert len(r.hits) == 2
        assert r.hit_count(("IDLE","IDLE","IDLE")) == 5

    def test_from_hits_bare_tuple(self):
        r = CoverageResult.from_hits([("IDLE","ACTIVE")])
        assert len(r.hits) == 1
        assert r.hit_count(("IDLE","ACTIVE")) == 1

    def test_hit_labels_set(self):
        r = CoverageResult.from_hits([
            (("A","B"), 3),
            (("C","D"), 1),
        ])
        assert r.hit_labels() == {("A","B"), ("C","D")}

    def test_total_hits(self):
        r = CoverageResult.from_hits([
            (("A","B"), 10),
            (("C","D"),  5),
        ])
        assert r.total_hits() == 15

    def test_hit_count_missing_returns_zero(self):
        r = CoverageResult.from_hits([(("X","Y"), 3)])
        assert r.hit_count(("NOT","HERE")) == 0

    def test_json_round_trip(self):
        r = CoverageResult.from_hits([
            (("IDLE","ACTIVE","STALL"), 7),
            (("ERROR","ERROR","ERROR"), 1),
        ], run_id="test_run", simulator="questa", covergroup="lane_cg")
        text = r.to_json()
        r2 = CoverageResult.from_json(text)
        assert len(r2.hits) == 2
        assert r2.run_id == "test_run"
        assert r2.simulator == "questa"
        assert r2.covergroup == "lane_cg"
        assert r2.hit_count(("IDLE","ACTIVE","STALL")) == 7

    def test_from_file_round_trip(self):
        r = CoverageResult.from_hits([(("A","B"), 3)], run_id="file_test")
        with tempfile.NamedTemporaryFile(suffix=".json", mode="w", delete=False) as f:
            f.write(r.to_json())
            path = f.name
        try:
            r2 = CoverageResult.from_file(path)
            assert r2.run_id == "file_test"
            assert r2.hit_count(("A","B")) == 3
        finally:
            os.unlink(path)

    def test_to_dict_has_hits_key(self):
        r = CoverageResult.from_hits([(("X","Y"), 2)])
        d = r.to_dict()
        assert "hits" in d
        assert d["hits"][0]["bin"] == ["X","Y"]
        assert d["hits"][0]["count"] == 2

    def test_empty_result(self):
        r = CoverageResult()
        assert len(r) == 0
        assert r.total_hits() == 0
        assert r.hit_labels() == set()

    def test_minimal_json_no_metadata(self):
        text = json.dumps({"hits": [{"bin": ["A","B"], "count": 1}]})
        r = CoverageResult.from_json(text)
        assert len(r.hits) == 1
        assert r.run_id == ""


# ═══════════════════════════════════════════════════════════════════════════════
# ExpansionEngine tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestExpansionEngine:

    # ── Full coverage ─────────────────────────────────────────────────────────

    def test_full_coverage_all_classes_hit(self):
        bs = make_3lane_bs()
        reps = all_reps(bs)
        result = CoverageResult.from_hits([(r, 1) for r in reps])
        er = ExpansionEngine(bs).expand(result)

        assert er.is_complete()
        assert er.n_orbits_hit() == 20
        assert er.n_orbits() == 20
        assert er.n_bins_covered() == 64
        assert er.class_coverage_pct() == 100.0
        assert er.bin_coverage_pct() == 100.0
        assert len(er.orbits_missed) == 0

    def test_full_coverage_all_bins_marked(self):
        bs = make_3lane_bs()
        reps = all_reps(bs)
        result = CoverageResult.from_hits([(r, 5) for r in reps])
        er = ExpansionEngine(bs).expand(result)
        assert all(c > 0 for c in er.coverage_map.values())

    # ── Zero coverage ─────────────────────────────────────────────────────────

    def test_zero_coverage_empty_result(self):
        bs = make_3lane_bs()
        er = ExpansionEngine(bs).expand(CoverageResult())
        assert not er.is_complete()
        assert er.n_orbits_hit() == 0
        assert er.n_bins_covered() == 0
        assert er.class_coverage_pct() == 0.0
        assert er.bin_coverage_pct() == 0.0
        assert len(er.orbits_missed) == 20

    def test_zero_coverage_all_bins_zero(self):
        bs = make_3lane_bs()
        er = ExpansionEngine(bs).expand(CoverageResult())
        assert all(c == 0 for c in er.coverage_map.values())

    # ── Partial coverage ──────────────────────────────────────────────────────

    def test_partial_coverage_correct_counts(self):
        bs = make_3lane_bs()
        reps = bs.select_representatives()
        # Hit first 10 of 20 orbits
        hit_reps = reps[:10]
        label_hits = [(bs.bin_label(r), 3) for r in hit_reps]
        result = CoverageResult.from_hits(label_hits)
        er = ExpansionEngine(bs).expand(result)

        assert er.n_orbits_hit() == 10
        assert len(er.orbits_missed) == 10
        assert not er.is_complete()

    def test_partial_coverage_bin_count(self):
        """Bins covered = sum of sizes of hit orbits."""
        bs = make_3lane_bs()
        orbits = bs.compute_orbits()
        # Hit exactly the first 5 orbits by their representatives
        hit_reps = [o.representative for o in orbits[:5]]
        expected_bins = sum(o.size() for o in orbits[:5])

        label_hits = [(bs.bin_label(r), 1) for r in hit_reps]
        result = CoverageResult.from_hits(label_hits)
        er = ExpansionEngine(bs).expand(result)
        assert er.n_bins_covered() == expected_bins

    def test_partial_coverage_correct_orbit_attribution(self):
        """A hit bin should mark exactly its orbit's members as covered."""
        bs = make_3lane_bs()
        target_orbit = bs.compute_orbits()[7]  # arbitrary orbit
        rep_label = bs.bin_label(target_orbit.representative)
        result = CoverageResult.from_hits([(rep_label, 1)])
        er = ExpansionEngine(bs).expand(result)

        # All members of the target orbit should be covered
        for member in target_orbit.members:
            assert er.coverage_map[member] > 0

        # All other orbits should be zero
        for orbit in bs.compute_orbits():
            if orbit.id != target_orbit.id:
                for member in orbit.members:
                    assert er.coverage_map[member] == 0

    # ── Non-representative hit ────────────────────────────────────────────────

    def test_non_rep_hit_covers_whole_orbit(self):
        """
        Hitting a non-representative member of an orbit should still cover
        the full orbit (simulation may exercise any member, not just the rep).
        """
        bs = make_3lane_bs()
        orbits = bs.compute_orbits()
        # Find an orbit with more than one member
        multi = next(o for o in orbits if o.size() > 1)
        # Pick a non-representative member
        non_rep = next(m for m in multi.members if m != multi.representative)
        non_rep_label = bs.bin_label(non_rep)

        result = CoverageResult.from_hits([(non_rep_label, 2)])
        er = ExpansionEngine(bs).expand(result)

        assert er.n_orbits_hit() == 1
        for member in multi.members:
            assert er.coverage_map[member] > 0

    # ── Hit count propagation ─────────────────────────────────────────────────

    def test_hit_count_propagates_to_members(self):
        """Members of a covered orbit carry the representative's hit count."""
        bs = make_2lane_bs()
        reps = bs.select_representatives()
        result = CoverageResult.from_hits([(bs.bin_label(reps[0]), 42)])
        er = ExpansionEngine(bs).expand(result)

        orbit = bs.compute_orbits()[0]
        for member in orbit.members:
            assert er.coverage_map[member] == 42

    def test_multiple_hits_same_orbit_uses_max(self):
        """If two members of the same orbit are hit, use the higher count."""
        bs = make_3lane_bs()
        # Find an orbit with ≥2 members
        orbit = next(o for o in bs.compute_orbits() if o.size() >= 2)
        m0_label = bs.bin_label(orbit.members[0])
        m1_label = bs.bin_label(orbit.members[1])
        result = CoverageResult.from_hits([
            (m0_label, 10),
            (m1_label,  3),
        ])
        er = ExpansionEngine(bs).expand(result)
        # All members should carry the max count
        for member in orbit.members:
            assert er.coverage_map[member] == 10

    # ── Unresolved labels ─────────────────────────────────────────────────────

    def test_unresolved_wrong_label_name(self):
        bs = make_2lane_bs()
        result = CoverageResult.from_hits([
            (("IDLE","ACTIVE"), 1),
            (("BOGUS_STATE","IDLE"), 1),   # BOGUS_STATE doesn't exist
        ])
        er = ExpansionEngine(bs).expand(result)
        assert len(er.unresolved_labels) == 1
        assert ("BOGUS_STATE","IDLE") in er.unresolved_labels

    def test_unresolved_wrong_arity(self):
        bs = make_2lane_bs()
        result = CoverageResult.from_hits([
            (("IDLE","ACTIVE","EXTRA"), 1),   # 3 labels for 2-cp space
        ])
        er = ExpansionEngine(bs).expand(result)
        assert len(er.unresolved_labels) == 1

    def test_unresolved_does_not_affect_valid_hits(self):
        bs = make_2lane_bs()
        result = CoverageResult.from_hits([
            (("IDLE","ACTIVE"), 5),
            (("INVALID",), 1),
        ])
        er = ExpansionEngine(bs).expand(result)
        # The valid hit should still be processed
        assert er.n_orbits_hit() >= 1
        assert len(er.unresolved_labels) == 1

    # ── is_covered / hit_count helpers ───────────────────────────────────────

    def test_is_covered_by_label(self):
        bs = make_2lane_bs()
        reps = all_reps(bs)
        result = CoverageResult.from_hits([(reps[0], 1)])
        er = ExpansionEngine(bs).expand(result)
        assert er.is_covered(reps[0])

    def test_is_not_covered_missed_orbit(self):
        bs = make_2lane_bs()
        reps = all_reps(bs)
        result = CoverageResult.from_hits([(reps[0], 1)])
        er = ExpansionEngine(bs).expand(result)
        # All other reps should not be covered
        for r in reps[1:]:
            # Find reps that are NOT in the hit orbit
            orbit0 = bs.compute_orbits()[0]
            member_labels = {bs.bin_label(m) for m in orbit0.members}
            if r not in member_labels:
                assert not er.is_covered(r)

    def test_hit_count_label_lookup(self):
        bs = make_2lane_bs()
        rep_label = all_reps(bs)[0]
        result = CoverageResult.from_hits([(rep_label, 99)])
        er = ExpansionEngine(bs).expand(result)
        assert er.hit_count(rep_label) == 99

    # ── merge_and_expand ──────────────────────────────────────────────────────

    def test_merge_two_runs_union_of_orbits(self):
        """Two runs covering disjoint orbit sets → merged covers both."""
        bs = make_3lane_bs()
        reps = bs.select_representatives()
        first_half  = reps[:10]
        second_half = reps[10:]

        run1 = CoverageResult.from_hits([(bs.bin_label(r), 1) for r in first_half])
        run2 = CoverageResult.from_hits([(bs.bin_label(r), 1) for r in second_half])

        er = ExpansionEngine(bs).merge_and_expand([run1, run2])
        assert er.is_complete()
        assert er.n_orbits_hit() == 20

    def test_merge_overlapping_runs_sums_counts(self):
        """Same bin hit in two runs → counts are summed."""
        bs = make_2lane_bs()
        rep_label = all_reps(bs)[0]
        run1 = CoverageResult.from_hits([(rep_label, 3)])
        run2 = CoverageResult.from_hits([(rep_label, 7)])
        er = ExpansionEngine(bs).merge_and_expand([run1, run2])
        # Merged count = 10; max of orbit members = 10
        orbit = bs.compute_orbits()[0]
        assert er.coverage_map[orbit.representative] == 10

    def test_merge_empty_list(self):
        """Empty list of runs → zero coverage."""
        bs = make_2lane_bs()
        er = ExpansionEngine(bs).merge_and_expand([])
        assert er.n_orbits_hit() == 0

    def test_merge_single_run_identical_to_expand(self):
        bs = make_3lane_bs()
        reps = bs.select_representatives()
        hit = [(bs.bin_label(r), 2) for r in reps[:5]]
        result = CoverageResult.from_hits(hit)
        er_single = ExpansionEngine(bs).expand(result)
        er_merged  = ExpansionEngine(bs).merge_and_expand([result])
        assert er_single.n_orbits_hit() == er_merged.n_orbits_hit()
        assert er_single.n_bins_covered() == er_merged.n_bins_covered()

    # ── ExpansionResult helpers ───────────────────────────────────────────────

    def test_covered_bins_list(self):
        bs = make_2lane_bs()
        orbit = bs.compute_orbits()[0]
        rep_label = bs.bin_label(orbit.representative)
        result = CoverageResult.from_hits([(rep_label, 1)])
        er = ExpansionEngine(bs).expand(result)
        covered = set(er.covered_bins())
        assert set(orbit.members).issubset(covered)

    def test_uncovered_bins_list(self):
        bs = make_2lane_bs()
        er = ExpansionEngine(bs).expand(CoverageResult())
        assert len(er.uncovered_bins()) == bs.total_bin_count()

    def test_missed_representatives(self):
        bs = make_3lane_bs()
        reps = bs.select_representatives()
        result = CoverageResult.from_hits([(bs.bin_label(reps[0]), 1)])
        er = ExpansionEngine(bs).expand(result)
        missed = set(er.missed_representatives())
        # All reps except those in orbit 0 should be missed
        orbit0_members = set(bs.compute_orbits()[0].members)
        for r in reps[1:]:
            if r not in orbit0_members:
                assert r in missed

    # ── to_dict / report ─────────────────────────────────────────────────────

    def test_to_dict_structure(self):
        bs = make_2lane_bs()
        reps = all_reps(bs)
        result = CoverageResult.from_hits([(reps[0], 1)], run_id="dict_test")
        er = ExpansionEngine(bs).expand(result)
        d = er.to_dict()
        assert "class_coverage" in d
        assert "bin_coverage" in d
        assert "holes" in d
        assert "complete" in d
        assert "compression" in d
        assert d["run_id"] == "dict_test"

    def test_to_dict_holes_contain_rep_labels(self):
        bs = make_2lane_bs()
        er = ExpansionEngine(bs).expand(CoverageResult())
        d = er.to_dict()
        assert len(d["holes"]) == bs.orbit_count()
        for hole in d["holes"]:
            assert "rep_labels" in hole
            assert "orbit_size" in hole

    def test_report_contains_key_fields(self):
        bs = make_3lane_bs()
        reps = all_reps(bs)
        result = CoverageResult.from_hits(
            [(r, 1) for r in reps[:10]],
            run_id="report_test", simulator="questa"
        )
        er = ExpansionEngine(bs).expand(result)
        report = er.report()
        assert "Dabih" in report
        assert "report_test" in report
        assert "questa" in report
        assert "50.00%" in report   # 10/20 classes
        assert "Holes" in report

    def test_report_complete_no_holes_section(self):
        bs = make_2lane_bs()
        reps = all_reps(bs)
        result = CoverageResult.from_hits([(r, 1) for r in reps])
        er = ExpansionEngine(bs).expand(result)
        report = er.report()
        assert "COMPLETE" in report

    def test_report_unresolved_shown(self):
        bs = make_2lane_bs()
        result = CoverageResult.from_hits([
            (("IDLE","ACTIVE"), 1),
            (("NO_SUCH_BIN","IDLE"), 1),
        ])
        er = ExpansionEngine(bs).expand(result)
        report = er.report()
        assert "Unresolved" in report

    # ── Statistics correctness ────────────────────────────────────────────────

    def test_compression_ratio_matches_bin_space(self):
        bs = make_3lane_bs()
        er = ExpansionEngine(bs).expand(CoverageResult())
        assert abs(er.compression_ratio() - bs.compression_ratio()) < 0.001

    def test_class_coverage_pct_formula(self):
        bs = make_3lane_bs()
        reps = bs.select_representatives()
        n_hit = 7
        result = CoverageResult.from_hits([(bs.bin_label(r), 1) for r in reps[:n_hit]])
        er = ExpansionEngine(bs).expand(result)
        expected = 100 * n_hit / 20
        assert abs(er.class_coverage_pct() - expected) < 0.01

    def test_bin_coverage_pct_formula(self):
        """Bin coverage = (sum of hit orbit sizes) / total bins × 100."""
        bs = make_3lane_bs()
        orbits = bs.compute_orbits()
        target_orbits = orbits[:4]
        expected_covered = sum(o.size() for o in target_orbits)
        hit = [(bs.bin_label(o.representative), 1) for o in target_orbits]
        result = CoverageResult.from_hits(hit)
        er = ExpansionEngine(bs).expand(result)
        assert er.n_bins_covered() == expected_covered
        expected_pct = 100 * expected_covered / 64
        assert abs(er.bin_coverage_pct() - expected_pct) < 0.01


# ═══════════════════════════════════════════════════════════════════════════════
# End-to-end integration: RTL → BinSpace → ExpansionEngine
# ═══════════════════════════════════════════════════════════════════════════════

class TestIdeaCIntegration:

    def test_rtl_to_expansion_serdes(self):
        """Full pipeline: RTL extract → BinSpace → expand → report."""
        from dabih.rtl import RtlExtractor, BinSpaceBuilder, CoverSpec

        ext = (RtlExtractor()
               .add_file(fx("serdes_top.sv"))
               .add_param("N_LANES", 4))
        arrays = [a for a in ext.extract() if a.module_type == "rx_lane"]

        results = (BinSpaceBuilder(arrays)
                   .cover("state", ["IDLE","ACTIVE","STALL","ERROR"])
                   .build(ext.param_overrides))

        assert len(results) == 1
        bs = results[0].bin_space

        # Simulate: hit representatives for the first 10 orbits
        engine = ExpansionEngine(bs)
        reps = bs.select_representatives()
        sim_result = CoverageResult.from_hits(
            [(bs.bin_label(r), 1) for r in reps[:10]],
            run_id="serdes_test", simulator="questa",
        )
        er = engine.expand(sim_result)

        assert er.n_orbits() == 35       # C(7,4) for S4 on 4 bins
        assert er.n_orbits_hit() == 10
        assert not er.is_complete()
        report = er.report()
        assert "serdes_test" in report
        assert "Holes" in report

    def test_incremental_regression_closes_coverage(self):
        """Multiple simulation runs incrementally close coverage gaps."""
        from dabih.rtl import RtlExtractor, BinSpaceBuilder

        ext = (RtlExtractor()
               .add_file(fx("mem_ctrl.sv")))
        arrays = ext.extract()

        results = (BinSpaceBuilder(arrays)
                   .cover("ch_state", ["IDLE","BUSY","ERROR"])
                   .build())

        bs = results[0].bin_space
        engine = ExpansionEngine(bs)

        # 45 total orbits (C(10,8) for S8 on 3 bins)
        assert bs.orbit_count() == 45
        all_rep_labels = [bs.bin_label(r) for r in bs.select_representatives()]

        # Split across 3 runs of 15 orbits each
        run1 = CoverageResult.from_hits([(r, 1) for r in all_rep_labels[:15]])
        run2 = CoverageResult.from_hits([(r, 1) for r in all_rep_labels[15:30]])
        run3 = CoverageResult.from_hits([(r, 1) for r in all_rep_labels[30:]])

        er = engine.merge_and_expand([run1, run2, run3])
        assert er.is_complete()
        assert er.n_bins_covered() == bs.total_bin_count()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
