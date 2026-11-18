<div align="center">
  <img src="../assets/banner.png" alt="Dabih" width="320" />
</div>

# Dabih — User Guide

**Dabih version:** 0.1.0  ·  **Date:** 2026-05-24

---

## 1. Installation

```bash
# Prerequisites: Python 3.11+
cd dabih                       # the unpacked source archive
pip install -e ".[dev]"        # installs pyslang, pytest, build and the `dabih` command

# Verify installation
dabih --help
pytest -q                      # 528 tests should pass
```

The commands in sections 3 and 4 use the sample data in `examples/` and can be
run from the repository root: RTL in `examples/rtl/`, simulator reports in
`examples/simulator/`, and synthetic result files in `examples/results/`.

---

## 2. Core Concepts

### Equivalence Classes (Orbits)

A cross-coverage group over N identical lanes produces N^k bins. Dabih
partitions these bins into equivalence classes: all bins in the same class
behave identically under the declared hardware symmetry.

Hitting *any* bin in a class implies coverage for the *entire* class.

### Compression Ratio

```
compression ratio = total bins / orbit count
```

For 8 lanes × 4 states: 65,536 bins → 165 orbits = **397× compression**.

### The Workflow

```
RTL source  →  dabih scan   (verify extraction)
            →  dabih spec   (build compressed coverage model)
simulation  →  dabih expand (expand results, identify holes)
            →  dabih report (generate HTML sign-off report)
            →  dabih verify (emit formal proofs)
```

---

## 3. CLI Reference

### 3.1 `dabih scan` — Extract generate-for arrays

```bash
dabih scan examples/rtl/serdes_top.sv --param N_LANES=8
dabih scan examples/rtl/*.sv --param N_LANES=4 --json
```

**Options:**
- `--param NAME=VALUE` — override RTL parameters (integers only; repeat as needed)
- `--json` — output results as JSON instead of formatted text

**Output:** A formatted table showing detected generate-for arrays with their
module type, instance base, genvar, and resolved instance count. Use this to
verify Dabih sees what you expect before building a spec.

---

### 3.2 `dabih spec` — Build coverage spec

```bash
# Single signal, single module type
dabih spec examples/rtl/serdes_top.sv \
    --param N_LANES=4 \
    --cover rx_lane state IDLE ACTIVE STALL ERROR \
    --module rx_lane \
    --out spec.json

# Multiple signals (cross-coverage)
dabih spec examples/rtl/serdes_top.sv \
    --param N_LANES=4 \
    --cover rx_lane state IDLE ACTIVE STALL ERROR \
    --cover rx_lane ready LO HI \
    --module rx_lane \
    --out spec_cross.json

# Multiple module types → one spec file per array (spec_all_0.json, spec_all_1.json)
dabih spec examples/rtl/serdes_top.sv \
    --param N_LANES=4 \
    --cover rx_lane state IDLE ACTIVE STALL ERROR \
    --cover tx_lane state IDLE SEND FLUSH ERROR \
    --out spec_all.json
```

The examples in the rest of this guide use the first one, `spec.json`. A result
file only resolves against the spec whose coverpoints it was recorded for — the
single-signal spec above has 4 coverpoints, the cross spec has 8 — so keep the
spec and its results together.

**Options:**
- `--param NAME=VALUE` — parameter overrides (repeat as needed)
- `--cover MODULE SIGNAL BIN [BIN...]` — declare coverage for a signal on a
  specific module type; may be repeated for multiple signals/modules
- `--module MODULE` — restrict extraction to a named module type
- `--out FILE` — output spec JSON path (required)

**Output:** A spec JSON file containing the orbit count, compression ratio,
and pre-computed representatives. This file is the input to `expand`,
`report`, and `verify`.

**Note:** When no `--cover` flag is given, a default 4-bin state coverpoint
(`IDLE ACTIVE STALL ERROR`) is assumed.

---

### 3.3 `dabih expand` — Expand simulation results

