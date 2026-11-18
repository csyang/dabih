<div align="center">
  <img src="../assets/banner.png" alt="Dabih" width="320" />
</div>

# Dabih — Errata

**Dabih version:** 0.1.0  ·  **Date:** 2026-05-24

This document records known bugs, limitations, fixed bugs, and important
implementation notes. Organised by severity.

---

## 1. Active Limitations

### L-01 — Parse-only RTL (no elaboration)

**Symptom:** Parameterised generate-for bounds with no default value in the
RTL source are reported as unresolved.

**Cause:** Dabih uses pyslang's concrete syntax tree (CST) without full
elaboration. Parameters that depend on higher-level instantiation context
cannot be resolved from the file alone.

**Workaround:** Supply the missing value via `--param NAME=VALUE` on the
CLI or `ext.add_param("NAME", value)` in the Python API.

```bash
# If N_LANES has no default in the RTL:
dabih scan rtl/top.sv --param N_LANES=8
dabih spec rtl/top.sv --param N_LANES=8 --cover lane state IDLE ACTIVE --out s.json
```

**Resolution path:** OQ-10 (real RTL validation) will identify specific
patterns that fail. If a common pattern is found, a heuristic can be added
to the extractor.

---

### L-02 — BFS engine ceiling ~1M bins

**Symptom:** `ExpansionEngine` consumes large amounts of memory or raises
`MemoryError` for spaces with > ~1M bins (e.g. 8 lanes × 2 signals × 4 bins
= 16,777,216 bins).

**Cause:** `ExpansionEngine` pre-builds a `dict[BinTuple, Orbit]` lookup
over the entire bin space at construction time.

**Workaround:** Use `SymbolicExpansionEngine` for any space where
`bs.total_bin_count() > 500_000`. The symbolic engine never enumerates the
full bin space.

```python
from dabih import SymbolicExpansionEngine
er = SymbolicExpansionEngine(bs).expand(result)
```

The CLI (`dabih expand`) switches to the symbolic engine automatically when
`total_bins > 500_000`.

---

### L-03 — Möbius inversion not implemented

**Symptom:** `SymbolicLimitError` raised when `|G| > 500,000`.

**Cause:** The Möbius inversion fallback in `SymbolicOrbitEngine` is a
documented boundary condition, not an implemented algorithm. In practice,
all hardware verification use cases are either full Sₙ (handled by Pólya,
O(1)) or small partial symmetry subgroups (handled by Burnside, |G| ≤ 500k).

**Workaround:** Decompose large groups into smaller subgroup declarations.
For example, instead of one `add_instance_symmetry([0..31])` (|S₃₂| =
32! — astronomical), use two separate declarations:
`add_instance_symmetry([0..15])` and `add_instance_symmetry([16..31])`.
Each generates a smaller Sₙ handled by Pólya.

---

### L-04 — Non-uniform bin counts in Burnside

**Symptom:** Burnside orbit count may be incorrect when coverpoints in the
same symmetry orbit have different bin counts (e.g. lane 0 has 4-bin state
but lane 1 has 3-bin state).

**Cause:** The Burnside formula `K^{c(g)}` assumes uniform K (per-position
bin count) across positions in the same cycle. For non-uniform bin counts,
the correct formula is more complex and not yet implemented.

**Note:** This situation should not arise in valid hardware verification
designs — if two instances are symmetric, they must have identical signal
definitions and bin sets. The limitation is only relevant if a BinSpace is
manually constructed with mixed bin counts across symmetric positions.

---

### L-05 — Provenance tracking memory overhead

**Symptom:** `merge_and_expand(..., track_provenance=True)` with many runs
and many covered orbits uses more memory than the non-provenance merge.

**Cause:** `_provenance` is a `dict[BinTuple, list[str]]` — one entry per
covered orbit, each storing a sorted list of run_id strings. For 10,000
runs covering 100,000 orbits with average run_id length 20 chars, this is
approximately 20MB.

**Workaround:** For regression regression scenarios with thousands of runs,
consider batching: merge in groups of 100, produce a provenance summary per
batch, then combine summaries.

---

### L-06 — No UCDB binary reader

**Symptom:** Cannot read `.ucdb` files directly.

**Cause:** By design — Dabih avoids EDA binary API dependencies to allow
post-processing on any machine without EDA licenses.

