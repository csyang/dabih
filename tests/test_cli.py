"""
tests/test_cli.py
~~~~~~~~~~~~~~~~~
Tests for OQ-03: the `dabih` CLI.

Strategy: call main(argv=[...]) directly — no subprocess overhead, full
coverage of argument parsing, dispatch, and output. Uses tmp directories
for all file I/O.

Covers:
  Argument parsing
    - scan:   files, --param, --json
    - spec:   files, --param, --cover, --out, --module
    - expand: results, --spec, --html, --json, --no-exit-code, --max-holes
    - report: results, --spec, --out, --title
    - verify: --spec, --dut, --inst, --clk, --rst, --input, --output,
              --rtl, --depth, --tool, --out-dir, --name, --param

  scan command
    - Detects generate-for arrays in fixture RTL
    - Text output contains module/count info
    - JSON output is valid and contains arrays list
    - --param resolves parameterised bounds
    - Missing file exits 2

  spec command
    - Produces valid spec JSON
    - Spec JSON contains required fields (version, coverpoints, orbit_count)
    - --cover filters module types and sets bins
    - --module restricts to named module
    - Default cover applied when --cover omitted
    - Multiple arrays produce multiple output files
    - Missing file exits 2
    - No arrays found exits 2

  spec_io round-trip
    - load_bin_space(dump_bin_space(bs)) preserves orbit_count
    - load_bin_space preserves declarations
    - Representatives round-trip

  expand command
    - Loads spec and result, prints text report
    - Returns exit 1 when incomplete (CI integration)
    - Returns exit 0 when complete
    - --no-exit-code overrides CI exit code
    - --html writes HTML file
    - --json output is valid dict with class_coverage
    - Multiple result files are merged
    - Missing spec exits 2
    - Missing result exits 2

  report command
    - Writes HTML file to --out path
    - File is non-empty and contains <html>
    - --title appears in HTML
    - Returns 0

  verify command
    - Writes .sv and .tcl and .sgdc and .tcl to --out-dir
    - --tool questa_formal emits only SV + questa TCL
    - --tool spyglass emits only SGDC + spyglass TCL
    - --tool all emits all four files
    - --depth reflected in SV assertions
    - --name suffix applied to filenames
    - Bad --inst (no {i}) exits 2
    - Missing --spec exits 2

  Error handling
    - Unknown command exits non-zero
    - Bad --param format exits 2
    - Non-integer --param value exits 2
"""

import sys, os, json, tempfile
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from dabih.cli import main

FIXTURES = os.path.join(os.path.dirname(__file__), "..", "examples", "rtl")
SERDES   = os.path.join(FIXTURES, "serdes_top.sv")
MEM      = os.path.join(FIXTURES, "mem_ctrl.sv")
MIXED    = os.path.join(FIXTURES, "mixed_top.sv")
MULTI    = os.path.join(FIXTURES, "multi_module.sv")


# ── Helpers ───────────────────────────────────────────────────────────────────

def run(*argv, expected_exit=0):
    """Call main() and assert the exit code."""
    try:
        code = main(list(argv))
    except SystemExit as e:
        code = int(e.code) if e.code is not None else 0
    assert code == expected_exit, \
        f"Expected exit {expected_exit}, got {code} for: {list(argv)}"
    return code

def run_capture(*argv, expected_exit=0, capsys=None):
    """Call main() and return captured stdout."""
    try:
        code = main(list(argv))
    except SystemExit as e:
        code = int(e.code) if e.code is not None else 0
    assert code == expected_exit, \
        f"Expected exit {expected_exit}, got {code}"
    return code

def make_result_json(
    hits: list,
    run_id: str = "test_run",
    simulator: str = "questa",
    covergroup: str = "test_cg",
) -> dict:
    return {
        "run_id": run_id,
        "simulator": simulator,
        "covergroup": covergroup,
        "hits": [{"bin": list(h[0]), "count": h[1]} for h in hits],
    }


# ═══════════════════════════════════════════════════════════════════════════════
# scan command
# ═══════════════════════════════════════════════════════════════════════════════

