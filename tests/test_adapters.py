"""
tests/test_adapters.py
~~~~~~~~~~~~~~~~~~~~~~
Tests for OQ-04: Questa and VCS simulator coverage adapters.

Covers:
  questa adapter (from_vcover_text / from_vcover_report)
    - Basic cross bin extraction with counts
    - Zero-count bins excluded
    - Multi-covergroup file: correct covergroup selected by name
    - Multi-covergroup file: first cross used when covergroup=None
    - run_id defaults and overrides
    - simulator tag set to "questa"
    - covergroup name stored on result
    - Unknown covergroup raises ValueError with helpful message
    - list_covergroups utility

  vcs adapter (from_urg_text / from_urg_report)
    - Basic cross bin extraction with counts
    - Zero-count / Zero-status bins excluded
    - Multi-covergroup file: correct covergroup selected by name
    - Multi-covergroup file: first cross used when covergroup=None
    - run_id defaults and overrides
    - simulator tag set to "vcs"
    - covergroup name stored on result
    - Unknown covergroup raises ValueError with helpful message
    - list_covergroups utility

  Cross-adapter consistency
    - Same fixture data in Questa and VCS format produces identical
      CoverageResult contents (same hit labels, same counts)

  Integration with ExpansionEngine
    - Adapter output feeds directly into expand() without modification
    - Correct orbits are hit after expansion
"""

import sys, os, pytest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dabih.adapters.questa import (
    from_vcover_text, from_vcover_report, list_covergroups as questa_list_cgs,
)
from dabih.adapters.vcs import (
    from_urg_text, from_urg_report, list_covergroups as vcs_list_cgs,
)
from dabih.coverage.result import CoverageResult

FIXTURES = os.path.join(os.path.dirname(__file__), "..", "examples", "simulator")
def fx(name): return os.path.join(FIXTURES, name)

# ── Expected results for the 4-lane partial fixture ──────────────────────────
# Both simulators use the same bins/counts so we can compare them directly.

EXPECTED_HITS_4LANE = {
    ("IDLE",   "IDLE",   "IDLE",   "IDLE"):   5,
    ("IDLE",   "ACTIVE", "IDLE",   "IDLE"):   3,
    ("ACTIVE", "IDLE",   "IDLE",   "IDLE"):   2,
    ("STALL",  "IDLE",   "ACTIVE", "IDLE"):   1,
    ("IDLE",   "IDLE",   "ACTIVE", "ACTIVE"): 2,
    ("ACTIVE", "ACTIVE", "IDLE",   "IDLE"):   1,
    ("IDLE",   "STALL",  "IDLE",   "IDLE"):   1,
    ("ACTIVE", "IDLE",   "ACTIVE", "IDLE"):   1,
    ("IDLE",   "IDLE",   "IDLE",   "ACTIVE"): 2,
    ("ACTIVE", "ACTIVE", "ACTIVE", "IDLE"):   1,
    ("IDLE",   "ACTIVE", "STALL",  "IDLE"):   1,
    ("IDLE",   "IDLE",   "STALL",  "IDLE"):   1,
}

EXPECTED_ZERO_BINS_4LANE = {
    ("IDLE",   "IDLE",   "IDLE",   "STALL"),
    ("ERROR",  "IDLE",   "IDLE",   "IDLE"),
    ("ACTIVE", "STALL",  "IDLE",   "ACTIVE"),
}


# ═══════════════════════════════════════════════════════════════════════════════
# Questa adapter
# ═══════════════════════════════════════════════════════════════════════════════

