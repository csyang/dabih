"""
dabih.cli
~~~~~~~~~
Command-line interface for Dabih.

Entry point: `dabih` (registered in pyproject.toml)

Commands
--------
  dabih scan    <files...>             Idea A: RTL extraction report
  dabih spec    <files...>             Idea A+B: emit compressed coverage spec
  dabih expand  <result.json>          Idea C: expand simulation results
  dabih report  <result.json>          Idea C + Visual: generate HTML report
  dabih verify  --spec <spec.json>     Idea D: emit formal verification artifacts

Exit codes
----------
  0  Success / coverage complete
  1  Coverage incomplete (for CI integration on dabih expand)
  2  Input error (bad arguments, missing files, parse failures)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


# ── Colour helpers (no external deps) ────────────────────────────────────────

def _c(text: str, code: str) -> str:
    """ANSI colour — degrades gracefully in non-TTY environments."""
    if not sys.stdout.isatty():
        return text
    return f"\033[{code}m{text}\033[0m"

def green(t):  return _c(t, "32")
def yellow(t): return _c(t, "33")
def red(t):    return _c(t, "31")
def bold(t):   return _c(t, "1")
def dim(t):    return _c(t, "2")


# ── Argument parsing ──────────────────────────────────────────────────────────

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="dabih",
        description="Coverage Model Compression via Equivalence Classes",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  dabih scan    examples/rtl/serdes_top.sv --param N_LANES=8
  dabih spec    examples/rtl/serdes_top.sv --param N_LANES=4 \\
                --cover rx_lane state IDLE ACTIVE STALL ERROR \\
                --out spec.json
  dabih expand  examples/results/seed_0042.json --spec spec.json
  dabih expand  examples/results/*.json --spec spec.json --provenance --html report.html
  dabih report  examples/results/seed_0042.json --spec spec.json --out report.html
  dabih verify  --spec spec.json  --dut serdes_top \\
                --inst "rx_gen[{i}].u_rx" --clk clk --rst rst_n \\
                --input valid data --output state ready \\
                --rtl examples/rtl/serdes_top.sv --out-dir formal/
""",
    )

    sub = parser.add_subparsers(dest="command", metavar="COMMAND")
    sub.required = True

    # ── scan ──────────────────────────────────────────────────────────────────
    p_scan = sub.add_parser(
        "scan",
        help="Parse RTL and report detected generate-for arrays",
        description="Idea A — RTL extraction report. Scans SystemVerilog source "
                    "files for generate-for loops, resolves instance counts, and "
                    "prints an extraction summary.",
    )
    p_scan.add_argument(
        "files", nargs="+", metavar="FILE",
        help="SystemVerilog source files to scan",
    )
    p_scan.add_argument(
        "--param", "-p", action="append", metavar="NAME=VALUE", default=[],
        help="Parameter override, e.g. --param N_LANES=8 (may be repeated)",
    )
    p_scan.add_argument(
        "--json", action="store_true",
        help="Output results as JSON instead of formatted text",
    )

    # ── spec ──────────────────────────────────────────────────────────────────
    p_spec = sub.add_parser(
        "spec",
        help="Build and save a compressed coverage spec",
        description="Ideas A+B — Emit a compressed coverage spec JSON. Extracts "
                    "symmetry from RTL, partitions bins into equivalence classes, "
                    "and writes a spec file for use with 'dabih expand'.",
    )
    p_spec.add_argument(
        "files", nargs="+", metavar="FILE",
        help="SystemVerilog source files to process",
    )
    p_spec.add_argument(
        "--param", "-p", action="append", metavar="NAME=VALUE", default=[],
        help="Parameter override, e.g. --param N_LANES=8",
    )
    p_spec.add_argument(
        "--cover", "-c", action="append", nargs="+", metavar="",
        help="Coverage spec: MODULE SIGNAL BIN [BIN ...], e.g. "
             "--cover rx_lane state IDLE ACTIVE STALL ERROR",
    )
    p_spec.add_argument(
        "--out", "-o", required=True, metavar="FILE",
        help="Output spec JSON file path",
    )
    p_spec.add_argument(
        "--module", "-m", action="append", default=[], metavar="MODULE",
        help="Restrict extraction to named module type(s) (may be repeated)",
    )

    # ── expand ────────────────────────────────────────────────────────────────
    p_exp = sub.add_parser(
        "expand",
        help="Expand simulation coverage results using a spec",
        description="Idea C — Expand one or more simulation coverage results "
                    "using the orbit partition from a spec file. Prints a coverage "
                    "report and optionally writes an HTML sign-off report. "
                    "Exit code 1 when coverage is incomplete (for CI use).",
    )
    p_exp.add_argument(
        "results", nargs="*", metavar="RESULT",
        help="Coverage result JSON file(s). Multiple files are merged. "
             "Omit when using --questa-report or --vcs-report.",
    )
    p_exp.add_argument(
        "--spec", "-s", required=True, metavar="SPEC",
        help="Spec JSON file produced by 'dabih spec'",
    )
    p_exp.add_argument(
        "--html", metavar="FILE",
        help="Write an HTML coverage report to FILE",
    )
    p_exp.add_argument(
        "--json", action="store_true",
        help="Output expansion results as JSON",
    )
    p_exp.add_argument(
        "--no-exit-code", action="store_true",
        help="Always exit 0 (suppress CI exit-code-1 on incomplete coverage)",
    )
    p_exp.add_argument(
        "--max-holes", type=int, default=20, metavar="N",
        help="Maximum holes to show in text report (default: 20)",
    )
    p_exp.add_argument(
        "--provenance", action="store_true",
        help="Track which run_id covered each orbit (merge only). "
             "Adds coverage confidence histogram and fragile orbit list.",
    )
    p_exp.add_argument(
        "--questa-report", action="append", default=None,
        metavar="FILE", dest="questa_reports",
        help="Questa 'vcover report -details' text file (may repeat for merge)",
    )
    p_exp.add_argument(
        "--vcs-report", action="append", default=None,
        metavar="FILE", dest="vcs_reports",
        help="VCS 'urg -format text' coverage.txt file (may repeat for merge)",
    )
    p_exp.add_argument(
        "--covergroup", metavar="NAME", default=None,
        help="Covergroup name to extract (required for multi-cg reports)",
    )

    # ── report ────────────────────────────────────────────────────────────────
    p_rep = sub.add_parser(
        "report",
        help="Generate an HTML coverage sign-off report",
        description="Idea C + Visual — Generate a self-contained HTML coverage "
                    "report from one or more simulation results. Equivalent to "
                    "'dabih expand --html FILE' but focused on report output.",
    )
    p_rep.add_argument(
        "results", nargs="*", metavar="RESULT",
        help="Coverage result JSON file(s). Multiple files are merged. "
             "Omit when using --questa-report or --vcs-report.",
    )
    p_rep.add_argument(
        "--spec", "-s", required=True, metavar="SPEC",
        help="Spec JSON file produced by 'dabih spec'",
    )
    p_rep.add_argument(
        "--out", "-o", required=True, metavar="FILE",
        help="Output HTML report file path",
    )
    p_rep.add_argument(
        "--title", "-t", default="", metavar="TITLE",
        help="Report title (default: derived from spec name)",
    )
    p_rep.add_argument("--provenance", action="store_true",
        help="Track provenance when merging multiple runs.")
    p_rep.add_argument("--questa-report", action="append", default=None,
        metavar="FILE", dest="questa_reports")
    p_rep.add_argument("--vcs-report", action="append", default=None,
        metavar="FILE", dest="vcs_reports")
    p_rep.add_argument("--covergroup", metavar="NAME", default=None)

    # ── verify ────────────────────────────────────────────────────────────────
    p_ver = sub.add_parser(
        "verify",
        help="Emit formal symmetry verification artifacts",
        description="Idea D — Emit SpyGlass constraints (Tier 1) and Questa Formal "
                    "SVA properties (Tier 2) from a spec file and DUT port spec.",
    )
    p_ver.add_argument(
        "--spec", "-s", required=True, metavar="SPEC",
        help="Spec JSON file produced by 'dabih spec'",
    )
    p_ver.add_argument(
        "--dut", required=True, metavar="MODULE",
        help="Top-level DUT module name, e.g. serdes_top",
    )
    p_ver.add_argument(
        "--inst", required=True, metavar="PATTERN",
        help='Instance path pattern with {i} placeholder, e.g. "rx_gen[{i}].u_rx"',
    )
    p_ver.add_argument(
        "--clk", required=True, metavar="PORT",
        help="Clock port name",
    )
    p_ver.add_argument(
        "--rst", metavar="PORT", default=None,
        help="Reset port name (optional)",
    )
    p_ver.add_argument(
        "--rst-active-low", action="store_true",
        help="Reset is active-low (default: active-high)",
    )
    p_ver.add_argument(
        "--input", nargs="+", required=True, metavar="PORT",
        help="Input (stimulus) port names",
    )
    p_ver.add_argument(
        "--output", nargs="+", required=True, metavar="PORT",
        help="Output (observable) port names",
    )
    p_ver.add_argument(
        "--rtl", nargs="+", default=[], metavar="FILE",
        help="RTL source files to include in Questa Formal compile step",
    )
    p_ver.add_argument(
        "--depth", type=int, default=20, metavar="N",
        help="SVA proof depth in clock cycles (default: 20)",
    )
    p_ver.add_argument(
        "--tool", choices=["questa_formal", "spyglass", "all"],
        default="all", metavar="TOOL",
        help="Emit for: questa_formal, spyglass, or all (default: all)",
    )
    p_ver.add_argument(
        "--out-dir", "-o", default="formal/", metavar="DIR",
        help="Output directory for emitted files (default: formal/)",
    )
    p_ver.add_argument(
        "--name", default="", metavar="NAME",
        help="Suffix for emitted file names, e.g. rx_lane",
    )
    p_ver.add_argument(
        "--param", "-p", action="append", metavar="NAME=VALUE", default=[],
        help="DUT parameter override for the SV instantiation",
    )

    return parser