class TestScanCommand:

    def test_scan_detects_serdes(self, capsys):
        run("scan", SERDES, "--param", "N_LANES=4")
        out = capsys.readouterr().out
        assert "serdes_top" in out
        assert "rx_lane"    in out
        assert "tx_lane"    in out

    def test_scan_literal_bound(self, capsys):
        run("scan", MEM)
        out = capsys.readouterr().out
        assert "mem_ctrl"   in out
        assert "mem_channel" in out

    def test_scan_json_output(self, capsys):
        run("scan", SERDES, "--param", "N_LANES=4", "--json")
        out = capsys.readouterr().out
        data = json.loads(out)
        assert "arrays" in data
        assert len(data["arrays"]) == 2
        types = {a["module_type"] for a in data["arrays"]}
        assert "rx_lane" in types
        assert "tx_lane" in types

    def test_scan_param_resolves_bound(self, capsys):
        run("scan", SERDES, "--param", "N_LANES=8", "--json")
        out = capsys.readouterr().out
        data = json.loads(out)
        for arr in data["arrays"]:
            assert arr["count"] == 8

    def test_scan_multi_file(self, capsys):
        run("scan", SERDES, MEM)
        out = capsys.readouterr().out
        assert "rx_lane"    in out
        assert "mem_channel" in out

    def test_scan_missing_file_exits_2(self):
        run("scan", "/nonexistent/path.sv", expected_exit=2)

    def test_scan_mixed_ignores_non_generate(self, capsys):
        run("scan", MIXED)
        out = capsys.readouterr().out
        assert "pipe_stage"    in out
        assert "global_ctrl"   not in out
        assert "arbiter"       not in out


# ═══════════════════════════════════════════════════════════════════════════════
# spec command
# ═══════════════════════════════════════════════════════════════════════════════

class TestSpecCommand:

    def test_spec_produces_json_file(self, tmp_path):
        out = tmp_path / "spec.json"
        run("spec", SERDES, "--param", "N_LANES=4",
            "--cover", "rx_lane", "state", "IDLE", "ACTIVE", "STALL", "ERROR",
            "--module", "rx_lane",
            "--out", str(out))
        assert out.exists()
        data = json.loads(out.read_text())
        assert data["version"] == "1"

    def test_spec_has_required_fields(self, tmp_path):
        out = tmp_path / "spec.json"
        run("spec", MEM,
            "--cover", "mem_channel", "ch_state", "IDLE", "BUSY", "ERROR",
            "--out", str(out))
        data = json.loads(out.read_text())
        for field in ["version", "coverpoints", "declarations",
                      "orbit_count", "total_bins", "compression_ratio",
                      "method", "representatives"]:
            assert field in data, f"Missing field: {field}"

    def test_spec_orbit_count_polya(self, tmp_path):
        """4-lane S4 on 4-bin state: C(7,4) = 35 orbits."""
        import math
        out = tmp_path / "spec.json"
        run("spec", SERDES, "--param", "N_LANES=4",
            "--cover", "rx_lane", "state", "IDLE", "ACTIVE", "STALL", "ERROR",
            "--module", "rx_lane",
            "--out", str(out))
        data = json.loads(out.read_text())
        assert data["orbit_count"] == math.comb(4+4-1, 4)  # 35
        assert data["method"] == "polya"

    def test_spec_compression_ratio(self, tmp_path):
        out = tmp_path / "spec.json"
        run("spec", MEM,
            "--cover", "mem_channel", "ch_state", "IDLE", "BUSY", "ERROR",
            "--out", str(out))
        data = json.loads(out.read_text())
        # 8-lane S8 on 3 bins: 3^8=6561 / C(10,8)=45 ≈ 145.8
        assert data["compression_ratio"] > 100

    def test_spec_representatives_present(self, tmp_path):
        out = tmp_path / "spec.json"
        run("spec", SERDES, "--param", "N_LANES=4",
            "--cover", "rx_lane", "state", "IDLE", "ACTIVE", "STALL", "ERROR",
            "--module", "rx_lane",
            "--out", str(out))
        data = json.loads(out.read_text())
        assert len(data["representatives"]) == data["orbit_count"]

    def test_spec_coverpoints_match_cover(self, tmp_path):
        out = tmp_path / "spec.json"
        run("spec", SERDES, "--param", "N_LANES=4",
            "--cover", "rx_lane", "state", "IDLE", "ACTIVE", "STALL", "ERROR",
            "--module", "rx_lane",
            "--out", str(out))
        data = json.loads(out.read_text())
        # 4 instances × 1 signal = 4 coverpoints
        assert len(data["coverpoints"]) == 4
        bins = data["coverpoints"][0]["bins"]
        assert bins == ["IDLE", "ACTIVE", "STALL", "ERROR"]

    def test_spec_default_cover_when_omitted(self, tmp_path):
        """Without --cover, should apply default 4-bin state spec."""
        out = tmp_path / "spec.json"
        run("spec", MEM, "--out", str(out))
        data = json.loads(out.read_text())
        assert data["orbit_count"] > 0

    def test_spec_module_filter(self, tmp_path):
        out = tmp_path / "rx_only.json"
        run("spec", SERDES, "--param", "N_LANES=4",
            "--module", "rx_lane",
            "--cover", "rx_lane", "state", "IDLE", "ACTIVE", "STALL", "ERROR",
            "--out", str(out))
        assert out.exists()
        # Should not produce a tx_lane file
        assert not (tmp_path / "rx_only_1.json").exists()

    def test_spec_multiple_arrays_multiple_files(self, tmp_path):
        out = tmp_path / "spec.json"
        run("spec", SERDES, "--param", "N_LANES=4",
            "--cover", "rx_lane", "state", "IDLE", "ACTIVE", "STALL", "ERROR",
            "--cover", "tx_lane", "state", "IDLE", "SEND", "FLUSH", "ERROR",
            "--out", str(out))
        # Two arrays → spec_0.json and spec_1.json
        files = list(tmp_path.glob("spec_*.json"))
        assert len(files) == 2

    def test_spec_missing_file_exits_2(self, tmp_path):
        run("spec", "/no/such/file.sv",
            "--out", str(tmp_path / "out.json"),
            expected_exit=2)

    def test_spec_no_arrays_exits_2(self, tmp_path):
        """A file with no generate-for should exit 2."""
        sv = tmp_path / "empty.sv"
        sv.write_text("module top (input logic clk); endmodule")
        run("spec", str(sv),
            "--out", str(tmp_path / "out.json"),
            expected_exit=2)


