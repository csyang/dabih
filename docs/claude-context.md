# Dabih — Claude Handoff Context
**Updated:** 2026-11-17  ·  v0.1.0  ·  528 tests passing  ·  OQ-01 through OQ-09 resolved

Paste this file at the start of a conversation to orient a new Claude instance.

---

## What Dabih Is

A Python library and CLI that compresses functional coverage models for ASIC/FPGA
verification using equivalence class partitioning and symmetry reduction.

**Core insight:** In a replicated hardware design (N identical lanes from a
`generate-for` loop), covering one representative bin implies coverage for every
bin in the same equivalence class (orbit). A 65,536-bin cross-coverage space
compresses to 165 orbits — 397× fewer simulation cycles needed.

**Tagline:** *Cut the Redundant. Keep What Matters.*

---

## Repository Layout

The archive unpacks to a single `dabih/` folder (the version is in the zip name,
e.g. `dabih-v0_1_0-source.zip`). Layout mirrors the Canopus project.

```
dabih/
├── dabih/                         Python package — the `dabih` CLI and library
│   ├── cli.py                     CLI entry point: scan / spec / expand / report / verify
│   ├── core/
│   │   ├── symmetry.py            Permutation, SymmetryGroup (generator closure)
│   │   ├── coverpoint.py          Coverpoint, BinLabel
│   │   ├── bin_space.py           BinSpace, Orbit — core orbit engine
│   │   ├── symbolic.py            SymbolicOrbitEngine — Pólya / Burnside / Möbius boundary
│   │   └── spec_io.py             BinSpace ↔ spec JSON (contract between CLI commands)
│   ├── rtl/
│   │   ├── generate_array.py      GenerateArray data class
│   │   ├── extractor.py           RtlExtractor — pyslang CST, no elaboration
│   │   └── bridge.py              BinSpaceBuilder — extracted arrays → BinSpace
│   ├── coverage/
│   │   ├── result.py              CoverageResult (portable result JSON)
│   │   ├── expander.py            ExpansionEngine (BFS, ≤ ~1M bins) + provenance
│   │   └── symbolic_expander.py   SymbolicExpansionEngine (large spaces) + provenance
│   ├── adapters/
│   │   ├── questa.py              vcover report text → CoverageResult
│   │   └── vcs.py                 urg text report → CoverageResult
│   ├── formal/
│   │   ├── spec.py                DUTSpec, PortSpec
│   │   ├── questa.py              SVA property wrapper + Questa Formal TCL
│   │   ├── spyglass.py            SpyGlass SGDC + run TCL
│   │   └── __init__.py            emit_symmetry_check()
│   └── reporting/
│       └── html_report.py         render_html_report() — self-contained HTML
├── tests/                         528 tests — read their input data from examples/
│   ├── test_core.py               BinSpace, group closure, orbit correctness (41)
│   ├── test_coverage.py           ExpansionEngine, CoverageResult (43)
│   ├── test_rtl.py                Extractor + bridge on real SV (45)
│   ├── test_symbolic.py           Pólya / Burnside vs BFS agreement (84)
│   ├── test_partial_symmetry.py   Instance / cyclic / pairwise symmetry API (58)
│   ├── test_adapters.py           Questa + VCS report adapters (49)
│   ├── test_formal.py             DUTSpec, SVA + SpyGlass emission (93)
│   ├── test_cli.py                All five commands + simulator-report flags (72)
│   └── test_provenance.py         Provenance tracking and backward compatibility (43)
├── examples/
│   ├── rtl/                       serdes_top.sv, mem_ctrl.sv, mixed_top.sv, multi_module.sv
│   ├── simulator/                 Sample Questa vcover and VCS urg reports
│   ├── specs/                     rx_lane.spec.json — output of `dabih spec`
│   ├── results/                   seed_0042 / seed_1337 / seed_9999 — synthetic result JSON
│   ├── formal/                    Sample output of `dabih verify` (SVA, Questa TCL, SpyGlass)
│   ├── reports/                   coverage_report.html — sample output of `dabih report`
│   └── python/                    lane_demo.py, rtl_demo.py — library walkthroughs
├── web/
│   ├── landing.html               Static project page
│   └── dashboard.jsx              Interactive coverage dashboard (React)
├── docs/
│   ├── user-guide.md              Installation, CLI reference, Python API, workflows
│   ├── design.md                  Architecture, mathematics, algorithms, data formats
│   ├── errata.md                  Known limitations, fixed bugs, test gaps
│   ├── schema-changelog.md        Spec / result JSON format history
│   └── claude-context.md          Handoff context for a new Claude session
├── assets/
│   ├── banner-full.png            Wide banner with compression-flow strip
│   ├── banner.png                 Logo, wordmark and tagline
│   ├── icon.png                   Application icon
│   └── icons/                     icon.ico, .iconset and sized PNGs
├── pyproject.toml                 Package metadata, `dabih` entry point, dependencies
├── release.sh                     Build and publish a release to the NFS share
├── .release.env.example           Template for the per-machine share path
├── RELEASING.md                   Release process
├── REQUIREMENTS.md                Living requirements and design record
├── LICENSE.md                     MIT
└── README.md                      Project overview and quick start
```