# ── Parameter parsing helper ──────────────────────────────────────────────────

def _parse_params(param_list: list[str]) -> dict[str, int]:
    """Parse [NAME=VALUE, ...] into {NAME: int_value}."""
    result = {}
    for item in param_list:
        if "=" not in item:
            _die(f"Bad --param format: {item!r}  (expected NAME=VALUE)", 2)
        name, _, value = item.partition("=")
        try:
            result[name.strip()] = int(value.strip())
        except ValueError:
            _die(f"--param value must be an integer: {item!r}", 2)
    return result


def _die(msg: str, code: int = 2) -> None:
    print(f"{red('error:')} {msg}", file=sys.stderr)
    sys.exit(code)


def _ok(msg: str) -> None:
    print(f"{green('✓')} {msg}")


# ── Simulator adapter helper (OQ-09) ─────────────────────────

def _load_results(args):
    from .coverage.result import CoverageResult
    json_files   = getattr(args, "results",        [])
    questa_files = getattr(args, "questa_reports", None) or []
    vcs_files    = getattr(args, "vcs_reports",    None) or []
    covergroup   = getattr(args, "covergroup",     None)
    has_json   = bool(json_files)
    has_questa = bool(questa_files)
    has_vcs    = bool(vcs_files)
    if has_json and (has_questa or has_vcs):
        _die("Cannot mix positional files with --questa-report/--vcs-report.", 2)
    results = []
    if has_questa or has_vcs:
        if has_questa:
            from .adapters.questa import from_vcover_report
            for fpath in questa_files:
                if not Path(fpath).exists(): _die(f"Not found: {fpath}", 2)
                try:
                    cr = from_vcover_report(fpath, covergroup=covergroup, run_id=Path(fpath).stem)
                except ValueError as e: _die(str(e), 2)
                results.append(cr)
                _ok(f"Questa  {Path(fpath).stem}  →  {len(cr)} bins")
        if has_vcs:
            from .adapters.vcs import from_urg_report
            for fpath in vcs_files:
                if not Path(fpath).exists(): _die(f"Not found: {fpath}", 2)
                try:
                    cr = from_urg_report(fpath, covergroup=covergroup, run_id=Path(fpath).stem)
                except ValueError as e: _die(str(e), 2)
                results.append(cr)
                _ok(f"VCS     {Path(fpath).stem}  →  {len(cr)} bins")
    else:
        if not json_files:
            _die("No result files. Pass JSON files or --questa-report/--vcs-report.", 2)
        for rpath in json_files:
            if not Path(rpath).exists(): _die(f"Not found: {rpath}", 2)
            results.append(CoverageResult.from_file(rpath))
    if not results: _die("No coverage results loaded.", 2)
    return results