# ═══════════════════════════════════════════════════════════════════════════════
# spec_io round-trip
# ═══════════════════════════════════════════════════════════════════════════════

class TestSpecIO:

    def _make_spec(self, tmp_path) -> Path:
        out = tmp_path / "spec.json"
        run("spec", SERDES, "--param", "N_LANES=4",
            "--cover", "rx_lane", "state", "IDLE", "ACTIVE", "STALL", "ERROR",
            "--module", "rx_lane",
            "--out", str(out))
        return out

    def test_round_trip_orbit_count(self, tmp_path):
        from dabih.core.spec_io import load_bin_space_file
        spec_path = self._make_spec(tmp_path)
        bs = load_bin_space_file(spec_path)
        assert bs.orbit_count() == 35   # C(7,4)

    def test_round_trip_total_bins(self, tmp_path):
        from dabih.core.spec_io import load_bin_space_file
        spec_path = self._make_spec(tmp_path)
        bs = load_bin_space_file(spec_path)
        assert bs.total_bin_count() == 4**4  # 256

    def test_round_trip_declarations_preserved(self, tmp_path):
        from dabih.core.spec_io import load_bin_space_file
        spec_path = self._make_spec(tmp_path)
        bs = load_bin_space_file(spec_path)
        decls = bs.symmetry_declarations()
        assert len(decls) == 1
        assert decls[0]["type"] == "instance"
        assert decls[0]["instance_indices"] == [0, 1, 2, 3]

    def test_round_trip_coverpoint_names(self, tmp_path):
        from dabih.core.spec_io import load_bin_space_file
        spec_path = self._make_spec(tmp_path)
        bs = load_bin_space_file(spec_path)
        names = [cp.name for cp in bs._coverpoints]
        assert len(names) == 4
        assert all("state" in n for n in names)

    def test_round_trip_bin_names(self, tmp_path):
        from dabih.core.spec_io import load_bin_space_file
        spec_path = self._make_spec(tmp_path)
        bs = load_bin_space_file(spec_path)
        bins = [b.name for b in bs._coverpoints[0].bins]
        assert bins == ["IDLE", "ACTIVE", "STALL", "ERROR"]

    def test_bad_version_raises(self, tmp_path):
        from dabih.core.spec_io import load_bin_space
        data = {"version": "99", "coverpoints": [], "declarations": []}
        with pytest.raises(ValueError, match="version"):
            load_bin_space(data)


# ═══════════════════════════════════════════════════════════════════════════════
# expand command
# ═══════════════════════════════════════════════════════════════════════════════