**Workaround:** Use the `vcover report -details` text adapter:
```bash
vcover report -details -cvg simresults.ucdb > vcover_output.txt
dabih expand --questa-report vcover_output.txt --covergroup my_cg --spec spec.json
```

---

### L-07 — Formal verification requires manual DUTSpec

**Symptom:** `dabih verify` requires explicit `--dut`, `--inst`, `--input`,
`--output` flags — it cannot infer port names from the RTL automatically.

**Cause:** Port role inference (which ports are inputs vs outputs, which
is the clock) requires elaboration and semantic analysis beyond CST parsing.

**Workaround:** Specify the DUTSpec explicitly. For well-understood generate-
for arrays, the port names are stable and can be scripted:

```bash
dabih verify \
    --spec spec.json \
    --dut serdes_top \
    --inst "rx_gen[{i}].u_rx" \
    --clk clk --rst rst_n --rst-active-low \
    --input valid data \
    --output state ready \
    --rtl examples/rtl/serdes_top.sv
```

---

### L-08 — OQ-10 and OQ-11 require internal RTL and EDA access

**Symptom:** End-to-end real-RTL validation (OQ-10) and Idea D on a real
DUT (OQ-11) cannot be run from this repository.

**Status:** Planned. Both require access to internal ASIC RTL and EDA tool
licenses. No Dabih code changes are expected from OQ-10; OQ-11 may surface
edge cases in the extractor or formal emitter.

---

### L-09 — Piping CLI output into a closing reader

**Symptom:** `dabih expand ... | head` prints `error: [Errno 32] Broken pipe`
and exits 2 instead of stopping quietly.

**Cause:** The top-level handler in `cli.main()` reports any exception —
including `BrokenPipeError` when the reader closes early — as an input error.

**Workaround:** Redirect to a file, or limit the output at the source with
`--max-holes N` (text report) or `--json | jq ...` (which reads all output).

---

## 2. Fixed Bugs (Historical Record)

### F-01 — `window.scrollTo` collision in HTML report  *(Fixed)*

**Symptom:** Clicking Coverage, Holes, and Orbit Detail nav items in the
HTML coverage report produced JavaScript errors.

**Root cause:** The nav `onclick` attribute called `scrollTo('coverage')`
which the browser resolved to the native `window.scrollTo(x, y)` method
rather than the custom function. `window.scrollTo('coverage', undefined)`
raised a type error.

**Fix:** Renamed the custom function to `dabihScrollTo()`. All `onclick`
attributes updated to `onclick="dabihScrollTo('coverage', this)"`. The `el`
parameter receives `this` for active-class management, replacing the
unreliable `event.currentTarget` reference.

**Introduced in:** Initial visual surfaces build.  
**Fixed in:** OQ-07 branding integration / HTML report JS debugfix.

---

### F-02 — False Sₙ detection for Z₂ groups  *(Fixed)*

**Symptom:** A Z₂ group (order 2 — single transposition) was incorrectly
classified as S₂ (also order 2) by the `SymbolicOrbitEngine` profile
auto-detector, causing Pólya to be selected instead of Burnside. This
produced an incorrect orbit count.

**Root cause:** The heuristic checked whether `group.order() == math.factorial(n)`
for some factorisation of the degree. For n=2, both Z₂ and S₂ have order 2,
so the check passed. The profile then set `is_full_sn = True`, selecting Pólya.

**Fix:** Added `_is_block_permutation(perm, block_size)` validation — all
group generators must genuinely permute whole blocks. A Z₂ transposition of
positions 1 and 2 on a degree-4 space does not permute blocks of size 2,
failing the check.

**Introduced in:** Idea E symbolic orbit engine.  
**Fixed in:** OQ-05 partial symmetry / symbolic profile fix.

---

### F-03 — Burnside `K` value computed over all coverpoints  *(Fixed)*

**Symptom:** Burnside orbit count was wildly wrong for partial symmetry
groups in the profile heuristic fallback.

**Root cause:** In the fallback profile (no declaration, no hint), `k_per_signal`
was set to `[cps[i].bin_count() for i in range(degree)]` — a list of length
`degree` with all coverpoint bin counts. `K = math.prod(k_per_signal)` then
equalled the total bin space size, not the per-position bin count. Burnside
then computed K^{c(g)} where K = total bin space, producing an enormously
wrong result.