# ── scan command ──────────────────────────────────────────────────────────────

def cmd_scan(args: argparse.Namespace) -> int:
    from .rtl.extractor import RtlExtractor
    params = _parse_params(args.param)
    ext = RtlExtractor()
    for f in args.files:
        if not Path(f).exists():
            _die(f"File not found: {f}", 2)
        ext.add_file(f)
    for name, value in params.items():
        ext.add_param(name, value)

    arrays = ext.extract()

    if args.json:
        out = {
            "files"  : args.files,
            "params" : params,
            "arrays" : [
                {
                    "parent_module" : a.parent_module,
                    "block_label"   : a.block_label,
                    "module_type"   : a.module_type,
                    "instance_base" : a.instance_base,
                    "genvar"        : a.genvar,
                    "bound_kind"    : a.bound_kind,
                    "bound_value"   : a.bound_value,
                    "bound_param"   : a.bound_param,
                    "count"         : a.count(params),
                    "source_file"   : a.source_file,
                }
                for a in arrays
            ],
        }
        print(json.dumps(out, indent=2))
    else:
        print(ext.report())
        unresolved = ext.unresolved()
        if unresolved:
            print(yellow(f"\n  {len(unresolved)} unresolved array(s) — use --param NAME=VALUE to resolve"))

    return 0