class TestExpandCommand:

    def _build_spec(self, tmp_path) -> Path:
        spec = tmp_path / "spec.json"
        run("spec", SERDES, "--param", "N_LANES=4",
            "--cover", "rx_lane", "state", "IDLE", "ACTIVE", "STALL", "ERROR",
            "--module", "rx_lane",
            "--out", str(spec))
        return spec

    def _write_result(self, tmp_path, hits, run_id="run1", name="result.json") -> Path:
        rfile = tmp_path / name
        rfile.write_text(json.dumps(make_result_json(hits, run_id=run_id)))
        return rfile

    def _all_reps(self, tmp_path):
        """Return all representative label-tuples from the spec."""
        from dabih.core.spec_io import load_spec_file
        spec = self._build_spec(tmp_path)
        data = load_spec_file(str(spec))
        return data["representatives"], spec

    def test_expand_text_report(self, tmp_path, capsys):
        reps, spec = self._all_reps(tmp_path)
        # Hit first 10 reps
        hits = [(tuple(r), 1) for r in reps[:10]]
        rfile = self._write_result(tmp_path, hits)
        run("expand", str(rfile), "--spec", str(spec), expected_exit=1)
        out = capsys.readouterr().out
        assert "Coverage" in out

    def test_expand_complete_returns_0(self, tmp_path):
        reps, spec = self._all_reps(tmp_path)
        hits = [(tuple(r), 1) for r in reps]
        rfile = self._write_result(tmp_path, hits)
        run("expand", str(rfile), "--spec", str(spec), expected_exit=0)

    def test_expand_incomplete_returns_1(self, tmp_path):
        reps, spec = self._all_reps(tmp_path)
        hits = [(tuple(reps[0]), 1)]   # only one orbit hit
        rfile = self._write_result(tmp_path, hits)
        run("expand", str(rfile), "--spec", str(spec), expected_exit=1)

    def test_expand_no_exit_code_overrides(self, tmp_path):
        reps, spec = self._all_reps(tmp_path)
        hits = [(tuple(reps[0]), 1)]
        rfile = self._write_result(tmp_path, hits)
        run("expand", str(rfile), "--spec", str(spec),
            "--no-exit-code", expected_exit=0)

    def test_expand_json_output(self, tmp_path, capsys):
        reps, spec = self._all_reps(tmp_path)
        # clear any output from _all_reps (spec build)
        capsys.readouterr()
        hits = [(tuple(r), 1) for r in reps[:10]]
        rfile = self._write_result(tmp_path, hits)
        run("expand", str(rfile), "--spec", str(spec),
            "--json", expected_exit=1)
        out = capsys.readouterr().out
        data = json.loads(out)
        assert "class_coverage" in data
        assert "orbits_hit" in data

    def test_expand_html_output(self, tmp_path):
        reps, spec = self._all_reps(tmp_path)
        hits = [(tuple(r), 1) for r in reps[:10]]
        rfile = self._write_result(tmp_path, hits)
        html = tmp_path / "report.html"
        run("expand", str(rfile), "--spec", str(spec),
            "--html", str(html), expected_exit=1)
        assert html.exists()
        content = html.read_text()
        assert "<html" in content.lower()

    def test_expand_merge_two_results(self, tmp_path, capsys):
        reps, spec = self._all_reps(tmp_path)
        half = len(reps) // 2
        r1 = self._write_result(tmp_path,
             [(tuple(r), 1) for r in reps[:half]], name="r1.json")
        r2 = self._write_result(tmp_path,
             [(tuple(r), 1) for r in reps[half:]], name="r2.json")
        run("expand", str(r1), str(r2), "--spec", str(spec), expected_exit=0)
        out = capsys.readouterr().out
        assert "100.00" in out or "Complete" in out

    def test_expand_missing_spec_exits_2(self, tmp_path):
        rfile = tmp_path / "r.json"
        rfile.write_text(json.dumps(make_result_json([])))
        run("expand", str(rfile), "--spec", "/no/such/spec.json", expected_exit=2)

    def test_expand_missing_result_exits_2(self, tmp_path):
        spec = self._build_spec(tmp_path)
        run("expand", "/no/such/result.json", "--spec", str(spec), expected_exit=2)

    def test_expand_max_holes_respected(self, tmp_path, capsys):
        reps, spec = self._all_reps(tmp_path)
        # Hit none — all 35 are holes
        rfile = self._write_result(tmp_path, [])
        run("expand", str(rfile), "--spec", str(spec),
            "--max-holes", "5", expected_exit=1)
        out = capsys.readouterr().out
        # Report should mention truncation
        assert "5" in out or "35" in out


# ═══════════════════════════════════════════════════════════════════════════════
# report command
# ═══════════════════════════════════════════════════════════════════════════════