```bash
# From Dabih JSON
dabih expand examples/results/seed_0042.json --spec spec.json

# Incomplete coverage exits 1 (for CI pipelines)
dabih expand examples/results/seed_0042.json --spec spec.json
echo "Exit code: $?"    # 1 = incomplete, 0 = complete

# Suppress CI exit code
dabih expand examples/results/seed_0042.json --spec spec.json --no-exit-code

# Merge multiple runs
dabih expand examples/results/*.json --spec spec.json

# Generate HTML report
dabih expand examples/results/seed_0042.json --spec spec.json --html report.html

# JSON output (for scripting)
dabih expand examples/results/seed_0042.json --spec spec.json --json | jq '.class_coverage'

# With provenance tracking
dabih expand examples/results/seed_0042.json examples/results/seed_1337.json \
    --spec spec.json --provenance

# From Questa vcover report
dabih expand \
    --questa-report examples/simulator/questa_4lane_partial.txt \
    --covergroup rx_lane_cross_cg \
    --spec spec.json

# From VCS urg report
dabih expand \
    --vcs-report examples/simulator/vcs_4lane_partial.txt \
    --covergroup rx_lane_cross_cg \
    --spec spec.json

# Merge Questa runs (seed_042.txt / seed_1337.txt stand in for your own
# per-seed `vcover report -details` output)
dabih expand \
    --questa-report seed_042.txt \
    --questa-report seed_1337.txt \
    --covergroup rx_lane_cross_cg \
    --spec spec.json
```

**Options:**
- `--spec FILE` — spec JSON from `dabih spec` (required)
- `--questa-report FILE` — Questa `vcover report -details` text file
- `--vcs-report FILE` — VCS `urg -format text` coverage file
- `--covergroup NAME` — covergroup name (required for multi-cg reports)
- `--html FILE` — write HTML report to FILE
- `--json` — output JSON instead of text
- `--provenance` — track which run_id covered each orbit
- `--no-exit-code` — always exit 0 (suppress CI exit-code behaviour)
- `--max-holes N` — maximum holes to show in text report (default: 20)

**Exit codes:** 0 = complete coverage, 1 = incomplete, 2 = input error.

---

### 3.4 `dabih report` — Generate HTML report

```bash
# From Dabih JSON
dabih report examples/results/seed_0042.json \
    --spec spec.json \
    --out coverage_report.html \
    --title "SerDes RX — Tape-out Coverage"

# From simulator report
dabih report \
    --questa-report examples/simulator/questa_4lane_partial.txt \
    --covergroup rx_lane_cross_cg \
    --spec spec.json \
    --out report.html

# With provenance (shows Confidence tab in report)
dabih report examples/results/*.json \
    --spec spec.json \
    --out report.html \
    --provenance
```

**Options:**
- `--spec FILE` — required
- `--out FILE` — output HTML path (required)
- `--title TEXT` — report heading (default: derived from spec name)
- `--provenance` — enable confidence histogram in the report
- All simulator adapter flags from `expand` also apply

---

### 3.5 `dabih verify` — Emit formal verification artifacts

```bash
dabih verify \
    --spec spec.json \
    --dut serdes_top \
    --inst "rx_gen[{i}].u_rx" \
    --clk clk \
    --input valid data \
    --output state ready \
    --rtl examples/rtl/serdes_top.sv \
    --depth 20 \
    --tool all \
    --out-dir formal/ \
    --name rx_lane
```

`serdes_top` has a clock but no reset port, so `--rst` is omitted and no
`disable iff` clause is emitted. For a design with a reset, add `--rst PORT`
(and `--rst-active-low` if it is active-low).

**Options:**
- `--spec FILE` — required
- `--dut MODULE` — top-level DUT module name
- `--inst PATTERN` — hierarchical instance path with `{i}` placeholder,
  e.g. `"rx_gen[{i}].u_rx"` or `"lane[{i}]"`
- `--clk PORT` — clock port name
- `--rst PORT` — reset port name (optional)
- `--rst-active-low` — reset is active-low (default: active-high)
- `--input PORT [PORT...]` — stimulus port names
- `--output PORT [PORT...]` — observable response port names
- `--rtl FILE [FILE...]` — RTL sources for Questa Formal compile step
- `--depth N` — SVA proof depth in cycles (default: 20)
- `--tool` — `all` (default), `questa_formal`, or `spyglass`
- `--out-dir DIR` — output directory (default: `formal/`)
- `--name SUFFIX` — suffix for emitted filenames