# ── spec command ──────────────────────────────────────────────────────────────

def cmd_spec(args: argparse.Namespace) -> int:
    from .rtl.extractor import RtlExtractor
    from .rtl.bridge import BinSpaceBuilder, CoverSpec
    from .core.spec_io import dump_bin_space

    params = _parse_params(args.param)

    # Build extraction
    ext = RtlExtractor()
    for f in args.files:
        if not Path(f).exists():
            _die(f"File not found: {f}", 2)
        ext.add_file(f)
    for name, value in params.items():
        ext.add_param(name, value)

    arrays = ext.extract()
    if not arrays:
        _die("No generate-for arrays detected in supplied RTL files.\n"
             "  Run 'dabih scan' to inspect what was found.", 2)

    # Filter by module type if --module was supplied
    if args.module:
        arrays = [a for a in arrays if a.module_type in args.module]
        if not arrays:
            _die(f"No arrays match module filter: {args.module}", 2)

    # Build coverage specs
    cover_specs: list[CoverSpec] = []
    if args.cover:
        for cover_item in args.cover:
            if len(cover_item) < 3:
                _die(f"--cover requires at least MODULE SIGNAL BIN: {cover_item}", 2)
            module_type = cover_item[0]
            signal      = cover_item[1]
            bins        = cover_item[2:]
            cover_specs.append(CoverSpec(signal, bins, module_type=module_type))

    builder = BinSpaceBuilder(arrays)
    if cover_specs:
        builder.cover_specs(cover_specs)
    else:
        # Default: 4-bin state coverpoint for all module types
        builder.cover("state", ["IDLE", "ACTIVE", "STALL", "ERROR"])

    results = builder.build(params)
    if not results:
        _die("Coverage spec produced no BinSpaces.\n"
             "  Check --cover MODULE names match extracted module types.\n"
             f"  Detected module types: {sorted({a.module_type for a in arrays})}", 2)

    # Merge all BinSpaces into one spec file per array
    # (Multiple BinSpaces → multiple spec files with index suffix)
    out_path = Path(args.out)
    if len(results) == 1:
        paths = [out_path]
    else:
        stem   = out_path.stem
        suffix = out_path.suffix or ".json"
        paths  = [out_path.parent / f"{stem}_{i}{suffix}" for i in range(len(results))]

    for i, (result, path) in enumerate(zip(results, paths)):
        bs   = result.bin_space
        data = dump_bin_space(bs)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2))

        arr    = result.array
        n_orb  = data["orbit_count"]
        total  = data["total_bins"]
        ratio  = data["compression_ratio"]
        method = data["method"]

        _ok(f"{arr.parent_module}.{arr.module_type} × {result.n_instances}"
            f"  →  {n_orb:,} orbits / {total:,} bins  ({ratio:.1f}×  {method})")
        print(f"   {dim(str(path))}")

    return 0


# ── expand command ────────────────────────────────────────────────────────────

def cmd_expand(args: argparse.Namespace) -> int:
    from .core.spec_io import load_bin_space_file, load_spec_file
    from .coverage.symbolic_expander import SymbolicExpansionEngine
    from .coverage.expander import ExpansionEngine

    # Load spec
    if not Path(args.spec).exists():
        _die(f"Spec file not found: {args.spec}", 2)
    spec_data = load_spec_file(args.spec)
    bs        = load_bin_space_file(args.spec)

    results = _load_results(args)

    # Choose engine based on space size
    total = bs.total_bin_count()
    if total > 500_000:
        engine = SymbolicExpansionEngine(bs)
    else:
        engine = ExpansionEngine(bs)

    # Expand (merge if multiple)
    if len(results) == 1:
        er = engine.expand(results[0],
                           track_provenance=getattr(args, "provenance", False))
    else:
        er = engine.merge_and_expand(results,
                                     track_provenance=getattr(args, "provenance", False))

    # Output
    if args.json:
        print(json.dumps(er.to_dict(), indent=2))
    else:
        print(er.report(max_holes=args.max_holes))

    # HTML report
    if args.html:
        from .reporting.html_report import render_html_report
        html_path = Path(args.html)
        title = spec_data.get("name", "Dabih Coverage Report")
        render_html_report(er, title=title, path=html_path)
        if not args.json:
            _ok(f"HTML report written: {html_path}")

    # Unresolved warnings
    if er.unresolved_labels:
        print(yellow(f"\n  ⚠  {len(er.unresolved_labels)} unresolved label-tuple(s) in result file(s)"),
              file=sys.stderr)

    # Exit code for CI
    if er.is_complete():
        return 0
    return 0 if args.no_exit_code else 1