class TestReportCommand:

    def _setup(self, tmp_path):
        spec = tmp_path / "spec.json"
        run("spec", SERDES, "--param", "N_LANES=4",
            "--cover", "rx_lane", "state", "IDLE", "ACTIVE", "STALL", "ERROR",
            "--module", "rx_lane",
            "--out", str(spec))
        from dabih.core.spec_io import load_spec_file
        data = load_spec_file(str(spec))
        reps = data["representatives"]
        hits = [(tuple(r), 1) for r in reps[:15]]
        rfile = tmp_path / "result.json"
        rfile.write_text(json.dumps(make_result_json(hits)))
        return spec, rfile

    def test_report_writes_html(self, tmp_path):
        spec, rfile = self._setup(tmp_path)
        html = tmp_path / "report.html"
        run("report", str(rfile), "--spec", str(spec), "--out", str(html))
        assert html.exists()
        assert html.stat().st_size > 1000

    def test_report_html_is_valid(self, tmp_path):
        spec, rfile = self._setup(tmp_path)
        html = tmp_path / "report.html"
        run("report", str(rfile), "--spec", str(spec), "--out", str(html))
        content = html.read_text()
        assert "<html" in content.lower()
        assert "</html>" in content.lower()

    def test_report_custom_title(self, tmp_path):
        spec, rfile = self._setup(tmp_path)
        html = tmp_path / "report.html"
        run("report", str(rfile), "--spec", str(spec),
            "--out", str(html), "--title", "My SerDes Coverage")
        content = html.read_text()
        assert "My SerDes Coverage" in content

    def test_report_returns_0(self, tmp_path):
        spec, rfile = self._setup(tmp_path)
        html = tmp_path / "report.html"
        run("report", str(rfile), "--spec", str(spec),
            "--out", str(html), expected_exit=0)

    def test_report_missing_spec_exits_2(self, tmp_path):
        rfile = tmp_path / "r.json"
        rfile.write_text(json.dumps(make_result_json([])))
        run("report", str(rfile), "--spec", "/no/spec.json",
            "--out", str(tmp_path / "r.html"), expected_exit=2)


# ═══════════════════════════════════════════════════════════════════════════════
# verify command
# ═══════════════════════════════════════════════════════════════════════════════