**Emitted files:**
- `dabih_sym_<name>.sv` — SystemVerilog property wrapper
- `dabih_questa_formal_<name>.tcl` — Questa Formal compile + verify script
- `dabih_spyglass_<name>.sgdc` — SpyGlass design constraints
- `dabih_spyglass_<name>.tcl` — SpyGlass run script

**Running the formal tools:**
```bash
# Tier 1 — SpyGlass (run first, takes minutes)
vc_spyglass -tcl formal/dabih_spyglass_rx_lane.tcl

# Tier 2 — Questa Formal (takes longer, authoritative)
questa_formal -do formal/dabih_questa_formal_rx_lane.tcl
```

---

## 4. Python API

### 4.1 Building a BinSpace

```python
from dabih import BinSpace, Coverpoint

bs = BinSpace(name="4-lane rx")
for i in range(4):
    bs.add_coverpoint(
        Coverpoint.from_names(f"lane{i}_state", ["IDLE","ACTIVE","STALL","ERROR"])
    )

# Declare full S4 symmetry (all 4 lanes equivalent)
bs.add_full_lane_symmetry(4)

# Or declare partial symmetry (only lanes 1–3, lane 0 is special)
bs.add_instance_symmetry([1, 2, 3])

# Cyclic symmetry (ring topology)
bs.add_cyclic_symmetry([0, 1, 2, 3])

# Pairwise independent symmetry
bs.add_pairwise_symmetry([(0,1), (2,3)])

print(bs.orbit_count())          # → 35
print(bs.compression_ratio())    # → 7.31
```

### 4.2 RTL-driven workflow

```python
from dabih import RtlExtractor, BinSpaceBuilder

ext = (RtlExtractor()
       .add_file("examples/rtl/serdes_top.sv")
       .add_param("N_LANES", 4))

arrays = [a for a in ext.extract() if a.module_type == "rx_lane"]

built = (BinSpaceBuilder(arrays)
         .cover("state", ["IDLE", "ACTIVE", "STALL", "ERROR"])
         .build(ext.param_overrides))

bs = built[0].bin_space
print(bs.orbit_count())        # → 35
# Add .cover("ready", ["LO", "HI"]) for a state × ready cross (330 orbits).
```

### 4.3 Coverage expansion

```python
from dabih import CoverageResult, ExpansionEngine

# From Dabih JSON
result = CoverageResult.from_file("examples/results/seed_0042.json")
er = ExpansionEngine(bs).expand(result)

print(er.class_coverage_pct())    # → 57.14
print(er.is_complete())           # → False
print(er.n_orbits_hit())          # → 20 of 35

# Merge multiple runs
r1 = CoverageResult.from_file("examples/results/seed_0042.json")
r2 = CoverageResult.from_file("examples/results/seed_1337.json")
er = ExpansionEngine(bs).merge_and_expand([r1, r2])
```

### 4.4 Simulator adapters

```python
from dabih.adapters.questa import from_vcover_report
from dabih.adapters.vcs    import from_urg_report

# Questa
cr = from_vcover_report("examples/simulator/questa_4lane_partial.txt", covergroup="rx_lane_cross_cg")

# VCS
cr = from_urg_report("examples/simulator/vcs_4lane_partial.txt", covergroup="rx_lane_cross_cg")

# Then expand normally
er = ExpansionEngine(bs).expand(cr)
```

### 4.5 Large spaces (symbolic engine)

For spaces > ~1M bins, use `SymbolicExpansionEngine`:

```python
from dabih import SymbolicExpansionEngine
from dabih.core.symbolic import SymbolicOrbitEngine

sym = SymbolicOrbitEngine(bs)
print(sym.count_orbits())          # O(1) — no enumeration
print(sym.compression_ratio())     # → 7.31 here; an 8-lane state × ready space gives 2607×
                                   #   (6,435 orbits from 16.7M bins, still O(1))

er = SymbolicExpansionEngine(bs).expand(result)
print(er.class_coverage_pct())
print(er.missed_representatives()[:5])
```

### 4.6 Provenance tracking