---

## Critical Rules — Never Break

1. `add_full_lane_symmetry()` and `BinSpaceBuilder._build_bin_space()` MUST
   use `add_instance_symmetry()`, not raw `add_symmetry()` — populates
   `_symmetry_declarations` required by Idea D.

2. `expand()` / `merge_and_expand()` without `track_provenance` must be
   identical to pre-OQ-06 behaviour.

3. argparse adapter flags must be added to the subparser directly
   (`p_exp.add_argument`), not to `add_argument_group`. Use `default=None`
   (not `default=[]`) on append actions.

4. BFS orbit count and symbolic orbit count must agree for all small spaces
   (enforced by parametric tests in test_symbolic.py).

---

## CLI

```
dabih scan   <files...> [--param N=V] [--json]
dabih spec   <files...> [--param N=V] [--cover MODULE SIGNAL BIN...] --out spec.json
dabih expand <result.json...> --spec spec.json
             [--questa-report FILE] [--vcs-report FILE] [--covergroup NAME]
             [--html r.html] [--json] [--provenance] [--no-exit-code]
dabih report <result.json...> --spec spec.json --out r.html
             [--questa-report FILE] [--vcs-report FILE] [--covergroup NAME]
dabih verify --spec spec.json --dut MODULE --inst "pat[{i}].u" --clk CLK
             [--rst PORT] [--rst-active-low] --input P... --output P...
             [--depth N] [--tool all|questa_formal|spyglass] [--out-dir DIR]
```

Exit: 0=complete, 1=incomplete (CI), 2=input error.

---

## Provenance API

```python
er = engine.merge_and_expand([r1, r2, r3], track_provenance=True)
er.has_provenance          # True
er.coverage_histogram()    # {1: 14, 2: 31, 3: 102}
er.fragile_orbits(threshold=2)
er.orbit_run_ids(labels)
```

---

## OQ Status

| OQ | Title | Status |
|----|-------|--------|
| OQ-01–09 | All resolved | ✅ |
| OQ-10 | Real RTL validation | 🔲 Needs internal RTL |
| OQ-11 | Idea D on real DUT | 🔲 Needs RTL + EDA licenses |

---

## Install

```bash
cd dabih
pip install -e ".[dev]"      # pyslang, pytest, build, and the `dabih` command
pytest -q                    # 528 passed
./release.sh --dry-run       # build wheel, sdist and dabih-v0_1_0-source.zip into dist/
```

Paths: tests read RTL from `examples/rtl/` and simulator reports from
`examples/simulator/` (relative to `tests/`). Docs are in `docs/`; the
requirements record is `REQUIREMENTS.md` at the root.