**Fix:** For the direct-action fallback (block_size=1), `k_per_signal` is
set to `[k_uniform]` — a single entry for the per-coverpoint bin count.

**Introduced in:** Idea E symbolic orbit engine.  
**Fixed in:** OQ-05 / symbolic profile fallback fix (caught by BFS vs symbolic
parametric agreement tests).

---

### F-04 — Bridge using raw `add_symmetry()` — formal emission empty  *(Fixed)*

**Symptom:** `emit_symmetry_check()` on a BinSpace built via
`BinSpaceBuilder` produced an empty property file — the SVA property wrapper
had no assertion statements.

**Root cause:** `BinSpaceBuilder._build_bin_space()` called `bs.add_symmetry()`
directly with raw block-permutation generators, bypassing
`add_instance_symmetry()`. As a result, `_symmetry_declarations` was empty,
and the formal emitter had nothing to iterate over.

**Fix:** Replaced the two raw `add_symmetry()` calls in
`_build_bin_space()` with a single `bs.add_instance_symmetry(list(range(n)),
block_size=n_sigs)` call. This sets both the group generators and the
declarations in one step.

**Introduced in:** Idea D formal emission.  
**Fixed in:** Idea D test integration / bridge fix.

---

### F-05 — argparse `add_argument_group` flags not parsed  *(Fixed)*

**Symptom:** `dabih expand --questa-report FILE` raised "unrecognized arguments"
even after the flags were added to the argument parser.

**Root cause:** Flags were added to `add_argument_group(...)` objects, which
are purely cosmetic in argparse. They display grouped in `--help` but do not
actually register the arguments with the subparser's parser. Arguments must
be added directly to the subparser object (`p_exp.add_argument(...)`).

**Fix:** Removed the `sim_group = p_exp.add_argument_group(...)` intermediary
and added all adapter arguments directly to `p_exp`.

**Introduced in:** OQ-09 CLI adapter flags.  
**Fixed in:** OQ-09 test debugging.

---

### F-06 — `action="append"` default `[]` causes list mutation  *(Fixed)*

**Symptom:** The second CLI invocation in a test that used `--questa-report`
received an extra pre-populated entry in the `questa_reports` list, causing
unexpected "too many files" behaviour.

**Root cause:** `argparse` with `action="append", default=[]` reuses the
same list object as the default across multiple `parse_args()` calls in the
same process. The first call appends to the list; the second call receives
a list already containing the first call's value.

**Fix:** Changed `default=[]` to `default=None` on all append actions.
`_load_results()` uses `getattr(args, "questa_reports", None) or []` to
normalise None to an empty list.

**Introduced in:** OQ-09 CLI adapter flags.  
**Fixed in:** OQ-09 test debugging (detected by `test_expand_merge_two_questa`).

---

### F-07 — Packaging metadata could not install the package  *(Fixed)*

**Symptom:** `pip install -e .` failed, the `dabih` command was never
installed, and `pyslang` was not pulled in as a dependency.

**Root cause:** `pyproject.toml` named a build backend that does not exist
(`setuptools.backends.legacy:build`), had no `[project.scripts]` entry, and
declared `dependencies = []`. The whole test suite was run with
`PYTHONPATH=.`, so no test ever exercised installation.

**Fix:** `build-backend = "setuptools.build_meta"`;
`dabih = "dabih.cli:main"` registered under `[project.scripts]`;
`dependencies = ["pyslang>=12"]` (tested against pyslang 12.1.0); and explicit
`[tool.setuptools.packages.find] include = ["dabih*"]` so `assets/`, `docs/`,
`examples/` and `web/` at the repository root are not mistaken for packages.
Verified by installing into a clean virtual environment, running `dabih --help`,
and running the full suite.

**Introduced in:** Initial packaging.
**Fixed in:** 0.1.0 archive reorganisation.

---

### F-08 — CLI `--help` example used a flag that does not exist  *(Fixed)*

**Symptom:** The example `dabih expand sim/*.json --spec spec.json --merge ...`
in `dabih --help` failed with an argparse error.

**Root cause:** `expand` has never had a `--merge` flag — multiple result files
are merged automatically. The example was written from intent, not from the
parser.