```python
engine = ExpansionEngine(bs)
r3 = CoverageResult.from_file("examples/results/seed_9999.json")
er = engine.merge_and_expand([r1, r2, r3], track_provenance=True)

print(er.has_provenance)               # True
print(er.coverage_histogram())         # {1: 12, 2: 15, 3: 5}
print(er.fragile_orbits(threshold=2))  # list of rep BinTuples covered by 1 run
print(er.single_coverage_orbits())     # same as fragile_orbits(threshold=2)
labels = bs.bin_label(er.fragile_orbits()[0])
print(er.orbit_run_ids(labels))        # the run(s) that covered that orbit
```

### 4.7 HTML report generation

```python
from dabih.reporting import render_html_report

# Basic — a single run
er = engine.expand(r1)
render_html_report(er, title="SerDes RX Coverage", path="report.html")

# With provenance (enables the Confidence tab in the report)
er = engine.merge_and_expand([r1, r2, r3], track_provenance=True)
render_html_report(er, title="Multi-run Coverage", path="report.html")
```

### 4.8 Formal emission

```python
from dabih.formal import emit_symmetry_check
from dabih.formal.spec import DUTSpec

spec = DUTSpec(
    top_module      = "serdes_top",
    instance_fmt    = "rx_gen[{i}].u_rx",
    clk_port        = "clk",
    input_ports     = ["valid", "data"],
    output_ports    = ["state", "ready"],
    rtl_files       = ["examples/rtl/serdes_top.sv"],
    proof_depth     = 20,
    module_params   = {"N_LANES": 4},
)

emitted = emit_symmetry_check(bs, spec, out_dir="formal/", name="rx_lane")
# emitted: {"sv": Path, "questa_tcl": Path, "spyglass_sgdc": Path, "spyglass_tcl": Path}
```

---

## 5. Typical Workflows

The workflows below use placeholder paths (`rtl/chip_top.sv`, `sim/results/`) for
your own project — substitute your own.

### 5.1 New design — first compression assessment

```bash
# 1. Confirm extraction detects the arrays
dabih scan rtl/chip_top.sv --param N_LANES=8

# 2. Build the compressed model
dabih spec rtl/chip_top.sv \
    --param N_LANES=8 \
    --cover lane state IDLE ACTIVE STALL ERROR \
    --module lane \
    --out lane_spec.json

# 3. Check the result
cat lane_spec.json | python3 -c "
import json, sys
d = json.load(sys.stdin)
print(f'{d[\"orbit_count\"]} orbits / {d[\"total_bins\"]} bins')
print(f'{d[\"compression_ratio\"]}× compression  ({d[\"method\"]})')
"
```

### 5.2 Regression closure with CI

```makefile
# Makefile snippet
coverage-check:
    dabih expand sim/results/*.json \
        --spec coverage/lane_spec.json \
        --html coverage/report.html
    # Returns exit 1 if incomplete — fails the CI stage
```

### 5.3 Regression with provenance (fragility analysis)

```bash
# After a large regression (many seeds)
dabih expand sim/*.json \
    --spec lane_spec.json \
    --provenance \
    --html regression_report.html

# Open report and check the ◐ Confidence tab:
# - Single-seed orbits: need more targeted stimulus
# - Well-covered (≥3 seeds): robust coverage
```

### 5.4 Integrating Questa vcover reports

```bash
# Step 1: Get the report from Questa
vcover report -details -cvg simresults.ucdb > vcover_output.txt

# Step 2: Expand directly
dabih expand \
    --questa-report vcover_output.txt \
    --covergroup lane_cross_cg \
    --spec lane_spec.json \
    --html report.html

# Multiple seeds merged
for f in seed_*.ucdb; do
    vcover report -details -cvg $f > ${f%.ucdb}.txt
done
dabih expand --questa-report seed_*.txt \
    --covergroup lane_cross_cg \
    --spec lane_spec.json
```

### 5.5 Formal symmetry verification