class TestQuestaAdapter:

    # ── Basic parsing ─────────────────────────────────────────────────────────

    def test_reads_correct_number_of_hits(self):
        cr = from_vcover_report(fx("questa_4lane_partial.txt"),
                                covergroup="rx_lane_cross_cg")
        assert len(cr.hits) == len(EXPECTED_HITS_4LANE)

    def test_all_expected_labels_present(self):
        cr = from_vcover_report(fx("questa_4lane_partial.txt"),
                                covergroup="rx_lane_cross_cg")
        present = cr.hit_labels()
        for labels in EXPECTED_HITS_4LANE:
            assert labels in present, f"Missing: {labels}"

    def test_counts_are_correct(self):
        cr = from_vcover_report(fx("questa_4lane_partial.txt"),
                                covergroup="rx_lane_cross_cg")
        for labels, expected_count in EXPECTED_HITS_4LANE.items():
            assert cr.hit_count(labels) == expected_count, \
                f"Wrong count for {labels}: got {cr.hit_count(labels)}"

    def test_zero_bins_excluded(self):
        cr = from_vcover_report(fx("questa_4lane_partial.txt"),
                                covergroup="rx_lane_cross_cg")
        present = cr.hit_labels()
        for labels in EXPECTED_ZERO_BINS_4LANE:
            assert labels not in present, f"Zero bin should be absent: {labels}"

    def test_total_hits_sum(self):
        cr = from_vcover_report(fx("questa_4lane_partial.txt"),
                                covergroup="rx_lane_cross_cg")
        expected_total = sum(EXPECTED_HITS_4LANE.values())
        assert cr.total_hits() == expected_total

    # ── Metadata ──────────────────────────────────────────────────────────────

    def test_simulator_tag(self):
        cr = from_vcover_report(fx("questa_4lane_partial.txt"),
                                covergroup="rx_lane_cross_cg")
        assert cr.simulator == "questa"

    def test_covergroup_stored(self):
        cr = from_vcover_report(fx("questa_4lane_partial.txt"),
                                covergroup="rx_lane_cross_cg")
        assert cr.covergroup == "rx_lane_cross_cg"

    def test_run_id_defaults_to_filestem(self):
        cr = from_vcover_report(fx("questa_4lane_partial.txt"),
                                covergroup="rx_lane_cross_cg")
        assert cr.run_id == "questa_4lane_partial"

    def test_run_id_override(self):
        cr = from_vcover_report(fx("questa_4lane_partial.txt"),
                                covergroup="rx_lane_cross_cg",
                                run_id="seed_0042")
        assert cr.run_id == "seed_0042"

    # ── Multi-covergroup file ─────────────────────────────────────────────────

    def test_selects_correct_covergroup(self):
        cr = from_vcover_report(fx("questa_multi_cg.txt"),
                                covergroup="rx_lane_cross_cg")
        # rx_lane_cross_cg has 2-lane cross
        assert len(cr.hits) == 4
        assert cr.hit_count(("IDLE",   "IDLE"))   == 4
        assert cr.hit_count(("IDLE",   "ACTIVE")) == 1
        assert cr.hit_count(("ACTIVE", "IDLE"))   == 2
        assert cr.hit_count(("ACTIVE", "ACTIVE")) == 1

    def test_selects_tx_covergroup(self):
        cr = from_vcover_report(fx("questa_multi_cg.txt"),
                                covergroup="tx_lane_cross_cg")
        assert cr.hit_count(("IDLE", "IDLE")) == 5
        assert cr.hit_count(("SEND", "SEND")) == 2
        assert cr.hit_count(("IDLE", "FLUSH")) == 1

    def test_does_not_include_other_covergroup_bins(self):
        cr = from_vcover_report(fx("questa_multi_cg.txt"),
                                covergroup="rx_lane_cross_cg")
        # unrelated_cg has bins like (READ, SINGLE) — must not appear
        assert ("READ", "SINGLE") not in cr.hit_labels()

    def test_none_covergroup_uses_first_cross(self):
        # With covergroup=None, should pick up the first cross section found
        cr = from_vcover_text(
            open(fx("questa_4lane_partial.txt")).read(),
            covergroup=None,
        )
        assert len(cr.hits) == len(EXPECTED_HITS_4LANE)

    # ── Error handling ────────────────────────────────────────────────────────

    def test_unknown_covergroup_raises(self):
        with pytest.raises(ValueError, match="not found"):
            from_vcover_report(fx("questa_4lane_partial.txt"),
                               covergroup="no_such_cg")

    def test_error_message_lists_available_covergroups(self):
        with pytest.raises(ValueError) as exc:
            from_vcover_report(fx("questa_multi_cg.txt"),
                               covergroup="no_such_cg")
        msg = str(exc.value)
        assert "rx_lane_cross_cg" in msg or "unrelated_cg" in msg

    # ── list_covergroups ──────────────────────────────────────────────────────

    def test_list_covergroups_single(self):
        cgs = questa_list_cgs(fx("questa_4lane_partial.txt"))
        assert "rx_lane_cross_cg" in cgs

    def test_list_covergroups_multi(self):
        cgs = questa_list_cgs(fx("questa_multi_cg.txt"))
        assert "unrelated_cg"    in cgs
        assert "rx_lane_cross_cg" in cgs
        assert "tx_lane_cross_cg" in cgs
        assert len(cgs) == 3

    # ── from_vcover_text ──────────────────────────────────────────────────────

    def test_from_text_string(self):
        text = open(fx("questa_4lane_partial.txt")).read()
        cr = from_vcover_text(text, covergroup="rx_lane_cross_cg",
                              run_id="text_test")
        assert len(cr.hits) == len(EXPECTED_HITS_4LANE)
        assert cr.run_id == "text_test"


