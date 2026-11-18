"""
tests/test_provenance.py
~~~~~~~~~~~~~~~~~~~~~~~~~
Tests for OQ-06: Coverage provenance tracking in merge.

Covers:
  ExpansionResult provenance (BFS engine)
    - has_provenance False by default (expand / merge without flag)
    - has_provenance True when track_provenance=True
    - orbit_run_ids returns [] without provenance
    - orbit_run_ids returns correct run_ids for a covered orbit
    - orbit_run_ids returns [] for uncovered orbit
    - coverage_count returns 0 without provenance
    - coverage_count matches len(orbit_run_ids)
    - single_coverage_orbits returns [] without provenance
    - single_coverage_orbits correct when 1-run orbits exist
    - coverage_histogram returns {} without provenance
    - coverage_histogram correct distribution
    - fragile_orbits returns [] without provenance
    - fragile_orbits default threshold=2
    - fragile_orbits custom threshold
    - to_dict has no provenance key without tracking
    - to_dict has provenance sub-dict with tracking
    - report() has confidence section with tracking
    - report() has no confidence section without tracking
    - merge_and_expand accumulates run_ids per orbit
    - merge_and_expand deduplicates run_id within one orbit
    - single expand builds trivial provenance (all orbits → [run_id])

  SymbolicExpansionResult provenance
    - Same API contract as BFS (has_provenance, orbit_run_ids, etc.)
    - canonical form used for keying
    - merge_and_expand tracks run_ids correctly

  Integration with CLI (--provenance flag)
    - dabih expand --provenance prints confidence section
    - dabih expand without --provenance omits confidence section
    - to_dict includes provenance key when flag set
"""

import sys, os, json, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from dabih.core.bin_space import BinSpace
from dabih.core.coverpoint import Coverpoint
from dabih.coverage.result import CoverageResult
from dabih.coverage.expander import ExpansionEngine
from dabih.coverage.symbolic_expander import SymbolicExpansionEngine

FIXTURES = os.path.join(os.path.dirname(__file__), "..", "examples", "rtl")
SERDES   = os.path.join(FIXTURES, "serdes_top.sv")


# ── Helpers ───────────────────────────────────────────────────────────────────

def make_bs(n: int = 3, k: int = 4) -> BinSpace:
    bs = BinSpace(name=f"S{n}_k{k}")
    for i in range(n):
        bs.add_coverpoint(
            Coverpoint.from_names(f"cp{i}", [f"b{v}" for v in range(k)])
        )
    bs.add_full_lane_symmetry(n)
    return bs

def make_run(bs: BinSpace, reps: list, run_id: str,
             n_hit: int | None = None) -> CoverageResult:
    """Create a CoverageResult hitting the first n_hit representatives."""
    n = n_hit if n_hit is not None else len(reps)
    hits = [(bs.bin_label(r), 1) for r in reps[:n]]
    return CoverageResult.from_hits(hits, run_id=run_id)


# ═══════════════════════════════════════════════════════════════════════════════
# BFS ExpansionResult provenance
# ═══════════════════════════════════════════════════════════════════════════════