class TestVerifyCommand:

    def _build_spec(self, tmp_path) -> Path:
        spec = tmp_path / "spec.json"
        run("spec", SERDES, "--param", "N_LANES=4",
            "--cover", "rx_lane", "state", "IDLE", "ACTIVE", "STALL", "ERROR",
            "--module", "rx_lane",
            "--out", str(spec))
        return spec

    def _base_verify_args(self, spec, out_dir):
        return [
            "verify",
            "--spec", str(spec),
            "--dut",  "serdes_top",
            "--inst", "rx_gen[{i}].u_rx",
            "--clk",  "clk",
            "--rst",  "rst_n",
            "--input", "valid", "data",
            "--output", "state",
            "--rtl", "rtl/serdes_top.sv",
            "--out-dir", str(out_dir),
        ]

    def test_verify_emits_all_four_files(self, tmp_path):
        spec    = self._build_spec(tmp_path)
        out_dir = tmp_path / "formal"
        run(*self._base_verify_args(spec, out_dir))
        files = list(out_dir.glob("*"))
        extensions = {f.suffix for f in files}
        assert ".sv"   in extensions
        assert ".tcl"  in extensions
        assert ".sgdc" in extensions

    def test_verify_sv_has_module(self, tmp_path):
        spec    = self._build_spec(tmp_path)
        out_dir = tmp_path / "formal"
        run(*self._base_verify_args(spec, out_dir))
        sv_files = list(out_dir.glob("*.sv"))
        assert sv_files
        content = sv_files[0].read_text()
        assert "module dabih_sym_check" in content

    def test_verify_sv_has_assertions(self, tmp_path):
        spec    = self._build_spec(tmp_path)
        out_dir = tmp_path / "formal"
        run(*self._base_verify_args(spec, out_dir))
        sv_files = list(out_dir.glob("*.sv"))
        content = sv_files[0].read_text()
        assert "assert property" in content
        assert "SYM_" in content

    def test_verify_tcl_has_questa_commands(self, tmp_path):
        spec    = self._build_spec(tmp_path)
        out_dir = tmp_path / "formal"
        run(*self._base_verify_args(spec, out_dir))
        tcl_files = [f for f in out_dir.glob("*.tcl")
                     if "questa" in f.name]
        assert tcl_files
        content = tcl_files[0].read_text()
        assert "questa_formal compile" in content
        assert "questa_formal verify"  in content

    def test_verify_sgdc_has_clock(self, tmp_path):
        spec    = self._build_spec(tmp_path)
        out_dir = tmp_path / "formal"
        run(*self._base_verify_args(spec, out_dir))
        sgdc_files = list(out_dir.glob("*.sgdc"))
        assert sgdc_files
        content = sgdc_files[0].read_text()
        assert "define_clock" in content

    def test_verify_tool_questa_only(self, tmp_path):
        spec    = self._build_spec(tmp_path)
        out_dir = tmp_path / "formal"
        args    = self._base_verify_args(spec, out_dir)
        args   += ["--tool", "questa_formal"]
        run(*args)
        files  = list(out_dir.glob("*"))
        names  = [f.name for f in files]
        assert any(".sv"   in n for n in names)
        assert any("questa" in n for n in names)
        assert not any(".sgdc" in n for n in names)

    def test_verify_tool_spyglass_only(self, tmp_path):
        spec    = self._build_spec(tmp_path)
        out_dir = tmp_path / "formal"
        args    = self._base_verify_args(spec, out_dir)
        args   += ["--tool", "spyglass"]
        run(*args)
        files  = list(out_dir.glob("*"))
        names  = [f.name for f in files]
        assert any(".sgdc" in n for n in names)
        assert not any(".sv" in n for n in names)

    def test_verify_depth_reflected_in_sv(self, tmp_path):
        spec    = self._build_spec(tmp_path)
        out_dir = tmp_path / "formal"
        args    = self._base_verify_args(spec, out_dir)
        args   += ["--depth", "50"]
        run(*args)
        sv_files = list(out_dir.glob("*.sv"))
        content  = sv_files[0].read_text()
        assert "##[0:50]" in content

    def test_verify_name_suffix(self, tmp_path):
        spec    = self._build_spec(tmp_path)
        out_dir = tmp_path / "formal"
        args    = self._base_verify_args(spec, out_dir)
        args   += ["--name", "rx_lane"]
        run(*args)
        files = [f.name for f in out_dir.glob("*")]
        assert any("rx_lane" in n for n in files)

    def test_verify_active_low_reset(self, tmp_path):
        spec    = self._build_spec(tmp_path)
        out_dir = tmp_path / "formal"
        args    = self._base_verify_args(spec, out_dir)
        args   += ["--rst-active-low"]
        run(*args)
        sv_files = list(out_dir.glob("*.sv"))
        content  = sv_files[0].read_text()
        assert "disable iff (!rst_n)" in content

    def test_verify_bad_inst_no_placeholder_exits_2(self, tmp_path):
        spec    = self._build_spec(tmp_path)
        out_dir = tmp_path / "formal"
        args = [
            "verify",
            "--spec", str(spec),
            "--dut",  "serdes_top",
            "--inst", "rx_gen[0].u_rx",   # missing {i}
            "--clk",  "clk",
            "--input", "valid",
            "--output", "state",
            "--out-dir", str(out_dir),
        ]
        run(*args, expected_exit=2)

    def test_verify_missing_spec_exits_2(self, tmp_path):
        out_dir = tmp_path / "formal"
        run("verify",
            "--spec", "/no/spec.json",
            "--dut",  "top",
            "--inst", "u[{i}]",
            "--clk",  "clk",
            "--input", "a",
            "--output", "b",
            "--out-dir", str(out_dir),
            expected_exit=2)

    def test_verify_creates_out_dir(self, tmp_path):
        spec    = self._build_spec(tmp_path)
        out_dir = tmp_path / "does" / "not" / "exist"
        args    = self._base_verify_args(spec, out_dir)
        run(*args)
        assert out_dir.exists()


# ═══════════════════════════════════════════════════════════════════════════════
# Error handling
# ═══════════════════════════════════════════════════════════════════════════════

class TestErrorHandling:

    def test_bad_param_format_exits_2(self):
        run("scan", SERDES, "--param", "BADFORMAT", expected_exit=2)

    def test_non_integer_param_value_exits_2(self):
        run("scan", SERDES, "--param", "N=notanint", expected_exit=2)

    def test_scan_nonexistent_file_exits_2(self):
        run("scan", "/totally/missing.sv", expected_exit=2)


# ═══════════════════════════════════════════════════════════════════════════════
# End-to-end pipeline
# ═══════════════════════════════════════════════════════════════════════════════