**Fix:** The example is now
`dabih expand examples/results/*.json --spec spec.json --provenance --html report.html`,
which runs as written.

**Introduced in:** OQ-03 CLI.
**Fixed in:** 0.1.0 archive reorganisation.

---

### F-09 — Formal examples assumed a reset port the example RTL lacks  *(Fixed)*

**Symptom:** The `dabih verify` examples and the bundled formal sample used
`--rst rst_n` against `serdes_top.sv`, which has no reset port. The generated
properties therefore referred to a signal that does not exist in the file they
claimed to be generated from.

**Fix:** The examples now omit `--rst` for `serdes_top` (reset-less designs emit
no `disable iff` clause), and `examples/formal/` was regenerated from
`examples/rtl/serdes_top.sv` with the real instance hierarchy and port names.

**Introduced in:** Idea D sample outputs.
**Fixed in:** 0.1.0 archive reorganisation.

---

## 3. Known Gaps in Test Coverage

### G-01 — Real simulator output variants

The simulator sample reports in `examples/simulator/` (`questa_4lane_partial.txt`,
`vcs_4lane_partial.txt`, etc. — also the adapter test fixtures) were hand-crafted to match the documented format. Real simulator output
from different versions of Questa and VCS may use slightly different whitespace,
column alignment, or label formatting.

**Mitigation:** OQ-10 (real RTL validation) will produce real simulator
output for integration testing. The adapter parsers use robust regex
patterns that tolerate variable whitespace.

### G-02 — Formal artifact correctness

Tests in `test_formal.py` verify that the emitted SVA wrapper *contains*
expected strings (e.g. `"SYM_"`, `"assert property"`, `"questa_formal compile"`).
They do not verify that the emitted artifacts are syntactically valid
SystemVerilog or that Questa Formal accepts them.

**Mitigation:** OQ-11 (Idea D on real DUT) will run the emitted artifacts
through actual tool flows and verify results.

### G-03 — Symbolic engine for very large groups

The `SymbolicLimitError` path (Möbius boundary, |G| > 500,000) has no test
because no test fixture can practically reach this condition without extremely
large designs. The error message and exception type are tested indirectly
through the `test_symbolic.py` BURNSIDE_LIMIT constant check.

---

## 4. Implementation Notes

### N-01 — Provenance dict keys on representatives, not arbitrary hits

`_provenance` maps *canonical representative BinTuples* to run_id lists.
When a non-representative bin is hit, it is canonicalised before provenance
attribution. This ensures `orbit_run_ids(labels)` works correctly regardless
of which bin (representative or not) the simulation actually hit.

### N-02 — HTML report data injection

The HTML template uses Python f-string format with double-brace escaping for
JavaScript literal braces: `{{D.provenance}}` in the Python source becomes
`{D.provenance}` in the rendered HTML. Any new JavaScript added to the
template must follow this convention.

### N-03 — Spec file version field

`spec_io.py` checks `data["version"] == "1"` and raises `ValueError` for
other values. This is intentional — the spec format is versioned to allow
future breaking changes without silent data corruption.

### N-04 — `add_full_lane_symmetry` delegation

Since OQ-05, `add_full_lane_symmetry(n)` delegates entirely to
`add_instance_symmetry(list(range(n)), block_size=len(cps)//n)`. Any code
that calls `add_full_lane_symmetry` will now also populate
`_symmetry_declarations`. This is backward-compatible (orbit counts are
identical) but is a semantic change: `symmetry_declarations()` now returns
a non-empty list even when `add_full_lane_symmetry` was used.

### N-05 — SymbolicExpansionResult has no `coverage_map` dict

`SymbolicExpansionResult` does not expose a `coverage_map` attribute
(unlike `ExpansionResult`). Per-bin coverage queries use `is_covered(labels)`
instead. This is by design — materialising a full coverage map for a 16M-bin
space would defeat the purpose of the symbolic engine.

### N-06 — Tests and examples share one data folder

Test input data lives in `examples/` (RTL in `examples/rtl/`, simulator reports
in `examples/simulator/`); the test files locate it with
`os.path.join(os.path.dirname(__file__), "..", "examples", ...)`. Editing those
files changes both the documented examples and the test fixtures — run
`pytest` after touching them.