class TestBFSProvenance:

    def setup_method(self):
        self.bs   = make_bs(3, 4)   # 20 orbits
        self.eng  = ExpansionEngine(self.bs)
        self.reps = self.bs.select_representatives()

    # ── has_provenance ────────────────────────────────────────────────────────

    def test_no_provenance_by_default_expand(self):
        r = CoverageResult.from_hits([(self.bs.bin_label(self.reps[0]), 1)])
        er = self.eng.expand(r)
        assert not er.has_provenance

    def test_no_provenance_by_default_merge(self):
        r = CoverageResult.from_hits([(self.bs.bin_label(self.reps[0]), 1)])
        er = self.eng.merge_and_expand([r])
        assert not er.has_provenance

    def test_has_provenance_expand_with_flag(self):
        r = CoverageResult.from_hits(
            [(self.bs.bin_label(self.reps[0]), 1)], run_id="s1"
        )
        er = self.eng.expand(r, track_provenance=True)
        assert er.has_provenance

    def test_has_provenance_merge_with_flag(self):
        r = CoverageResult.from_hits(
            [(self.bs.bin_label(self.reps[0]), 1)], run_id="s1"
        )
        er = self.eng.merge_and_expand([r], track_provenance=True)
        assert er.has_provenance

    # ── orbit_run_ids ─────────────────────────────────────────────────────────

    def test_orbit_run_ids_empty_without_provenance(self):
        r  = CoverageResult.from_hits([(self.bs.bin_label(self.reps[0]), 1)])
        er = self.eng.expand(r)
        assert er.orbit_run_ids(self.bs.bin_label(self.reps[0])) == []

    def test_orbit_run_ids_single_run(self):
        rep_label = self.bs.bin_label(self.reps[0])
        r  = CoverageResult.from_hits([(rep_label, 1)], run_id="seed_42")
        er = self.eng.expand(r, track_provenance=True)
        assert er.orbit_run_ids(rep_label) == ["seed_42"]

    def test_orbit_run_ids_uncovered_orbit(self):
        rep0 = self.bs.bin_label(self.reps[0])
        rep1 = self.bs.bin_label(self.reps[1])
        r  = CoverageResult.from_hits([(rep0, 1)], run_id="s1")
        er = self.eng.expand(r, track_provenance=True)
        assert er.orbit_run_ids(rep1) == []

    def test_orbit_run_ids_merge_two_runs_same_orbit(self):
        """Two runs both covering orbit 0 → both run_ids recorded."""
        rep_label = self.bs.bin_label(self.reps[0])
        r1 = CoverageResult.from_hits([(rep_label, 1)], run_id="s1")
        r2 = CoverageResult.from_hits([(rep_label, 1)], run_id="s2")
        er = self.eng.merge_and_expand([r1, r2], track_provenance=True)
        ids = sorted(er.orbit_run_ids(rep_label))
        assert ids == ["s1", "s2"]

    def test_orbit_run_ids_merge_different_orbits(self):
        """Run1 covers orbit 0, run2 covers orbit 1 — no cross-attribution."""
        l0 = self.bs.bin_label(self.reps[0])
        l1 = self.bs.bin_label(self.reps[1])
        r1 = CoverageResult.from_hits([(l0, 1)], run_id="s1")
        r2 = CoverageResult.from_hits([(l1, 1)], run_id="s2")
        er = self.eng.merge_and_expand([r1, r2], track_provenance=True)
        assert er.orbit_run_ids(l0) == ["s1"]
        assert er.orbit_run_ids(l1) == ["s2"]

    def test_orbit_run_ids_deduplicates_same_run_multiple_hits(self):
        """Same run_id hitting the same orbit twice → appears once."""
        rep_label = self.bs.bin_label(self.reps[0])
        r = CoverageResult.from_hits([(rep_label, 5)], run_id="s1")
        er = self.eng.merge_and_expand([r, r], track_provenance=True)
        assert er.orbit_run_ids(rep_label).count("s1") == 1

    # ── coverage_count ────────────────────────────────────────────────────────

    def test_coverage_count_zero_without_provenance(self):
        r  = CoverageResult.from_hits([(self.bs.bin_label(self.reps[0]), 1)])
        er = self.eng.expand(r)
        assert er.coverage_count(self.bs.bin_label(self.reps[0])) == 0

    def test_coverage_count_matches_run_ids_length(self):
        l0 = self.bs.bin_label(self.reps[0])
        r1 = CoverageResult.from_hits([(l0, 1)], run_id="s1")
        r2 = CoverageResult.from_hits([(l0, 1)], run_id="s2")
        r3 = CoverageResult.from_hits([(l0, 1)], run_id="s3")
        er = self.eng.merge_and_expand([r1, r2, r3], track_provenance=True)
        assert er.coverage_count(l0) == 3
        assert len(er.orbit_run_ids(l0)) == 3

    # ── single_coverage_orbits ────────────────────────────────────────────────

    def test_single_coverage_orbits_empty_without_provenance(self):
        r  = CoverageResult.from_hits([(self.bs.bin_label(self.reps[0]), 1)])
        er = self.eng.expand(r)
        assert er.single_coverage_orbits() == []

    def test_single_coverage_orbits_identified(self):
        """Orbit 0 covered by 1 run, orbit 1 covered by 2 runs."""
        l0 = self.bs.bin_label(self.reps[0])
        l1 = self.bs.bin_label(self.reps[1])
        r1 = CoverageResult.from_hits([(l0, 1), (l1, 1)], run_id="s1")
        r2 = CoverageResult.from_hits([(l1, 1)], run_id="s2")
        er = self.eng.merge_and_expand([r1, r2], track_provenance=True)
        single = er.single_coverage_orbits()
        # Orbit 0 covered once → in single list
        assert self.reps[0] in single
        # Orbit 1 covered twice → NOT in single list
        assert self.reps[1] not in single

    # ── coverage_histogram ────────────────────────────────────────────────────

    def test_coverage_histogram_empty_without_provenance(self):
        r  = CoverageResult.from_hits([(self.bs.bin_label(self.reps[0]), 1)])
        er = self.eng.expand(r)
        assert er.coverage_histogram() == {}

    def test_coverage_histogram_correct(self):
        """
        5 orbits covered by 1 run, 3 by 2 runs, 2 by 3 runs.
        Histogram should be {1:5, 2:3, 3:2}.
        """
        reps = self.reps
        l    = lambda i: self.bs.bin_label(reps[i])
        # 5 orbits hit only in r1
        r1_hits = [(l(i), 1) for i in range(10)]   # orbits 0–9
        r2_hits = [(l(i), 1) for i in range(5, 13)] # orbits 5–12
        r3_hits = [(l(i), 1) for i in range(8, 10)] # orbits 8–9
        r1 = CoverageResult.from_hits(r1_hits, run_id="s1")
        r2 = CoverageResult.from_hits(r2_hits, run_id="s2")
        r3 = CoverageResult.from_hits(r3_hits, run_id="s3")
        er = self.eng.merge_and_expand([r1, r2, r3], track_provenance=True)
        hist = er.coverage_histogram()
        # orbits 0-4: s1 only → count=1 (5 orbits)
        # orbits 5-7: s1+s2 → count=2 (3 orbits)
        # orbits 8-9: s1+s2+s3 → count=3 (2 orbits)
        # orbits 10-12: s2 only → count=1 (3 orbits) → total count=1: 8
        assert 1 in hist
        assert 2 in hist
        assert 3 in hist
        assert hist[3] == 2
        assert hist[2] == 3

    def test_coverage_histogram_sorted_keys(self):
        reps = self.reps
        hits = [(self.bs.bin_label(r), 1) for r in reps[:5]]
        r1 = CoverageResult.from_hits(hits, run_id="s1")
        r2 = CoverageResult.from_hits(hits[:3], run_id="s2")
        er = self.eng.merge_and_expand([r1, r2], track_provenance=True)
        keys = list(er.coverage_histogram().keys())
        assert keys == sorted(keys)

    # ── fragile_orbits ────────────────────────────────────────────────────────

    def test_fragile_orbits_empty_without_provenance(self):
        r  = CoverageResult.from_hits([(self.bs.bin_label(self.reps[0]), 1)])
        er = self.eng.expand(r)
        assert er.fragile_orbits() == []

    def test_fragile_orbits_default_threshold_2(self):
        l0 = self.bs.bin_label(self.reps[0])
        l1 = self.bs.bin_label(self.reps[1])
        r1 = CoverageResult.from_hits([(l0, 1), (l1, 1)], run_id="s1")
        r2 = CoverageResult.from_hits([(l1, 1)], run_id="s2")
        er = self.eng.merge_and_expand([r1, r2], track_provenance=True)
        fragile = er.fragile_orbits()   # threshold=2
        # Orbit 0: 1 run → fragile
        assert self.reps[0] in fragile
        # Orbit 1: 2 runs → NOT fragile at threshold=2
        assert self.reps[1] not in fragile

    def test_fragile_orbits_custom_threshold(self):
        """threshold=3: orbits covered by <3 runs are fragile."""
        reps  = self.reps
        hits0 = [(self.bs.bin_label(reps[0]), 1)]
        hits1 = [(self.bs.bin_label(reps[1]), 1)]
        r1 = CoverageResult.from_hits(hits0 + hits1, run_id="s1")
        r2 = CoverageResult.from_hits(hits1, run_id="s2")
        r3 = CoverageResult.from_hits(hits1, run_id="s3")
        er = self.eng.merge_and_expand([r1, r2, r3], track_provenance=True)
        fragile3 = er.fragile_orbits(threshold=3)
        # Orbit 0: 1 run < 3 → fragile
        assert reps[0] in fragile3
        # Orbit 1: 3 runs == 3 → NOT fragile (< 3 is the condition)
        assert reps[1] not in fragile3

    # ── to_dict / report ──────────────────────────────────────────────────────

    def test_to_dict_no_provenance_key_without_tracking(self):
        r  = CoverageResult.from_hits([(self.bs.bin_label(self.reps[0]), 1)])
        er = self.eng.expand(r)
        assert "provenance" not in er.to_dict()

    def test_to_dict_has_provenance_with_tracking(self):
        r  = CoverageResult.from_hits(
            [(self.bs.bin_label(self.reps[0]), 1)], run_id="s1"
        )
        er = self.eng.expand(r, track_provenance=True)
        d  = er.to_dict()
        assert "provenance" in d
        prov = d["provenance"]
        assert "histogram"     in prov
        assert "fragile_count" in prov
        assert "well_covered"  in prov

    def test_report_confidence_section_with_tracking(self):
        r  = CoverageResult.from_hits(
            [(self.bs.bin_label(r), 1) for r in self.reps[:5]],
            run_id="s1"
        )
        er = self.eng.expand(r, track_provenance=True)
        rep = er.report()
        assert "confidence" in rep.lower() or "Coverage confidence" in rep

    def test_report_no_confidence_without_tracking(self):
        r  = CoverageResult.from_hits(
            [(self.bs.bin_label(r), 1) for r in self.reps[:5]]
        )
        er = self.eng.expand(r)
        rep = er.report()
        assert "confidence" not in rep.lower()