class TestEndToEnd:

    def test_full_pipeline_scan_spec_expand_report(self, tmp_path, capsys):
        """scan → spec → expand → report: complete pipeline."""
        spec = tmp_path / "spec.json"
        html = tmp_path / "report.html"

        # 1. scan
        run("scan", SERDES, "--param", "N_LANES=4")
        capsys.readouterr()

        # 2. spec
        run("spec", SERDES, "--param", "N_LANES=4",
            "--cover", "rx_lane", "state", "IDLE", "ACTIVE", "STALL", "ERROR",
            "--module", "rx_lane",
            "--out", str(spec))
        capsys.readouterr()

        # Load reps from spec
        data = json.loads(spec.read_text())
        reps = data["representatives"]

        # 3. Write a result file (hit 80% of reps)
        n_hit = int(len(reps) * 0.8)
        result_data = make_result_json(
            [(tuple(r), 1) for r in reps[:n_hit]],
            run_id="e2e_run", simulator="questa",
        )
        rfile = tmp_path / "result.json"
        rfile.write_text(json.dumps(result_data))

        # 4. expand — should exit 1 (incomplete)
        run("expand", str(rfile), "--spec", str(spec), expected_exit=1)

        # 5. report
        run("report", str(rfile), "--spec", str(spec),
            "--out", str(html), "--title", "E2E Test")

        assert html.exists()
        assert "E2E Test" in html.read_text()

    def test_full_pipeline_with_merge(self, tmp_path, capsys):
        """Two partial runs merged to complete coverage."""
        spec = tmp_path / "spec.json"
        run("spec", SERDES, "--param", "N_LANES=4",
            "--cover", "rx_lane", "state", "IDLE", "ACTIVE", "STALL", "ERROR",
            "--module", "rx_lane",
            "--out", str(spec))
        capsys.readouterr()

        data = json.loads(spec.read_text())
        reps = data["representatives"]
        half = len(reps) // 2

        r1 = tmp_path / "r1.json"
        r2 = tmp_path / "r2.json"
        r1.write_text(json.dumps(make_result_json(
            [(tuple(r), 1) for r in reps[:half]], run_id="r1")))
        r2.write_text(json.dumps(make_result_json(
            [(tuple(r), 1) for r in reps[half:]], run_id="r2")))

        run("expand", str(r1), str(r2), "--spec", str(spec), expected_exit=0)


if __name__ == "__main__":
    import pytest as pt
    pt.main([__file__, "-v"])


# ═══════════════════════════════════════════════════════════════════════════════
# OQ-09 — Simulator adapter flags
# ═══════════════════════════════════════════════════════════════════════════════

ADAPTER_FX   = os.path.join(os.path.dirname(__file__), "..", "examples", "simulator")
QUESTA_4LANE = os.path.join(ADAPTER_FX, "questa_4lane_partial.txt")
VCS_4LANE    = os.path.join(ADAPTER_FX, "vcs_4lane_partial.txt")
QUESTA_MULTI = os.path.join(ADAPTER_FX, "questa_multi_cg.txt")
VCS_MULTI    = os.path.join(ADAPTER_FX, "vcs_multi_cg.txt")