# ═══════════════════════════════════════════════════════════════════════════════
# VCS adapter
# ═══════════════════════════════════════════════════════════════════════════════

class TestVCSAdapter:

    # ── Basic parsing ─────────────────────────────────────────────────────────

    def test_reads_correct_number_of_hits(self):
        cr = from_urg_report(fx("vcs_4lane_partial.txt"),
                             covergroup="rx_lane_cross_cg")
        assert len(cr.hits) == len(EXPECTED_HITS_4LANE)

    def test_all_expected_labels_present(self):
        cr = from_urg_report(fx("vcs_4lane_partial.txt"),
                             covergroup="rx_lane_cross_cg")
        present = cr.hit_labels()
        for labels in EXPECTED_HITS_4LANE:
            assert labels in present, f"Missing: {labels}"

    def test_counts_are_correct(self):
        cr = from_urg_report(fx("vcs_4lane_partial.txt"),
                             covergroup="rx_lane_cross_cg")
        for labels, expected_count in EXPECTED_HITS_4LANE.items():
            assert cr.hit_count(labels) == expected_count, \
                f"Wrong count for {labels}: got {cr.hit_count(labels)}"

    def test_zero_bins_excluded(self):
        cr = from_urg_report(fx("vcs_4lane_partial.txt"),
                             covergroup="rx_lane_cross_cg")
        present = cr.hit_labels()
        for labels in EXPECTED_ZERO_BINS_4LANE:
            assert labels not in present, f"Zero bin should be absent: {labels}"

    def test_total_hits_sum(self):
        cr = from_urg_report(fx("vcs_4lane_partial.txt"),
                             covergroup="rx_lane_cross_cg")
        expected_total = sum(EXPECTED_HITS_4LANE.values())
        assert cr.total_hits() == expected_total

    # ── Metadata ──────────────────────────────────────────────────────────────

    def test_simulator_tag(self):
        cr = from_urg_report(fx("vcs_4lane_partial.txt"),
                             covergroup="rx_lane_cross_cg")
        assert cr.simulator == "vcs"

    def test_covergroup_stored(self):
        cr = from_urg_report(fx("vcs_4lane_partial.txt"),
                             covergroup="rx_lane_cross_cg")
        assert cr.covergroup == "rx_lane_cross_cg"

    def test_run_id_defaults_to_filestem(self):
        cr = from_urg_report(fx("vcs_4lane_partial.txt"),
                             covergroup="rx_lane_cross_cg")
        assert cr.run_id == "vcs_4lane_partial"

    def test_run_id_override(self):
        cr = from_urg_report(fx("vcs_4lane_partial.txt"),
                             covergroup="rx_lane_cross_cg",
                             run_id="seed_1337")
        assert cr.run_id == "seed_1337"

    # ── Multi-covergroup file ─────────────────────────────────────────────────

    def test_selects_correct_covergroup(self):
        cr = from_urg_report(fx("vcs_multi_cg.txt"),
                             covergroup="rx_lane_cross_cg")
        assert len(cr.hits) == 4
        assert cr.hit_count(("IDLE",   "IDLE"))   == 4
        assert cr.hit_count(("IDLE",   "ACTIVE")) == 1
        assert cr.hit_count(("ACTIVE", "IDLE"))   == 2
        assert cr.hit_count(("ACTIVE", "ACTIVE")) == 1

    def test_selects_tx_covergroup(self):
        cr = from_urg_report(fx("vcs_multi_cg.txt"),
                             covergroup="tx_lane_cross_cg")
        assert cr.hit_count(("IDLE", "IDLE")) == 5
        assert cr.hit_count(("SEND", "SEND")) == 2
        assert cr.hit_count(("IDLE", "FLUSH")) == 1

    def test_does_not_include_other_covergroup_bins(self):
        cr = from_urg_report(fx("vcs_multi_cg.txt"),
                             covergroup="rx_lane_cross_cg")
        assert ("READ", "SINGLE") not in cr.hit_labels()

    def test_none_covergroup_uses_first_cross(self):
        cr = from_urg_text(
            open(fx("vcs_4lane_partial.txt")).read(),
            covergroup=None,
        )
        assert len(cr.hits) == len(EXPECTED_HITS_4LANE)

    # ── Error handling ────────────────────────────────────────────────────────

    def test_unknown_covergroup_raises(self):
        with pytest.raises(ValueError, match="not found"):
            from_urg_report(fx("vcs_4lane_partial.txt"),
                            covergroup="no_such_cg")

    def test_error_message_lists_available_covergroups(self):
        with pytest.raises(ValueError) as exc:
            from_urg_report(fx("vcs_multi_cg.txt"),
                            covergroup="no_such_cg")
        msg = str(exc.value)
        assert "rx_lane_cross_cg" in msg or "unrelated_cg" in msg

    # ── list_covergroups ──────────────────────────────────────────────────────

    def test_list_covergroups_single(self):
        cgs = vcs_list_cgs(fx("vcs_4lane_partial.txt"))
        assert "rx_lane_cross_cg" in cgs

    def test_list_covergroups_multi(self):
        cgs = vcs_list_cgs(fx("vcs_multi_cg.txt"))
        assert "unrelated_cg"     in cgs
        assert "rx_lane_cross_cg"  in cgs
        assert "tx_lane_cross_cg"  in cgs
        assert len(cgs) == 3

    # ── from_urg_text ─────────────────────────────────────────────────────────

    def test_from_text_string(self):
        text = open(fx("vcs_4lane_partial.txt")).read()
        cr = from_urg_text(text, covergroup="rx_lane_cross_cg",
                           run_id="text_test")
        assert len(cr.hits) == len(EXPECTED_HITS_4LANE)
        assert cr.run_id == "text_test"