# ═══════════════════════════════════════════════════════════════════════════════
# Symbolic SymbolicExpansionResult provenance
# ═══════════════════════════════════════════════════════════════════════════════

class TestSymbolicProvenance:

    def setup_method(self):
        self.bs   = make_bs(4, 4)   # 35 orbits, Pólya
        self.eng  = SymbolicExpansionEngine(self.bs)
        from dabih.core.symbolic import SymbolicOrbitEngine
        self.reps = SymbolicOrbitEngine(self.bs).representatives()

    def test_no_provenance_by_default(self):
        r  = CoverageResult.from_hits([(self.bs.bin_label(self.reps[0]), 1)])
        er = self.eng.expand(r)
        assert not er.has_provenance

    def test_has_provenance_with_flag(self):
        r  = CoverageResult.from_hits(
            [(self.bs.bin_label(self.reps[0]), 1)], run_id="s1"
        )
        er = self.eng.expand(r, track_provenance=True)
        assert er.has_provenance

    def test_orbit_run_ids_single_run(self):
        l0 = self.bs.bin_label(self.reps[0])
        r  = CoverageResult.from_hits([(l0, 1)], run_id="seed_001")
        er = self.eng.expand(r, track_provenance=True)
        assert er.orbit_run_ids(l0) == ["seed_001"]

    def test_merge_accumulates_run_ids(self):
        l0 = self.bs.bin_label(self.reps[0])
        l1 = self.bs.bin_label(self.reps[1])
        r1 = CoverageResult.from_hits([(l0, 1), (l1, 1)], run_id="s1")
        r2 = CoverageResult.from_hits([(l1, 1)], run_id="s2")
        er = self.eng.merge_and_expand([r1, r2], track_provenance=True)
        assert sorted(er.orbit_run_ids(l1)) == ["s1", "s2"]
        assert er.orbit_run_ids(l0) == ["s1"]

    def test_single_coverage_orbits(self):
        l0 = self.bs.bin_label(self.reps[0])
        l1 = self.bs.bin_label(self.reps[1])
        r1 = CoverageResult.from_hits([(l0, 1), (l1, 1)], run_id="s1")
        r2 = CoverageResult.from_hits([(l1, 1)], run_id="s2")
        er = self.eng.merge_and_expand([r1, r2], track_provenance=True)
        single = er.single_coverage_orbits()
        assert self.reps[0] in single
        assert self.reps[1] not in single

    def test_coverage_histogram(self):
        l0 = self.bs.bin_label(self.reps[0])
        l1 = self.bs.bin_label(self.reps[1])
        l2 = self.bs.bin_label(self.reps[2])
        r1 = CoverageResult.from_hits([(l0,1),(l1,1),(l2,1)], run_id="s1")
        r2 = CoverageResult.from_hits([(l1,1),(l2,1)], run_id="s2")
        r3 = CoverageResult.from_hits([(l2,1)], run_id="s3")
        er = self.eng.merge_and_expand([r1, r2, r3], track_provenance=True)
        hist = er.coverage_histogram()
        assert hist.get(1) == 1   # l0 covered by s1 only
        assert hist.get(2) == 1   # l1 covered by s1+s2
        assert hist.get(3) == 1   # l2 covered by s1+s2+s3

    def test_fragile_orbits(self):
        l0 = self.bs.bin_label(self.reps[0])
        l1 = self.bs.bin_label(self.reps[1])
        r1 = CoverageResult.from_hits([(l0,1),(l1,1)], run_id="s1")
        r2 = CoverageResult.from_hits([(l1,1)], run_id="s2")
        er = self.eng.merge_and_expand([r1, r2], track_provenance=True)
        fragile = er.fragile_orbits()
        assert self.reps[0] in fragile
        assert self.reps[1] not in fragile

    def test_to_dict_has_provenance(self):
        l0 = self.bs.bin_label(self.reps[0])
        r  = CoverageResult.from_hits([(l0, 1)], run_id="s1")
        er = self.eng.expand(r, track_provenance=True)
        d  = er.to_dict()
        assert "provenance" in d

    def test_to_dict_no_provenance_without_flag(self):
        l0 = self.bs.bin_label(self.reps[0])
        r  = CoverageResult.from_hits([(l0, 1)])
        er = self.eng.expand(r)
        assert "provenance" not in er.to_dict()

    def test_report_confidence_section(self):
        l0 = self.bs.bin_label(self.reps[0])
        r  = CoverageResult.from_hits([(l0, 1)], run_id="s1")
        er = self.eng.expand(r, track_provenance=True)
        assert "Coverage confidence" in er.report()

    def test_non_rep_hit_still_tracked(self):
        """A non-representative hit should be attributed correctly."""
        from dabih.core.symbolic import SymbolicOrbitEngine
        eng = SymbolicOrbitEngine(self.bs)
        # Find an orbit with at least 2 members (skip all-same multisets)
        multi_rep = next(
            r for r in self.reps
            if len(eng.orbit_of(r)) > 1
        )
        orbit_members = list(eng.orbit_of(multi_rep))
        non_rep = next(m for m in orbit_members if m != multi_rep)
        non_rep_label = self.bs.bin_label(non_rep)
        r  = CoverageResult.from_hits([(non_rep_label, 1)], run_id="s1")
        er = self.eng.expand(r, track_provenance=True)
        # Should attribute the orbit to s1 via the canonical form
        rep_label = self.bs.bin_label(multi_rep)
        assert er.orbit_run_ids(rep_label) == ["s1"]