# ── report command ────────────────────────────────────────────────────────────

def cmd_report(args: argparse.Namespace) -> int:
    from .core.spec_io import load_bin_space_file, load_spec_file
    from .coverage.result import CoverageResult
    from .coverage.symbolic_expander import SymbolicExpansionEngine
    from .coverage.expander import ExpansionEngine
    from .reporting.html_report import render_html_report

    if not Path(args.spec).exists():
        _die(f"Spec file not found: {args.spec}", 2)
    spec_data = load_spec_file(args.spec)
    bs        = load_bin_space_file(args.spec)

    results = _load_results(args)

    total = bs.total_bin_count()
    engine = SymbolicExpansionEngine(bs) if total > 500_000 else ExpansionEngine(bs)

    prov = getattr(args, "provenance", False)
    er = (engine.merge_and_expand(results, track_provenance=prov)
          if len(results) > 1
          else engine.expand(results[0], track_provenance=prov))

    title    = args.title or spec_data.get("name", "Dabih Coverage Report")
    out_path = Path(args.out)
    render_html_report(er, title=title, path=out_path)
    _ok(f"HTML report written: {out_path}")
    print(f"   Class coverage: {bold(f'{er.class_coverage_pct():.1f}%')}"
          f"  |  Bin coverage: {bold(f'{er.bin_coverage_pct():.1f}%')}"
          f"  |  {'Complete' if er.is_complete() else 'Incomplete'}")
    return 0


# ── verify command ────────────────────────────────────────────────────────────

def cmd_verify(args: argparse.Namespace) -> int:
    from .core.spec_io import load_bin_space_file
    from .formal import emit_symmetry_check
    from .formal.spec import DUTSpec

    if not Path(args.spec).exists():
        _die(f"Spec file not found: {args.spec}", 2)
    bs = load_bin_space_file(args.spec)

    params = _parse_params(args.param)

    spec = DUTSpec(
        top_module      = args.dut,
        instance_fmt    = args.inst,
        clk_port        = args.clk,
        rst_port        = args.rst,
        rst_active_high = not args.rst_active_low,
        input_ports     = args.input,
        output_ports    = args.output,
        rtl_files       = args.rtl,
        proof_depth     = args.depth,
        module_params   = params,
    )

    try:
        spec.validate()
    except ValueError as e:
        _die(str(e), 2)

    tools_map = {
        "questa_formal" : ["questa_formal"],
        "spyglass"      : ["spyglass"],
        "all"           : ["questa_formal", "spyglass"],
    }
    tools = tools_map[args.tool]

    emitted = emit_symmetry_check(
        bs,
        spec,
        out_dir = args.out_dir,
        name    = args.name,
        tools   = tools,
    )

    for key, path in emitted.items():
        _ok(f"{key:16s}  {path}")

    decls = getattr(bs, "_symmetry_declarations", [])
    print(f"\n   {dim(f'{len(decls)} symmetry declaration(s)  |  '
                    f'proof depth: {args.depth} cycles  |  '
                    f'tool(s): {args.tool}')}")

    if "questa_formal" in tools:
        print(f"\n   {bold('Tier 2 — Questa Formal:')}")
        print(f"   {dim('questa_formal -do ' + str(emitted.get('questa_tcl', '')))}")
    if "spyglass" in tools:
        print(f"\n   {bold('Tier 1 — SpyGlass (run first):')}")
        print(f"   {dim('vc_spyglass -tcl ' + str(emitted.get('spyglass_tcl', '')))}")

    return 0


# ── Main entry point ──────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args   = parser.parse_args(argv)

    dispatch = {
        "scan"  : cmd_scan,
        "spec"  : cmd_spec,
        "expand": cmd_expand,
        "report": cmd_report,
        "verify": cmd_verify,
    }

    try:
        return dispatch[args.command](args)
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"{red('error:')} {exc}", file=sys.stderr)
        if "--debug" in (argv or sys.argv):
            raise
        return 2


if __name__ == "__main__":
    sys.exit(main())