```bash
# Step 1: Build the spec
dabih spec rtl/chip_top.sv --param N_LANES=4 \
    --cover lane state IDLE ACTIVE STALL ERROR \
    --module lane --out lane_spec.json

# Step 2: Emit formal artifacts
dabih verify \
    --spec lane_spec.json \
    --dut chip_top \
    --inst "lane_gen[{i}].u_lane" \
    --clk clk --rst rst_n --rst-active-low \
    --input valid data_in \
    --output state data_out \
    --rtl rtl/chip_top.sv rtl/lane.sv \
    --depth 20 \
    --out-dir formal/

# Step 3: Run SpyGlass first (fast)
vc_spyglass -tcl formal/dabih_spyglass.tcl
# Check formal/dabih_sym_violations.txt

# Step 4: Run Questa Formal (authoritative)
questa_formal -do formal/dabih_questa_formal.tcl
# PROVEN = symmetry confirmed, compression is sound
# FALSIFIED = see counterexample waveform
```

---

## 6. Reading the HTML Report

The HTML report has six tabs accessible from the left sidebar:

**◈ Overview** — Run metadata, five summary stat cards (compression ratio,
orbit count, bin space size, simulation hits, unresolved labels), and a
complete/incomplete badge.

**◎ Coverage** — Two animated radial gauges: class coverage (how many
equivalence classes were hit, in cyan) and implied bin coverage (how many
bins are covered as a result, in purple). Each gauge has a matching progress
bar beneath it.

**◌ Holes** — Searchable table of uncovered orbit representatives. Filter
by label value to find patterns. Each row shows the representative bin
and the orbit size (how many raw bins it implies).

**⬡ Orbit Detail** — Searchable table of covered orbits with representative
labels and orbit sizes.

**⧖ Symmetry** — The symmetry declarations on the BinSpace: which instance
indices are declared equivalent, the group name (S4, Z2×Z2, etc.), and the
number of generators.

**≡ Coverpoints** — All coverpoints in the BinSpace, one chip per coverpoint.

**◐ Confidence** — Only visible when provenance is tracked (use
`--provenance` in the CLI or `track_provenance=True` in the API). Shows:
a summary row (single-seed / two-seed / well-covered counts), a colour-coded
histogram (amber = fragile, grey = two-seed, green = well-covered), and a
searchable fragile orbit chip grid.

---

## 7. CoverageResult JSON Format

Dabih's portable format for simulation output:

```json
{
  "run_id"    : "seed_042",
  "simulator" : "questa",
  "covergroup": "lane_cross_cg",
  "hits": [
    {"bin": ["IDLE", "ACTIVE", "STALL", "IDLE"], "count": 7}
  ]
}
```

To produce this from a UVM testbench:

```systemverilog
// In your UVM scoreboard or coverage collector:
function void write_dabih_json(string filename, string run_id,
                               string covergroup);
  int fd = $fopen(filename, "w");
  $fwrite(fd, "{\n");
  $fwrite(fd, "  \"run_id\": \"%s\",\n", run_id);
  $fwrite(fd, "  \"simulator\": \"questa\",\n");
  $fwrite(fd, "  \"covergroup\": \"%s\",\n", covergroup);
  $fwrite(fd, "  \"hits\": [\n");
  // iterate over cross bins with count > 0 and write:
  // {"bin": ["IDLE", "ACTIVE"], "count": N}
  $fwrite(fd, "  ]\n}\n");
  $fclose(fd);
endfunction
```

Alternatively, use the Questa or VCS adapter — no testbench changes needed.

---

## 8. Spec JSON Reference

The spec file written by `dabih spec` contains:

| Field | Type | Description |
|-------|------|-------------|
| `version` | string | Always `"1"` |
| `name` | string | Human-readable BinSpace name |
| `coverpoints` | array | `[{name, bins}]` — ordered list of coverpoints |
| `declarations` | array | Symmetry declarations (type, indices, block_size, group) |
| `orbit_count` | integer | Total number of equivalence classes |
| `total_bins` | integer | Raw bin space size (product of all bin counts) |
| `compression_ratio` | float | `total_bins / orbit_count` |
| `method` | string | `"polya"` or `"burnside"` |
| `representatives` | array | Label-tuples, one per orbit |

The `representatives` field is pre-computed to make `dabih expand` fast
— it does not re-run the symbolic engine on the spec file.