# ═══════════════════════════════════════════════════════════════════════════════
# CLI --provenance flag
# ═══════════════════════════════════════════════════════════════════════════════

class TestCLIProvenance:

    def _build_spec_and_results(self, tmp_path, n_runs=3):
        from dabih.cli import main
        spec = tmp_path / "spec.json"
        main(["spec", SERDES, "--param", "N_LANES=4",
              "--cover", "rx_lane", "state", "IDLE", "ACTIVE", "STALL", "ERROR",
              "--module", "rx_lane",
              "--out", str(spec)])

        data = json.loads(spec.read_text())
        reps = data["representatives"]
        n    = len(reps)   # 35

        result_files = []
        slice_size   = n // n_runs
        for i in range(n_runs):
            start = i * slice_size
            end   = start + slice_size if i < n_runs - 1 else n
            hits  = [{"bin": list(r), "count": 1} for r in reps[start:end]]
            rfile = tmp_path / f"run_{i}.json"
            rfile.write_text(json.dumps({
                "run_id": f"seed_{i:04d}",
                "simulator": "questa",
                "covergroup": "rx_cross",
                "hits": hits,
            }))
            result_files.append(str(rfile))
        return spec, result_files

    def test_provenance_flag_adds_confidence_section(self, tmp_path, capsys):
        from dabih.cli import main
        spec, rfiles = self._build_spec_and_results(tmp_path)
        try:
            main(["expand"] + rfiles + [
                "--spec", str(spec),
                "--provenance",
            ])
        except SystemExit:
            pass
        out = capsys.readouterr().out
        assert "Coverage confidence" in out

    def test_no_provenance_flag_omits_confidence(self, tmp_path, capsys):
        from dabih.cli import main
        spec, rfiles = self._build_spec_and_results(tmp_path)
        try:
            main(["expand"] + rfiles + ["--spec", str(spec)])
        except SystemExit:
            pass
        out = capsys.readouterr().out
        assert "Coverage confidence" not in out

    def test_provenance_in_json_output(self, tmp_path, capsys):
        from dabih.cli import main
        spec, rfiles = self._build_spec_and_results(tmp_path)
        try:
            main(["expand"] + rfiles + [
                "--spec", str(spec),
                "--provenance",
                "--json",
            ])
        except SystemExit:
            pass
        capsys.readouterr()   # discard spec build output already captured
        # Re-run cleanly to get just the JSON
        import io, contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            try:
                main(["expand"] + rfiles + [
                    "--spec", str(spec),
                    "--provenance",
                    "--json",
                ])
            except SystemExit:
                pass
        text = buf.getvalue().strip()
        # Find the JSON object in the output
        start = text.find("{")
        data = json.loads(text[start:])
        assert "provenance" in data
        assert "histogram" in data["provenance"]

    def test_single_run_provenance(self, tmp_path, capsys):
        from dabih.cli import main
        spec, rfiles = self._build_spec_and_results(tmp_path, n_runs=1)
        try:
            main(["expand", rfiles[0], "--spec", str(spec), "--provenance"])
        except SystemExit:
            pass
        out = capsys.readouterr().out
        assert "Coverage confidence" in out