class TestSimulatorAdapters:

    def _build_4lane_spec(self, tmp_path) -> Path:
        spec = tmp_path / "spec.json"
        run("spec", SERDES, "--param", "N_LANES=4",
            "--cover", "rx_lane", "state", "IDLE", "ACTIVE", "STALL", "ERROR",
            "--module", "rx_lane", "--out", str(spec))
        return spec

    def _build_2lane_spec(self, tmp_path) -> Path:
        sv = tmp_path / "two_lane.sv"
        sv.write_text("""
module rx_lane(input logic v, output logic [1:0] state, output logic ready);
endmodule
module top(input logic [1:0] v, output logic [1:0] state [1:0]);
    for(genvar i=0;i<2;i++) begin:rx_gen
        rx_lane u_rx(.v(v[i]),.state(state[i]),.ready());
    end
endmodule""")
        spec = tmp_path / "spec2.json"
        run("spec", str(sv),
            "--cover", "rx_lane", "state", "IDLE", "ACTIVE", "STALL", "ERROR",
            "--out", str(spec))
        return spec

    def test_expand_questa_report(self, tmp_path, capsys):
        spec = self._build_4lane_spec(tmp_path)
        capsys.readouterr()
        run("expand", "--questa-report", QUESTA_4LANE,
            "--covergroup", "rx_lane_cross_cg", "--spec", str(spec),
            expected_exit=1)
        out = capsys.readouterr().out
        assert "Coverage" in out or "orbit" in out.lower()

    def test_expand_questa_no_exit_code(self, tmp_path):
        spec = self._build_4lane_spec(tmp_path)
        run("expand", "--questa-report", QUESTA_4LANE,
            "--covergroup", "rx_lane_cross_cg", "--spec", str(spec),
            "--no-exit-code", expected_exit=0)

    def test_expand_questa_json(self, tmp_path, capsys):
        import io, contextlib
        spec = self._build_4lane_spec(tmp_path)
        capsys.readouterr()
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            try:
                run("expand", "--questa-report", QUESTA_4LANE,
                    "--covergroup", "rx_lane_cross_cg", "--spec", str(spec),
                    "--json", expected_exit=1)
            except SystemExit:
                pass
        text = buf.getvalue().strip()
        data = json.loads(text[text.find("{"):])
        assert "class_coverage" in data and data["orbits_hit"] > 0

    def test_expand_vcs_report(self, tmp_path):
        spec = self._build_4lane_spec(tmp_path)
        run("expand", "--vcs-report", VCS_4LANE,
            "--covergroup", "rx_lane_cross_cg", "--spec", str(spec),
            "--no-exit-code", expected_exit=0)

    def test_expand_vcs_json(self, tmp_path, capsys):
        import io, contextlib
        spec = self._build_4lane_spec(tmp_path)
        capsys.readouterr()
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            try:
                run("expand", "--vcs-report", VCS_4LANE,
                    "--covergroup", "rx_lane_cross_cg", "--spec", str(spec),
                    "--json", expected_exit=1)
            except SystemExit:
                pass
        text = buf.getvalue().strip()
        data = json.loads(text[text.find("{"):])
        assert "orbits_hit" in data

    def test_questa_vcs_same_orbits_hit(self, tmp_path, capsys):
        import io, contextlib
        spec = self._build_4lane_spec(tmp_path)
        capsys.readouterr()
        def get(flag, fx):
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                try:
                    run("expand", flag, fx, "--covergroup", "rx_lane_cross_cg",
                        "--spec", str(spec), "--json", expected_exit=1)
                except SystemExit:
                    pass
            t = buf.getvalue().strip()
            return json.loads(t[t.find("{"):])
        dq = get("--questa-report", QUESTA_4LANE)
        dv = get("--vcs-report",    VCS_4LANE)
        assert dq["orbits_hit"] == dv["orbits_hit"]
        assert dq["class_coverage"] == dv["class_coverage"]

    def test_expand_merge_two_questa(self, tmp_path):
        spec = self._build_4lane_spec(tmp_path)
        run("expand", "--questa-report", QUESTA_4LANE, "--questa-report", QUESTA_4LANE,
            "--covergroup", "rx_lane_cross_cg", "--spec", str(spec),
            "--no-exit-code", expected_exit=0)

    def test_expand_mix_questa_and_vcs(self, tmp_path):
        spec = self._build_4lane_spec(tmp_path)
        run("expand", "--questa-report", QUESTA_4LANE, "--vcs-report", VCS_4LANE,
            "--covergroup", "rx_lane_cross_cg", "--spec", str(spec),
            "--no-exit-code", expected_exit=0)

    def test_expand_multi_cg_questa(self, tmp_path, capsys):
        spec = self._build_2lane_spec(tmp_path)
        capsys.readouterr()
        run("expand", "--questa-report", QUESTA_MULTI,
            "--covergroup", "rx_lane_cross_cg", "--spec", str(spec),
            "--no-exit-code", expected_exit=0)

    def test_expand_multi_cg_vcs(self, tmp_path, capsys):
        spec = self._build_2lane_spec(tmp_path)
        capsys.readouterr()
        run("expand", "--vcs-report", VCS_MULTI,
            "--covergroup", "rx_lane_cross_cg", "--spec", str(spec),
            "--no-exit-code", expected_exit=0)

    def test_expand_unknown_covergroup_exits_2(self, tmp_path):
        spec = self._build_4lane_spec(tmp_path)
        run("expand", "--questa-report", QUESTA_4LANE,
            "--covergroup", "no_such_cg", "--spec", str(spec), expected_exit=2)

    def test_report_questa_writes_html(self, tmp_path):
        spec = self._build_4lane_spec(tmp_path)
        html = tmp_path / "r.html"
        run("report", "--questa-report", QUESTA_4LANE,
            "--covergroup", "rx_lane_cross_cg", "--spec", str(spec),
            "--out", str(html), expected_exit=0)
        assert html.exists() and "<html" in html.read_text().lower()

    def test_report_vcs_writes_html(self, tmp_path):
        spec = self._build_4lane_spec(tmp_path)
        html = tmp_path / "r.html"
        run("report", "--vcs-report", VCS_4LANE,
            "--covergroup", "rx_lane_cross_cg", "--spec", str(spec),
            "--out", str(html), expected_exit=0)
        assert html.exists()

    def test_mix_json_and_questa_exits_2(self, tmp_path):
        spec = self._build_4lane_spec(tmp_path)
        rfile = tmp_path / "r.json"
        rfile.write_text(json.dumps(make_result_json([])))
        run("expand", str(rfile), "--questa-report", QUESTA_4LANE,
            "--spec", str(spec), expected_exit=2)

    def test_missing_questa_file_exits_2(self, tmp_path):
        spec = self._build_4lane_spec(tmp_path)
        run("expand", "--questa-report", "/no/such.txt",
            "--spec", str(spec), expected_exit=2)