# ═══════════════════════════════════════════════════════════════════════════════
# Cross-adapter consistency
# ═══════════════════════════════════════════════════════════════════════════════

class TestCrossAdapterConsistency:
    """
    Both adapters processing the same underlying data must produce
    identical CoverageResult contents regardless of simulator format.
    """

    def test_same_hit_labels(self):
        cq = from_vcover_report(fx("questa_4lane_partial.txt"),
                                covergroup="rx_lane_cross_cg")
        cv = from_urg_report(fx("vcs_4lane_partial.txt"),
                             covergroup="rx_lane_cross_cg")
        assert cq.hit_labels() == cv.hit_labels()

    def test_same_hit_counts(self):
        cq = from_vcover_report(fx("questa_4lane_partial.txt"),
                                covergroup="rx_lane_cross_cg")
        cv = from_urg_report(fx("vcs_4lane_partial.txt"),
                             covergroup="rx_lane_cross_cg")
        for labels in cq.hit_labels():
            assert cq.hit_count(labels) == cv.hit_count(labels), \
                f"Count mismatch for {labels}"

    def test_same_total_hits(self):
        cq = from_vcover_report(fx("questa_4lane_partial.txt"),
                                covergroup="rx_lane_cross_cg")
        cv = from_urg_report(fx("vcs_4lane_partial.txt"),
                             covergroup="rx_lane_cross_cg")
        assert cq.total_hits() == cv.total_hits()

    def test_multi_cg_questa_vcs_rx_match(self):
        cq = from_vcover_report(fx("questa_multi_cg.txt"),
                                covergroup="rx_lane_cross_cg")
        cv = from_urg_report(fx("vcs_multi_cg.txt"),
                             covergroup="rx_lane_cross_cg")
        assert cq.hit_labels() == cv.hit_labels()

    def test_multi_cg_questa_vcs_tx_match(self):
        cq = from_vcover_report(fx("questa_multi_cg.txt"),
                                covergroup="tx_lane_cross_cg")
        cv = from_urg_report(fx("vcs_multi_cg.txt"),
                             covergroup="tx_lane_cross_cg")
        assert cq.hit_labels() == cv.hit_labels()

    def test_simulators_differ_in_metadata(self):
        """simulator field should differ even when data is identical."""
        cq = from_vcover_report(fx("questa_4lane_partial.txt"),
                                covergroup="rx_lane_cross_cg")
        cv = from_urg_report(fx("vcs_4lane_partial.txt"),
                             covergroup="rx_lane_cross_cg")
        assert cq.simulator == "questa"
        assert cv.simulator == "vcs"