# ═══════════════════════════════════════════════════════════════════════════════
# Regression: existing tests unaffected by new parameters
# ═══════════════════════════════════════════════════════════════════════════════

class TestBackwardCompatibility:
    """Verify that all existing callers without track_provenance still work."""

    def test_expand_unchanged_without_flag(self):
        bs   = make_bs(3, 4)
        eng  = ExpansionEngine(bs)
        reps = bs.select_representatives()
        r    = CoverageResult.from_hits([(bs.bin_label(r), 1) for r in reps[:10]])
        er   = eng.expand(r)
        assert er.n_orbits_hit() == 10
        assert not er.has_provenance

    def test_merge_unchanged_without_flag(self):
        bs   = make_bs(3, 4)
        eng  = ExpansionEngine(bs)
        reps = bs.select_representatives()
        r1   = CoverageResult.from_hits([(bs.bin_label(r), 1) for r in reps[:10]])
        r2   = CoverageResult.from_hits([(bs.bin_label(r), 1) for r in reps[10:]])
        er   = eng.merge_and_expand([r1, r2])
        assert er.is_complete()
        assert not er.has_provenance

    def test_symbolic_expand_unchanged(self):
        bs   = make_bs(4, 4)
        eng  = SymbolicExpansionEngine(bs)
        from dabih.core.symbolic import SymbolicOrbitEngine
        reps = SymbolicOrbitEngine(bs).representatives()
        r    = CoverageResult.from_hits([(bs.bin_label(r), 1) for r in reps[:15]])
        er   = eng.expand(r)
        assert er.n_orbits_hit() == 15
        assert not er.has_provenance

    def test_symbolic_merge_unchanged(self):
        bs   = make_bs(4, 4)
        eng  = SymbolicExpansionEngine(bs)
        from dabih.core.symbolic import SymbolicOrbitEngine
        reps = SymbolicOrbitEngine(bs).representatives()
        r1   = CoverageResult.from_hits([(bs.bin_label(r), 1) for r in reps[:18]])
        r2   = CoverageResult.from_hits([(bs.bin_label(r), 1) for r in reps[18:]])
        er   = eng.merge_and_expand([r1, r2])
        assert er.is_complete()
        assert not er.has_provenance


if __name__ == "__main__":
    import pytest as pt
    pt.main([__file__, "-v"])