# ═══════════════════════════════════════════════════════════════════════════════
# Integration with ExpansionEngine
# ═══════════════════════════════════════════════════════════════════════════════

class TestAdapterExpansionIntegration:
    """
    Adapter → ExpansionEngine → ExpansionResult end-to-end.
    Verifies that adapter output flows cleanly into the expansion pipeline.
    """

    def _make_4lane_bs(self):
        """4-lane BinSpace matching the fixture covergroup structure."""
        from dabih.core.bin_space import BinSpace
        from dabih.core.coverpoint import Coverpoint
        bs = BinSpace(name="4-lane rx")
        state_bins = ["IDLE", "ACTIVE", "STALL", "ERROR"]
        for i in range(4):
            bs.add_coverpoint(
                Coverpoint.from_names(f"lane{i}_state", state_bins)
            )
        bs.add_full_lane_symmetry(4)
        return bs

    def _make_2lane_bs(self):
        """2-lane BinSpace for the multi-cg rx fixture."""
        from dabih.core.bin_space import BinSpace
        from dabih.core.coverpoint import Coverpoint
        bs = BinSpace(name="2-lane rx")
        state_bins = ["IDLE", "ACTIVE", "STALL", "ERROR"]
        for i in range(2):
            bs.add_coverpoint(
                Coverpoint.from_names(f"lane{i}_state", state_bins)
            )
        bs.add_full_lane_symmetry(2)
        return bs

    def test_questa_adapter_feeds_expansion(self):
        from dabih.coverage.expander import ExpansionEngine
        bs = self._make_4lane_bs()
        cr = from_vcover_report(fx("questa_4lane_partial.txt"),
                                covergroup="rx_lane_cross_cg",
                                run_id="questa_run")
        er = ExpansionEngine(bs).expand(cr)
        # All hit bins must map to known orbits — no unresolved labels
        assert len(er.unresolved_labels) == 0
        # Some orbits must be covered
        assert er.n_orbits_hit() > 0
        # Coverage must be < 100% (fixture is partial)
        assert not er.is_complete()
        assert er.class_coverage_pct() > 0

    def test_vcs_adapter_feeds_expansion(self):
        from dabih.coverage.expander import ExpansionEngine
        bs = self._make_4lane_bs()
        cr = from_urg_report(fx("vcs_4lane_partial.txt"),
                             covergroup="rx_lane_cross_cg",
                             run_id="vcs_run")
        er = ExpansionEngine(bs).expand(cr)
        assert len(er.unresolved_labels) == 0
        assert er.n_orbits_hit() > 0
        assert not er.is_complete()

    def test_questa_vcs_produce_identical_expansion(self):
        """
        Same underlying data from two simulators must produce the same
        orbit coverage after expansion.
        """
        from dabih.coverage.expander import ExpansionEngine
        bs = self._make_4lane_bs()
        cr_q = from_vcover_report(fx("questa_4lane_partial.txt"),
                                  covergroup="rx_lane_cross_cg")
        cr_v = from_urg_report(fx("vcs_4lane_partial.txt"),
                               covergroup="rx_lane_cross_cg")
        er_q = ExpansionEngine(bs).expand(cr_q)
        er_v = ExpansionEngine(bs).expand(cr_v)

        assert er_q.n_orbits_hit()    == er_v.n_orbits_hit()
        assert er_q.n_bins_covered()  == er_v.n_bins_covered()
        assert er_q.class_coverage_pct() == er_v.class_coverage_pct()

    def test_merge_questa_and_vcs_runs(self):
        """
        Merging a Questa run and a VCS run for different seeds should work
        the same as merging two Dabih-native CoverageResults.
        """
        from dabih.coverage.expander import ExpansionEngine
        bs = self._make_4lane_bs()
        cr_q = from_vcover_report(fx("questa_4lane_partial.txt"),
                                  covergroup="rx_lane_cross_cg",
                                  run_id="questa_seed_42")
        cr_v = from_urg_report(fx("vcs_4lane_partial.txt"),
                               covergroup="rx_lane_cross_cg",
                               run_id="vcs_seed_99")
        # Both have the same hits so merged == individual
        er = ExpansionEngine(bs).merge_and_expand([cr_q, cr_v])
        er_single = ExpansionEngine(bs).expand(cr_q)
        assert er.n_orbits_hit() == er_single.n_orbits_hit()

    def test_2lane_multi_cg_expansion(self):
        """Multi-cg fixture with 2-lane cross feeds expansion correctly."""
        from dabih.coverage.expander import ExpansionEngine
        bs = self._make_2lane_bs()
        cr = from_vcover_report(fx("questa_multi_cg.txt"),
                                covergroup="rx_lane_cross_cg")
        er = ExpansionEngine(bs).expand(cr)
        assert len(er.unresolved_labels) == 0
        assert er.n_orbits_hit() > 0

    def test_adapter_result_round_trips_json(self):
        """CoverageResult from adapter must round-trip through JSON cleanly."""
        cr = from_vcover_report(fx("questa_4lane_partial.txt"),
                                covergroup="rx_lane_cross_cg")
        restored = CoverageResult.from_json(cr.to_json())
        assert restored.hit_labels() == cr.hit_labels()
        assert restored.total_hits() == cr.total_hits()
        assert restored.simulator    == cr.simulator
        assert restored.covergroup   == cr.covergroup

    def test_symbolic_engine_accepts_adapter_output(self):
        """SymbolicExpansionEngine must accept adapter output unchanged."""
        from dabih.coverage.symbolic_expander import SymbolicExpansionEngine
        bs = self._make_4lane_bs()
        cr = from_urg_report(fx("vcs_4lane_partial.txt"),
                             covergroup="rx_lane_cross_cg")
        er = SymbolicExpansionEngine(bs).expand(cr)
        assert er.n_orbits() == 35   # C(7,4) for S4 on 4 bins
        assert er.n_orbits_hit() > 0


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
