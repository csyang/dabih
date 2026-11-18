# Dabih — Living Requirements & Design Document

**Project:** Dabih  
**CLI:** `dabih`  
**Version:** 0.1.0  
**Status:** Active Development  
**Last Updated:** 2026-11-17 (archive reorganised to the Canopus layout — 528 tests passing)  

---

## Table of Contents

1. [Project Purpose](#1-project-purpose)
2. [Core Concept](#2-core-concept)
3. [Idea Inventory](#3-idea-inventory)
4. [Architecture](#4-architecture)
5. [Module Reference](#5-module-reference)
6. [Key Design Decisions](#6-key-design-decisions)
7. [Known Constraints & Limitations](#7-known-constraints--limitations)
8. [Outstanding Decisions & Open Questions](#8-outstanding-decisions--open-questions)
9. [Test Coverage Summary](#9-test-coverage-summary)
10. [Canonical JSON Format](#10-canonical-json-format)
11. [Glossary](#11-glossary)
12. [Visual & Reporting Surfaces](#12-visual--reporting-surfaces)

---

## 1. Project Purpose

Dabih is a standalone hardware verification tool that compresses functional
coverage models using **equivalence class partitioning** and **symmetry
reduction** — techniques drawn from formal methods and software testing theory.

The fundamental observation: coverage models for replicated hardware (lane
arrays, pipeline stages, identical functional units) explode combinatorially
because cross-coverage bins multiply. A covergroup with 10 coverpoints of 10
bins each has 10¹⁰ potential cross-coverage bins. Most of these bins represent
redundant verification work — testing one representative is sufficient for an
entire equivalence class.

Dabih is **not** tied to Cartographer or any register-interface tooling. It
targets RTL-level functional verification.

**Primary deliverable:** A Python library (and eventually CLI) that:

1. Analyzes RTL to extract structural symmetries automatically
2. Partitions coverage bins into equivalence classes (orbits)
3. Produces a minimal compressed coverage specification
4. Expands post-simulation results back to full implied coverage
5. Optionally verifies symmetry claims formally

---

## 2. Core Concept

### Equivalence Relation

Two coverage bins b₁ and b₂ are **equivalent** if and only if hitting b₁
provides the same verification evidence as hitting b₂.

This defines an equivalence relation `~` on the bin space B. The equivalence
classes (orbits) partition B, and only one representative per orbit need be
exercised.

### Symmetry Group

The set of all permutations of design elements that leave observable behavior
invariant forms a **symmetry group** G. Each bin's equivalence class is its
orbit under G:

```
[b] = { g(b) : g ∈ G }
```

Covering all orbits under a valid symmetry group is **provably equivalent**
to covering all bins — this is the completeness guarantee.

### Compression Formula

For the common case of Sₙ (full symmetric group) acting on n instances with
k bins each, orbit count = C(n+k−1, k), yielding ratios such as:

| Lanes (n) | Bins/lane (k) | Raw bins | Orbits | Ratio  |
|-----------|---------------|----------|--------|--------|
| 3         | 4             | 64       | 20     | 3.2×   |
| 5         | 4             | 1,024    | 56     | 18.3×  |
| 8         | 4             | 65,536   | 165    | 397×   |

---

## 3. Idea Inventory

| ID | Name | Status | Description |
|----|------|--------|-------------|
| **A** | RTL Generate-For Extractor | ✅ **Done** | Parse SystemVerilog via pyslang CST; detect generate-for loops instantiating replicated modules; emit `GenerateArray` descriptors |
| **B** | Orbit Engine / BinSpace | ✅ **Done** | Core compression library: `Permutation`, `SymmetryGroup`, `Coverpoint`, `BinSpace`; BFS orbit computation; representative selection; `expand_coverage()` stub |
| **C** | Coverage DB Post-Processor | ✅ **Done** | `CoverageResult` (portable JSON format); `ExpansionEngine` (label→BinTuple translation, orbit propagation, merge); `ExpansionResult` (stats, holes report, `to_dict`) |
| **D** | Formal Symmetry Verification Pass | ✅ **Done** | Two-tier: SpyGlass structural pre-check (Tier 1) + Questa Formal SVA proof (Tier 2). Emits `.sv` property wrapper, `.tcl` Questa script, `.sgdc` SpyGlass rules. **93 tests.** |
| **E** | Symbolic Orbit Engine | ✅ **Done** | Pólya closed-form (O(1) for Sₙ), Burnside's lemma (O(\|G\|) for partial symmetry), Möbius as documented boundary. Removes BFS enumeration ceiling — 16M-bin spaces computed in microseconds. `SymbolicOrbitEngine`, `SymbolicExpansionEngine`. |

---

## 4. Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                            Dabih                                    │
│                                                                     │
│  RTL Sources (.sv)                                                  │
│       │                                                             │
│       ▼  [Idea A]                                                   │
│  RtlExtractor  ──►  GenerateArray[]                                 │
│       │                 │                                           │
│       │                 ▼  BinSpaceBuilder                          │
│       │           BinSpace  (coverpoints + symmetry group)          │
│       │                 │                                           │
│       │                 ▼  [Idea B]                                 │
│       │           Orbit partition  (equivalence classes)            │
│       │                 │                                           │
│       │           select_representatives()                          │
│       │                 │                                           │
│       │      Compressed coverage spec  (N → M bins, M << N)        │
│       │                 │                                           │
│       │           ◄─ Simulation ─►                                  │
│       │                 │                                           │
│       │           CoverageResult  (.json)                           │
│       │                 │                                           │
│       │                 ▼  [Idea C]                                 │
│       │           ExpansionEngine.expand()                          │
│       │                 │                                           │
│       │           ExpansionResult                                   │
│       │           ├── coverage_map  (all bins → hit count)          │
│       │           ├── orbits_hit / orbits_missed                    │
│       │           ├── class_coverage_pct / bin_coverage_pct         │
│       │           └── holes report                                  │
│       │                                                             │
│       │  [Idea E — Done]                                            │
│       │  SymbolicOrbitEngine  (Pólya/Burnside/Möbius)               │
│       │  SymbolicExpansionEngine  (canonical-form, no BFS ceiling)  │
│       │                                                             │
│       ▼  [Idea D — Done]                                           │
│  Tier 1: SpyGlass structural pre-check  (vc_spyglass 2024.09-SP2) │
│  Tier 2: Questa Formal SVA proof        (questa-formal 2024.3_1)  │
│  Emits: .sv property wrapper + .tcl script + .sgdc SpyGlass rules │
└─────────────────────────────────────────────────────────────────────┘
```

### Package Layout

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

### `core/symbolic.py`  *(Idea E)*

| Class | Key Methods |
|-------|-------------|
| `SymbolicOrbitEngine` | `count_orbits()`, `method_used()` → `"polya"\|"burnside"\|"mobius"`, `compression_ratio()`, `canonical(bt)`, `orbit_of(bt)`, `is_same_orbit(bt1,bt2)`, `representatives()`, `report()` |
| `SymmetryProfile` | `n_blocks`, `block_size`, `k_per_signal`, `K`, `is_full_sn`, `total_bins()` |
| `SymbolicLimitError` | Raised when `\|G\|` > `BURNSIDE_LIMIT` (500,000) and Möbius is required |

**Method selection priority:** (1) Pólya if `is_full_sn` from declaration or hint; (2) Burnside if `\|G\|` ≤ 500,000; (3) `SymbolicLimitError`.

**Profile detection priority:** (1) `_symmetry_declarations` on BinSpace; (2) `_symbolic_hint` set by bridge; (3) heuristic from group order + block-permutation validation.

**Key invariant for Pólya:** Orbit count = C(n+K−1, n) where K = per-block combo count = Π k_per_signal. Representatives enumerated via `combinations_with_replacement` — O(orbit_count), not O(total_bins).

### `coverage/symbolic_expander.py`  *(Idea E + C)*

| Class | Key Methods |
|-------|-------------|
| `SymbolicExpansionEngine` | `expand(result)` → `SymbolicExpansionResult`, `merge_and_expand(results)` |
| `SymbolicExpansionResult` | `n_orbits()`, `n_orbits_hit()`, `class_coverage_pct()`, `n_bins_covered()`, `bin_coverage_pct()`, `is_complete()`, `is_covered(labels)`, `missed_representatives()`, `report()`, `to_dict()` |

**When to use vs `ExpansionEngine`:**
- `ExpansionEngine` (BFS): total bins ≤ ~1M, need full `coverage_map` dict
- `SymbolicExpansionEngine`: total bins > ~1M, or Sₙ group — canonical-form expansion, no full map

**Key difference:** `SymbolicExpansionResult` has no `coverage_map` dict. Per-bin queries use `is_covered(labels)` instead.

### `core/bin_space.py` — New methods  *(OQ-05)*

| Method | Description |
|--------|-------------|
| `add_instance_symmetry(instance_indices, block_size=1)` | Sₖ on arbitrary instance subset. Primary partial-symmetry API. |
| `add_cyclic_symmetry(instance_indices, block_size=1)` | Zₙ ring symmetry. One generator (n-cycle). Fewer orbits removed than Sₙ. |
| `add_pairwise_symmetry(pairs, block_size=1)` | Z₂×Z₂×... independent pairs. One generator per pair. |
| `symmetry_declarations()` | Returns list of structured intent dicts for Idea D and symbolic engine. |
| `add_full_lane_symmetry(n)` | Now delegates to `add_instance_symmetry([0..n-1])`. Backward compatible. |

**Validation:** All three raise `ValueError` for `block_size < 1`, out-of-range indices, or `block_size` not dividing coverpoint count. Empty or single-element `instance_indices` are no-ops.

**`_symmetry_declarations` schema per entry:**
```python
{
  "type"             : "instance" | "cyclic" | "pairwise",
  "instance_indices" : [int, ...]   # instance or cyclic
  "pairs"            : [[int,int],...]  # pairwise only
  "block_size"       : int,
  "group"            : "S3" | "Z4" | "Z2×Z2" | ...,
  "n_generators"     : int,
}
```

### `reporting/html_report.py`

| Function | Description |
|----------|-------------|
| `render_html_report(er, title, logo_src, path)` | Generate self-contained HTML report from `ExpansionResult` or `SymbolicExpansionResult`. Returns HTML string; writes to `path` if given. |

**Accepts both result types.** Normalises stats via `_extract_stats()`. All CSS and JS inlined — no network at view time. Panels: summary stats, dual coverage gauges (animated SVG), searchable holes table, covered orbit detail, symmetry declarations, coverpoints.

---

## 5. Module Reference

### `core/symmetry.py`

| Class | Key Methods |
|-------|-------------|
| `Permutation` | `apply(t)`, `compose(other)`, `inverse()`, `.identity(n)`, `.transposition(n,i,j)`, `.full_cycle(n)`, `.cycle(n, indices)`, `order()`, `cycle_notation()` |
| `SymmetryGroup` | `add_generator(perm)`, `elements()` (BFS closure), `generators_and_inverses()`, `order()`, `is_trivial()` |

**Convention:** `perm[i] = j` means position i draws its value from original
position j. So `apply(t)[i] = t[perm[i]]`.

### `core/coverpoint.py`

| Class | Key Methods / Constructors |
|-------|---------------------------|
| `Coverpoint` | `.from_names(name, bins)`, `.from_range(name, lo, hi)`, `.value_class_bins(name)`, `add_bin()`, `add_bins()` |
| `BinLabel` | `name`, `value` |

**Standard value classes** (6 bins): `ZERO`, `ONE_HOT`, `BOUNDARY_LO`,
`BOUNDARY_HI`, `INTERIOR`, `ALL_ONES` — the behaviorally distinct partitions
for a data field.

### `core/bin_space.py`

| Class | Key Methods |
|-------|-------------|
| `BinSpace` | `add_coverpoint(cp)`, `add_symmetry(perm)`, `add_full_lane_symmetry(n)`, `compute_orbits()` → `list[Orbit]`, `select_representatives()`, `compression_ratio()`, `compression_pct()`, `total_bin_count()`, `orbit_count()`, `expand_coverage(hit_reps)`, `coverage_stats(hit_reps)`, `bin_label(bt)`, `report()` |
| `Orbit` | `id`, `members`, `representative`, `size()` |

**Orbit algorithm:** BFS over generators + inverses only — O(k × |B|) where
k = generator count, |B| = total bin count. Does not enumerate the full group.

**Cache invalidation:** `add_coverpoint()` calls `_invalidate_all()` (resets
group + orbits). `add_symmetry()` calls `_invalidate_orbits()` only (preserves
group). These are kept separate to avoid wiping the group mid-construction.

### `rtl/generate_array.py`

| Field | Type | Description |
|-------|------|-------------|
| `parent_module` | `str` | Enclosing module name |
| `block_label` | `str \| None` | Named `begin : label` block |
| `module_type` | `str` | Instantiated module |
| `instance_base` | `str` | Instance name inside the loop |
| `genvar` | `str` | Loop variable |
| `bound_kind` | `"literal" \| "param"` | Whether bound is a constant or parameter |
| `bound_value` | `int \| None` | For literal bounds |
| `bound_param` | `str \| None` | Parameter name for param bounds |
| `param_default` | `int \| None` | Default scraped from module header |

`count(param_overrides)` resolves in priority: override → default → None.

### `rtl/extractor.py`

`RtlExtractor` — fluent builder.

```python
ext = (RtlExtractor()
       .add_file("rtl/top.sv")
       .add_param("N_LANES", 8))
arrays = ext.extract()     # list[GenerateArray], stable sort by (file, line)
print(ext.report())
```

**Detected pattern:**

```systemverilog
for (genvar i = 0; i < <bound>; i++) begin [: <label>]
    <module_type> [#(...)] <instance_name> (...);
end
```

**Not currently detected:** if-generate, non-unit stride, non-zero start,
multiple module types in one generate block.

**pyslang usage:** Parse-only (`SyntaxTree.fromFile`), no elaboration. The
parameter default is scraped from the CST's `ParameterPortList` →
`ParameterDeclaration` → `Declarator` → `EqualsValueClause` path.

### `rtl/bridge.py`

`BinSpaceBuilder` — wires CoverSpecs onto GenerateArrays.

```python
results = (BinSpaceBuilder(arrays)
           .cover("state", ["IDLE","ACTIVE","STALL","ERROR"], module_type="rx_lane")
           .cover_value_classes("data")
           .build(param_overrides={"N_LANES": 8}))
# → list[BridgeResult]
```

**Block permutation construction:** For n instances × s signals, coverpoints
are laid out as `[inst[0].sig[0], inst[0].sig[1], ..., inst[n-1].sig[s-1]]`.
Symmetry generators swap entire blocks of size s. Two generators suffice for
Sₙ regardless of n: `block_swap(0,1)` and `block_cycle()`.

### `coverage/result.py`

`CoverageResult` — raw simulation output.

```python
r = CoverageResult.from_hits([
    (("IDLE", "ACTIVE", "STALL"), 7),
    (("ERROR", "ERROR", "ERROR"), 1),
], run_id="run_042", simulator="questa")

r = CoverageResult.from_file("sim_output.json")
r.save("result.json")
```

### `coverage/expander.py`

`ExpansionEngine` — stateless after construction, `expand()` may be called
repeatedly.

```python
engine = ExpansionEngine(bin_space)
er = engine.expand(coverage_result)
er = engine.merge_and_expand([run1, run2, run3])

print(er.report())
print(er.class_coverage_pct())
print(er.is_complete())
d = er.to_dict()   # machine-readable JSON-safe dict
```

**Non-rep hit policy:** Any hit bin (not just the designated representative)
propagates to its full orbit. Makes the tool compatible with unmodified
simulation results.

**Multi-hit count policy:** If multiple members of the same orbit are hit with
different counts, the maximum is propagated to all members.

**`merge_and_expand`:** Hits from multiple runs are summed per label-tuple
before expansion. Enables incremental regression closure.

---

## 6. Key Design Decisions

### D-01 — Parse-only RTL analysis (no elaboration)

**Decision:** Use `pyslang.syntax.SyntaxTree.fromFile` (CST, parse-only) rather
than the elaborated AST via `pyslang.driver.Driver` + `Compilation`.

**Rationale:** Elaboration requires a consistent compilation unit and resolves
all parameters. Parse-only runs on partial/dirty source trees, is faster, and
has no dependency on tool configuration. Parameter defaults are scraped directly
from the CST.

**Consequence:** Parameter-based bounds with no default and no `add_param()`
override produce `count() = None` and are skipped with a warning. User must
supply `add_param()` for parameters with no source default.

---

### D-02 — Symmetry group generated by two generators (not full enumeration)

**Decision:** Sₙ is generated by `transposition(0,1)` + `n-cycle`. Orbit BFS
uses `generators_and_inverses()` only, never enumerating the full group.

**Rationale:** |S₈| = 40,320. Enumerating all elements to compute orbits would
multiply work by the group order. BFS over generators + inverses is O(k × |B|),
linear in the bin space.

**Consequence:** `SymmetryGroup.order()` still enumerates (for reporting). For
very large groups this can be slow; orbit computation is unaffected.

---

### D-03 — Block permutation for multi-signal symmetry

**Decision:** When multiple signals are declared per instance, coverpoints are
laid out as interleaved blocks `[inst[i].sig[j]]` and symmetry acts on whole
blocks, not individual coverpoints.

**Rationale:** Swapping two instances means swapping all their signals together.
A naive per-coverpoint permutation would mix signals across instance boundaries,
producing an incorrect (larger) symmetry group.

---

### D-04 — Canonical JSON as the coverage interchange format

**Decision:** Define a Dabih-native JSON schema rather than reading UCDB,
VCD, or simulator-proprietary formats directly.

**Rationale:** UCDB is a proprietary binary format requiring Questa/VCS APIs
not available in a standalone Python tool. The JSON format is trivially
emittable from UVM (`$fwrite`), manually constructible for testing, and
simulator-agnostic.

**Consequence:** An adapter layer from UCDB text exports (via `vcover report`)
is a future work item. That adapter would produce `CoverageResult` objects from
Questa/VCS text dumps without touching the core engine.

---

### D-05 — Any hit bin implies its orbit (not just the representative)

**Decision:** `ExpansionEngine.expand()` accepts hits on any bin in the space,
not only the designated representative.

**Rationale:** A simulation run against an uncompressed model, or one that
exercises non-representative bins incidentally, should still benefit from
symmetry expansion. Requiring only the representative to be hit would make the
tool fragile against testbench variations.

---

### D-06 — BFS enumeration ceiling acknowledged as a design constraint

**Decision:** The current orbit engine enumerates all members of the bin space
explicitly. This sets a practical ceiling at approximately 1M total bins in pure
Python.

**Consequence:** Multi-signal × high-lane-count cross-coverage (e.g. 2 signals
× 8 lanes at 4 bins each = 16M bins) exceeds this ceiling. Idea E (symbolic
orbit engine via Burnside/Pólya) is the resolution path. This is a known,
documented limitation, not a bug.

---

### D-07 — Verification completeness guarantee is conditional on Idea D

**Decision:** Dabih's coverage guarantees are conditional on the declared
symmetry group being a valid symmetry of the DUV. The tool does not verify
this claim internally in Ideas A–C.

**Rationale:** Symmetry validity is a design property, not a coverage property.
Verifying it requires formal tools (Idea D).

**Consequence:** Idea D is confirmed as a core requirement for tape-out sign-off
quality. Ideas A–C are useful and correct in the common case (clean generate-for
loops with no lane-specific behavior), but the formal guarantee requires Idea D.

**Tool decision (OQ-01 resolved):** Two-tier approach —
SpyGlass (`vc_spyglass/2024.09-SP2`) for structural pre-check, Questa Formal
(`questa-formal/2024.3_1`) for SVA behavioral proof. Both tools confirmed
present in the target environment. Implementation ready to begin.

---

## 7. Known Constraints & Limitations

| # | Constraint | Impact | Resolution Path |
|---|------------|--------|-----------------|
| L-01 | BFS enumeration ceiling ~1M bins | Multi-signal × many lanes infeasible | Idea E (symbolic engine) |
| L-02 | Parse-only RTL: no elaboration | Parameterized bounds without defaults need `add_param()` | Acceptable; well-documented |
| L-03 | `generate for` only — not `generate if` | If-generate symmetry not detected | Future extractor work |
| L-04 | Unit stride, zero-start loops only | Non-standard loop patterns ignored | Future extractor work |
| L-05 | Single module type per generate block | Multi-type blocks ignored | Rare in practice |
| L-06 | No UCDB binary reader | Adapters require `vcover report` or `urg` text output — binary UCDB not parsed directly | By design; text output requires no EDA API |
| L-07 | ~~Symmetry claim not formally verified~~ | ~~Incorrect symmetry silently under-covers~~ | **Idea D ✅ Done** — SpyGlass pre-check + Questa Formal SVA proof |
| L-08 | Pure Python BFS — not parallelized | Large spaces are slow (not OOM, just slow) | Idea E; or C extension |

---

## 8. Outstanding Decisions & Open Questions

### OQ-01 — Idea D: formal property target  ✅ Decided

**Decision:** Two-tier emission — SpyGlass structural pre-check (Tier 1)
followed by Questa Formal SVA proof (Tier 2).

**Tool inventory confirmed from environment survey (May 2026):**

| Tool | Available Versions | Role |
|------|--------------------|------|
| `mentor/questa-formal` | 2020.4 → **2026.1** (default: 2024.3_1) | Tier 2 — SVA formal proof |
| `synopsys/vc_spyglass` | 2024.09-SP2 (default) | Tier 1 — structural pre-check |
| `synopsys/spyglass` | 2017 → 2024.09-SP2 | Tier 1 — structural pre-check (legacy) |
| `cadence/conformal` | 19.x → 24.20 | ❌ Equivalence checker — out of scope |
| `synopsys/vcstatic` | 2021.09 → 2024.09-SP2 | ❌ Automated bug hunter, no user SVA |
| `realintent` | 2022.A_v2 | ❌ CDC/RDC analysis — not symmetry |

**Why VCStatic is out of scope:** VCStatic performs automated structural
bug-hunting and unreachability analysis without user-written assertions.
It is not VC Formal and does not support user-defined SVA property proving.

**Why Conformal is out of scope:** Equivalence checker between two design
representations (RTL vs. netlist). Cannot prove behavioral properties.

---

**Tier 1 — SpyGlass structural pre-check**

Fast, automatic, no SVA authorship required. Dabih emits a SpyGlass rule
file (`.sgdc` or constraint file) that verifies structural conditions
necessary for the symmetry claim to be plausible:

- All instance signals in the generate array have identical fanout
- No lane-specific clock domain assignments
- No asymmetric reset connectivity
- No per-index parameter differentiation visible at port level

SpyGlass runs in minutes. Catches obvious structural violations before
committing to a full formal run. Output: pass/fail + violation list.

Target: `synopsys/vc_spyglass/2024.09-SP2`

---

**Tier 2 — Questa Formal SVA proof**

Authoritative behavioral proof. Dabih emits:

1. **Property wrapper** (`.sv`) — a SystemVerilog module that instantiates
   the DUV and asserts the symmetry properties for all declared instance
   pairs:

```systemverilog
// Auto-generated by Dabih — do not edit
// Symmetry claim: S4 on instances [0,1,2,3] of rx_lane

module dabih_symmetry_check (
    input logic clk, rst,
    // ... DUV ports
);
    // Instantiate DUV
    dut u_dut (...);

    // Symmetry properties: all pairs (i,j) in S4
    property lane_0_1_sym;
        @(posedge clk) disable iff (rst)
        (in[0] === in[1]) |-> ##[1:DEPTH] (out[0] === out[1]);
    endproperty
    assert property (lane_0_1_sym)
        else $error("Symmetry violated: lane 0 vs lane 1");

    // ... all other pairs
endmodule
```

2. **Questa Formal script** (`.tcl`) — loads the property wrapper, sets
   the verification depth, runs the proof, and saves results:

```tcl
# Auto-generated by Dabih
questa_formal compile -work dabih_sym \
    -sv dabih_symmetry_check.sv [glob rtl/*.sv]
questa_formal verify -init dabih_sym.init \
    -timeout 3600 \
    -proof_depth 20
```

Target: `mentor/questa-formal/2024.3_1` (default), compatible with 2026.1.

---

**Dabih Idea D emission API (planned):**

```python
from dabih.formal import emit_symmetry_check

# From an existing BinSpace with declarations
emit_symmetry_check(
    bin_space    = bs,
    dut_module   = "rx_lane",
    dut_ports    = {"in": "data_in", "out": "data_out", "clk": "clk"},
    proof_depth  = 20,
    out_dir      = "formal/",
    tool         = "questa_formal",   # "questa_formal" | "spyglass"
)
# Writes: formal/dabih_symmetry_check.sv
#         formal/dabih_questa_formal.tcl
#         formal/dabih_spyglass.sgdc
```

**Status:** 🔲 Planned — tool decision resolved, unblocked for
implementation. Next step: build `dabih/formal/` module.

---

### OQ-02 — Idea E: Burnside vs Pólya vs Möbius  ✅ Resolved

**Decision:** All three implemented in priority order within `SymbolicOrbitEngine`:

1. **Pólya** (primary) — closed-form C(n+K−1,n) for any Sₙ group (direct or block). O(1), no enumeration. Selected when `is_full_sn=True` in the symmetry profile.
2. **Burnside** (fallback) — `(1/|G|) Σ_{g∈G} K^{c_block(g)}` for partial symmetry groups with `|G|` ≤ 500,000. Requires full group enumeration but never touches the bin space.
3. **Möbius** (boundary) — raises `SymbolicLimitError` with a diagnostic message. Unreachable in practice for hardware verification designs (all real cases are Sₙ or small partial-symmetry subgroups).

**Bug fixed during implementation:** A Z₂ group (order 2) was being misclassified as S₂ (also order 2) without the `_is_block_permutation()` validation check. The profile fallback also incorrectly set `k_per_signal` to all coverpoint bin counts rather than a single uniform value, causing Burnside to compute `K^{c(g)}` with K equal to the full bin-space size rather than the per-position bin count. Both bugs caught by 18-combination BFS vs symbolic parametric test sweep.

**84 new tests. Profile detection: declarations → hint → heuristic priority order.**

---

### OQ-03 — CLI interface design  ✅ Done

**Decision:** A `dabih` CLI implemented as five commands in `dabih/cli.py`,
registered as an entry point in `pyproject.toml`.

**Commands built:**

```
dabih scan   <files...> [--param N=V ...] [--json]
    Idea A: parse RTL, print generate-for extraction report.

dabih spec   <files...> [--param N=V ...] [--cover MODULE SIGNAL BIN ...]
             [--module MODULE] --out spec.json
    Ideas A+B: build compressed coverage spec, write to JSON.
    Serialisation includes orbit count, representatives, declarations.

dabih expand <result.json> [result2.json ...] --spec spec.json
             [--html report.html] [--json] [--no-exit-code] [--max-holes N]
    Idea C: expand simulation results. Exit 1 when incomplete (CI hook).
    Multiple result files are merged before expansion.

dabih report <result.json> [result2.json ...] --spec spec.json
             --out report.html [--title TITLE]
    Idea C + Visual: generate self-contained HTML sign-off report.

dabih verify --spec spec.json --dut MODULE --inst "pattern[{i}].u"
             --clk CLK [--rst RST] [--rst-active-low]
             --input PORT ... --output PORT ... [--rtl FILE ...]
             [--depth N] [--tool all|questa_formal|spyglass]
             [--out-dir DIR] [--name SUFFIX] [--param N=V ...]
    Idea D: emit SpyGlass SGDC + TCL (Tier 1) and/or Questa Formal
    SVA wrapper + TCL (Tier 2).
```

**BinSpace serialisation (`dabih/core/spec_io.py`):**
`dump_bin_space()` / `load_bin_space()` round-trip through JSON preserving
orbit count, coverpoints, bin names, and symmetry declarations. The spec
file is the contract between `dabih spec` and all downstream commands.

**CI integration:** `dabih expand` returns exit code 1 on incomplete
coverage and 0 on complete — enables `make coverage && dabih expand ...`
workflows. Suppressed with `--no-exit-code`.

**57 new tests. 470 total — all pass.**

**Proposed command surface:**
```
dabih scan   <files...> [--param N=8 ...]
    # Idea A: parse RTL, print generate-for extraction report

dabih spec   <files...> [--param N=8 ...] [--cover signal bins ...] --out spec.json
    # Idea A+B: emit compressed coverage spec (representatives + BinSpace metadata)

dabih expand <result.json> <spec.json> [--merge result2.json ...]
    # Idea C: expand simulation results, print report, optionally write HTML

dabih report <result.json> <spec.json> --out report.html
    # Idea C + Visual Option 2: generate full HTML sign-off report

dabih verify <files...> [--tool symbiyosys|jaspergold]
    # Idea D: emit formal symmetry-checking properties
```

**Design constraints:**
- All commands must be usable with no Python import knowledge
- `--out` flag controls file output; stdout used for plain-text report when omitted
- `dabih expand` and `dabih report` accept multiple `--merge` files for multi-run regression
- Error messages must name the offending RTL file and line when extraction fails
- Exit code 1 when coverage is incomplete (for CI integration)

**Status:** 🔲 Planned — not yet started. Blocked on nothing; next in queue
after OQ-04 adapter work. Target: `argparse` or `click`-based entry point
in `dabih/cli.py`.

---

### OQ-04 — Simulator adapter  ✅ Decided

**Decision:** Both Questa and VCS are in scope. Implement two adapters
that each produce a `CoverageResult` from native simulator output, without
requiring the Dabih JSON format in the testbench.

---

**Adapter A — Questa (`vcover` text report)**

Input: text output of `vcover report -details -cvg <ucdb_file>`

Questa's `vcover report` emits a structured text format with covergroup
headers, coverpoint names, bin names, and hit counts.  The adapter parses
this into a `CoverageResult`.

Key parsing targets:
```
Covergroup: <covergroup_name>
  Coverpoint: <cp_name>
    Bin <bin_name> Count= <n>
```

Usage:
```python
from dabih.adapters.questa import from_vcover_report
cr = from_vcover_report("vcover_output.txt", covergroup="lane_cross_cg")
```

Or from shell output directly:
```python
cr = from_vcover_report_text(vcover_stdout, covergroup="lane_cross_cg")
```

---

**Adapter B — VCS (`urg` report)**

Input: `urgReport/dashboard.html` or `urgReport/*/coverage.txt` produced
by `urg -dir simv.vdb -report urgReport`.

VCS's `urg` tool produces both HTML and text coverage summaries.  The text
format is the cleaner parse target.

Key parsing targets:
```
COVERGROUP COVERAGE:
  Covergroup: <name>
    Coverpoint: <cp_name>
      bin <bin_name>  <hit_count>/<at_least>
```

Usage:
```python
from dabih.adapters.vcs import from_urg_report
cr = from_urg_report("urgReport/", covergroup="lane_cross_cg")
```

---

**Shared adapter interface:**

Both adapters follow the same contract:
```python
def from_<tool>_<format>(
    path: str | Path,
    covergroup: str,
    coverpoints: list[str] | None = None,
) -> CoverageResult:
    ...
```

`covergroup` filters to the target covergroup by name.
`coverpoints` optionally filters to a specific ordered subset of coverpoints —
needed when the simulator covergroup contains more signals than the Dabih
BinSpace was built for.

**Implementation note:** Both adapters are pure text parsers with no
simulator API dependency.  They run on any machine that has the report
file — no EDA license required at post-processing time.

**Package location:** `dabih/adapters/questa.py`, `dabih/adapters/vcs.py`

**Status:** ✅ Done — both adapters built and tested.
`dabih/adapters/questa.py` and `dabih/adapters/vcs.py`.
Questa adapter first per plan. **49 new tests.**
Cross-adapter consistency tests confirm both simulators produce identical
`CoverageResult` contents from equivalent data. Both adapters verified to
feed `ExpansionEngine`, `SymbolicExpansionEngine`, and `merge_and_expand`
without modification. `CoverageResult` round-trips cleanly through JSON.

---

### OQ-05 — Partial Symmetry API  ✅ Resolved

**Decision:** Three new methods on `BinSpace`, all translating to existing
`add_symmetry()` generators internally:

```python
# Sₖ on an arbitrary subset of instances (most common case)
bs.add_instance_symmetry(instance_indices=[1, 2], block_size=2)

# Zₙ cyclic symmetry on a ring of instances
bs.add_cyclic_symmetry(instance_indices=[0, 1, 2, 3])

# Z2×Z2×... independent pairwise symmetry
bs.add_pairwise_symmetry(pairs=[(0, 1), (2, 3)])
```

`add_full_lane_symmetry(n)` now delegates to `add_instance_symmetry` —
fully backward compatible, orbit counts identical, now also stores a
structured declaration.

All three methods store a `_symmetry_declarations` entry on the BinSpace
with `type`, `instance_indices` / `pairs`, `block_size`, and `group` name.
This structured intent log is consumed by:
- `SymbolicOrbitEngine` (profile detection: full instance → Pólya; partial,
  cyclic, pairwise → Burnside)
- Idea D (formal verification pass — generates named properties per
  declaration rather than reverse-engineering from raw generators)

Validation: `block_size < 1`, out-of-range instance indices, and
`block_size` not dividing coverpoint count all raise `ValueError`.

**58 new tests. 271 total — all pass.**

---

### OQ-06 — Coverage provenance tracking in merge  ✅ Done

**Decision and implementation:** Provenance tracking is opt-in via a
`track_provenance=True` parameter on `merge_and_expand()` and `expand()`.
Default behavior (merge without provenance) is unchanged — zero overhead
for standard regression flows.

**API surface (both BFS and Symbolic engines):**

```python
# Standard merge — no overhead (default)
er = engine.merge_and_expand([run1, run2, run3])

# Merge with provenance tracking
er = engine.merge_and_expand([run1, run2, run3], track_provenance=True)

er.has_provenance                       # → True
er.orbit_run_ids(rep_label_tuple)       # → ["seed_042", "seed_1337"]
er.coverage_count(rep_label_tuple)      # → int
er.single_coverage_orbits()             # → list of reps covered by 1 run
er.coverage_histogram()                 # → {1: 14, 2: 31, 3: 102, ...}
er.fragile_orbits(threshold=2)          # → orbits covered by < threshold runs
```

**`to_dict()` provenance sub-dict** (when tracking enabled):
```json
"provenance": {
  "histogram": {"1": 14, "2": 31, "3": 102},
  "fragile_count": 14,
  "fragile_reps": [["IDLE","IDLE","IDLE","IDLE"], ...],
  "well_covered": 102
}
```

**`report()` confidence section** (when tracking enabled):
```
Coverage confidence  (provenance tracking)
  Single-seed orbits  (fragile)  :       14  ⚠
  Two-seed orbits                :       31
  Well-covered (≥3 seeds)        :      102  ✓
  Histogram  (seeds → orbits)    :  1×14  2×31  3×102
```

**CLI:** `dabih expand --provenance` enables tracking on the merge path.

**Implementation note:** The provenance dict keys on orbit *representatives*
(canonical BinTuples), not arbitrary member bins.  Non-representative hits
are canonicalised before attribution — so a simulation hitting a non-rep
member of an orbit is still correctly attributed to that orbit's key.

**43 new tests. 513 total — all pass.**

**Rationale:**
In a regression of N seeds, an orbit covered by only one seed is a
fragile coverage claim — that seed may be environment-sensitive, non-
deterministic, or rely on a specific sequence that other seeds avoid.
Provenance tracking surfaces these single-coverage orbits so they can be
flagged for re-verification or additional targeted stimulus.

**Proposed API:**

```python
# Standard regression merge — no provenance overhead (default)
er = engine.merge_and_expand([run1, run2, run3])

# Merge with provenance tracking (opt-in)
er = engine.merge_and_expand([run1, run2, run3], track_provenance=True)

# Provenance queries on the result
er.orbit_run_ids(rep_label_tuple)   # → ["seed_042", "seed_1337"]
er.coverage_count(rep_label_tuple)  # → int (how many runs covered this orbit)
er.single_coverage_orbits()         # → list of reps covered by exactly 1 run
er.coverage_histogram()             # → dict {count: n_orbits} — distribution
er.fragile_orbits(threshold=2)      # → orbits covered by < threshold runs
```

**ProvenanceResult / extended ExpansionResult:**

Two implementation options — to be decided at build time:

Option P1 (simpler): Add provenance fields directly to `ExpansionResult`
and `SymbolicExpansionResult` when `track_provenance=True`. Fields are
`None` when provenance was not requested.

Option P2 (cleaner): A separate `ProvenanceExpansionResult` subclass that
wraps the standard result and adds provenance attributes.

Lean toward P1 to avoid proliferating result types. The provenance data
is a `dict[BinTuple, list[str]]` mapping each covered orbit's canonical
representative to the list of `run_id` strings that contributed a hit.

**Report output:**

When provenance is tracked, `report()` and `render_html_report()` should
add a coverage confidence section:

```
Coverage Confidence (provenance)
  Single-seed orbits    :       14   ⚠  (fragile — only 1 run)
  Two-seed orbits       :       31
  Well-covered (≥3)     :      285   ✓
  Coverage histogram    :  1×14  2×31  3×58  4×102  ...
```

And the HTML report dashboard should add a "Confidence" tab showing the
histogram as a bar chart and the fragile orbit list.

**Relationship to standard merge workflow:**

The standard team regression workflow is:
1. Run N seeds in parallel
2. `merge_and_expand([run1, run2, ..., runN])` — close coverage
3. Check `is_complete()` — if not, identify holes and add targeted stimulus

Provenance adds a step 3a:
3a. Check `fragile_orbits(threshold=2)` — flag orbits that need more seeds

This is additive, not a replacement. The merge is still the primary
aggregation operation.

**Status:** 🔲 Planned — confirmed needed. Build after OQ-04 adapters,
since the most natural use of provenance is after merging real simulator
results from multiple regression seeds.

---

### OQ-08 — Provenance in visual surfaces  ✅ Done

**HTML Coverage Report** (`dabih/reporting/html_report.py`):
- `_extract_stats()` now extracts provenance from `er.has_provenance`,
  `er.coverage_histogram()`, `er.fragile_orbits()`, and `er.single_count`
  into a `provenance` sub-dict within the injected data JSON.
- New **◐ Confidence** nav item added to the sidebar — hidden via
  `display:none` when `D.provenance` is null, shown automatically when
  provenance data is present.
- New `<section id="confidence">` with:
  - Four summary stat cards: single-seed, two-seed, well-covered (≥3),
    total fragile count
  - Seed coverage histogram as horizontal inline bars (colour-coded:
    amber for 1-seed, dim for 2-seed, green for ≥3-seed)
  - Searchable fragile orbit chip grid
- `filterFragile()` function for live search on fragile representatives.
- No API changes — section is entirely data-driven from `er.has_provenance`.

**Interactive Dashboard** (`web/dashboard.jsx`):
- New **◐ Confidence** tab added to the sidebar nav list.
- Confidence tab content renders the same three panels as the HTML report:
  stat cards, histogram bars, fragile orbit chip grid.
- `DEMO_RUNS[2]` (seed_9999) carries synthetic provenance data so the
  Confidence tab renders immediately without real simulation data.
- Shows a clear "no provenance" state when data is absent.

---

### OQ-09 — CLI simulator adapter flags  ✅ Done

**`dabih expand`** and **`dabih report`** now accept simulator reports
directly. Positional `results` changed from `nargs="+"` to `nargs="*"`.

```
dabih expand  --questa-report vcover_output.txt --spec spec.json
dabih expand  --vcs-report    urgReport/coverage.txt --spec spec.json
dabih report  --questa-report vcover.txt --covergroup rx_cross_cg \
              --spec spec.json --out report.html

# Multiple files → merge before expansion
dabih expand  --questa-report seed_042.txt --questa-report seed_1337.txt \
              --spec spec.json

# Mixing Questa and VCS runs
dabih expand  --questa-report questa.txt --vcs-report vcs.txt \
              --spec spec.json
```

**`_load_results(args)`** helper added to `cli.py` — detects adapter vs
JSON path, calls `from_vcover_report()` / `from_urg_report()`, enforces
mutual exclusion with positional JSON files, prints a `✓` line per loaded
report. Shared between `cmd_expand` and `cmd_report`.

**Bugs fixed during implementation:**
- `argparse` `add_argument_group` is cosmetic only; arguments must be
  added directly to the subparser to be parsed correctly.
- `action="append"` with `default=[]` doubles the list if the flag is
  not used; fixed to `default=None` with `or []` in `_load_results`.

**16 new OQ-09 tests. 528 total — all pass.**

**HTML Coverage Report additions:**
- Confidence tab in the sidebar navigation
- Histogram bar chart (seeds → orbit count) rendered as inline SVG bars
- Fragile orbits list: representatives covered by only one seed, with
  orbit size and suggested action ("add targeted stimulus")
- `render_html_report()` automatically shows the Confidence tab when
  `er.has_provenance` is True; hidden otherwise (no API change needed)

**Dashboard additions:**
- New "Confidence" tab alongside Coverage, Holes, Run History
- Seed-coverage histogram rendered as a horizontal bar chart per seed count
- Fragile orbit browser with search (same pattern as Holes tab)
- Per-run provenance detail: click a run in Run History to see which orbits
  it uniquely contributes

**Status:** 🔲 Planned — no blocking dependencies.

---

### OQ-09 — CLI simulator adapter flags

**Decision:** Wire the Questa and VCS adapters directly into `dabih expand`
and `dabih report` so existing simulation flows need no Python code changes.

**Proposed flags:**
```
dabih expand  --questa-report vcover_output.txt  --spec spec.json
dabih expand  --vcs-report    urgReport/coverage.txt  --spec spec.json
dabih report  --questa-report vcover_output.txt  --spec spec.json --out r.html

# With covergroup selection (required when file has multiple covergroups)
dabih expand  --questa-report vcover.txt  --covergroup rx_lane_cross_cg \
              --spec spec.json
```

**Implementation:**
- `cmd_expand` and `cmd_report` detect `--questa-report` / `--vcs-report`
  as mutually exclusive alternatives to positional `results` files
- Parse with the existing `from_vcover_report()` / `from_urg_report()`
  adapters, then proceed identically to the JSON path
- `--covergroup` flag added to both commands for multi-cg files
- Multiple `--questa-report` or `--vcs-report` flags trigger merge

**Status:** 🔲 Planned — adapters already built (OQ-04); this is CLI
wiring only.

---

### OQ-10 — Real RTL end-to-end validation

**Decision:** Run the full Dabih pipeline on a real design file from the
ASIC/FPGA development environment.

**Goals:**
- Confirm that `dabih scan` correctly detects real generate-for patterns
  (multi-lane interfaces, memory controllers, pipeline arrays)
- Confirm that pyslang parses real SV without errors
- Measure actual compression ratios on real designs
- Identify any RTL patterns the extractor misses (edge cases for Idea A)
- Produce a real coverage spec and validate it against simulation output

**Process:**
1. Select a candidate design with at least one generate-for array
2. Run `dabih scan` — verify extraction report
3. Run `dabih spec` with appropriate `--cover` specs
4. Run simulation (or use existing coverage DB) → adapter → `dabih expand`
5. Compare Dabih orbit count against raw covergroup bin count

**Constraints:**
- Any IP-sensitive RTL stays in the local environment; only the Dabih
  outputs (spec JSON, compression ratio, report) need to be reviewed
- pyslang parse errors should be filed as issues against the extractor

**Status:** 🔲 Planned — requires access to internal RTL. No Dabih code
changes expected; this is a validation exercise that may surface edge cases.

---

### OQ-11 — Idea D on a real DUT

**Decision:** Write a `DUTSpec` for a real generate-for array and run the
SpyGlass + Questa Formal pipeline to formally verify (or falsify) the
symmetry claim.

**Goals:**
- Produce a real `dabih_sym_<name>.sv` and `dabih_questa_formal.tcl`
  from a real design
- Run SpyGlass Tier 1 structural pre-check — confirm no fanout or clock
  domain violations
- Run Questa Formal Tier 2 SVA proof — confirm PROVEN or get a falsifying
  counterexample
- If PROVEN: the first formally-verified symmetry claim using Dabih is
  established — coverage compression is sign-off quality for that design
- If FALSIFIED: the counterexample identifies the specific structural
  asymmetry (e.g. lane 0 special-casing) — fix the RTL or revise the
  declaration

**Process:**
1. Identify a clean generate-for array (confirmed structurally uniform)
2. Write `DUTSpec` with correct port names, hierarchy pattern, proof depth
3. Run `dabih verify --spec spec.json --dut ... --inst ... --clk ...`
4. Run SpyGlass: `vc_spyglass -tcl dabih_spyglass.tcl`
5. Run Questa Formal: `questa_formal -do dabih_questa_formal.tcl`
6. Review results — PROVEN / FALSIFIED / timeout

**Proof depth guidance:** Start at 20 cycles. If UNKNOWN (neither proven
nor falsified), increase depth by 10 and retry. Most structural symmetry
proofs close within 30–50 cycles for pipeline depths ≤ 8.

**Status:** 🔲 Planned — requires access to internal RTL and EDA tool
licenses (Questa Formal, vc_spyglass). Blocked only on RTL selection and
environment setup.

**Assets received (May 2026):**

| Asset | File | Used in |
|-------|------|---------|
| Favicon (rounded icon) | `Favicon_2.png` | All three surfaces — `<link rel="icon">` + nav header |
| Square dark banner | `Square_Banner_Dark.png` | HTML Coverage Report sidebar |
| Long banner with infographic | `Long_Banner_-_Detail.png` | Landing page hero section |
| Long banner (alt detail) | `Long_Banner_Dark_-_Concept.png` | Landing page (alternate) |
| Square banner concept | `Square_Banner_Dark_-_Concept.png` | Reference |

**Brand identity extracted from assets:**

| Token | Value | Role |
|-------|-------|------|
| Background | `#04060e` | Deep space black |
| Surface | `#090c18` | Card / panel background |
| Primary accent | `#00c8ff` | Cyan — "Cut the Redundant", gauges, borders |
| Secondary accent | `#a855f7` | Purple — "Keep What Matters", orbital ring |
| Midpoint | `#6366f1` | Indigo — gradient bridge |
| Alert | `#eab308` | Yellow — Essential Set target icon |
| Wordmark | `#ffffff` | "Dabih" in bold |

**Tagline:** *Cut the Redundant. Keep What Matters.*

**Logo concept:** Neon cleaver orbited by a blue-to-purple arc (the orbital
ring), superimposed on a bright 8-pointed star — representing precision
cutting (compression) through a vast design space (the star field).

**Integration applied to all three surfaces:**

HTML Coverage Report (`dabih/reporting/html_report.py`):
- All 6 CSS token values updated to brand palette
- Sidebar logo: embedded `Square_Banner_Dark.png` as base64 data-URI
- Favicon: embedded `Favicon_2.png` as base64 in `<link rel="icon">`
- Progress bar gradients: cyan → light-cyan and purple → light-purple
- Gauge strokes: cyan for class coverage, purple for bin coverage

Landing page (`web/landing.html`):
- All 6 CSS token values updated
- Nav logo: favicon embedded alongside "Dabih" wordmark
- Hero: long banner image displayed above the hero text block
- Scaling table bar gradient: cyan → purple
- Test count updated: 513 passing

Interactive Dashboard (`web/dashboard.jsx`):
- All `T` token hex values updated to brand palette
- Header: favicon `<img>` replacing the dot + text pattern
- All gradient fills updated: bars, gauges, merged progress
- Animation pulse shadow: `#00c8ff` glow
- `@keyframes pulse` updated for cyan glow

---

## 9. Test Coverage Summary

| Suite | File | Tests | Status |
|-------|------|-------|--------|
| Idea B — Core orbit engine | `tests/test_core.py` | 41 | ✅ All pass |
| Idea C — Coverage post-processor | `tests/test_coverage.py` | 43 | ✅ All pass |
| Idea A — RTL extractor + bridge | `tests/test_rtl.py` | 45 | ✅ All pass |
| Idea E — Symbolic orbit engine | `tests/test_symbolic.py` | 84 | ✅ All pass |
| OQ-05 — Partial symmetry API | `tests/test_partial_symmetry.py` | 58 | ✅ All pass |
| OQ-04 — Questa + VCS adapters | `tests/test_adapters.py` | 49 | ✅ All pass |
| Idea D — Formal emission | `tests/test_formal.py` | 93 | ✅ All pass |
| OQ-03 / OQ-09 — CLI + simulator-report flags | `tests/test_cli.py` | 72 | ✅ All pass |
| OQ-06 — Coverage provenance | `tests/test_provenance.py` | 43 | ✅ All pass |
| **Total** | | **528** | **✅ All pass** |

**test_core.py:** Permutation algebra, group closure, group order (S2–S5),
orbit partition correctness, orbit count formula (multiset C(n+k−1,k)),
compression ratio, coverage expansion, edge cases (single bin, no symmetry,
cache invalidation).

**test_rtl.py:** Literal bounds, parameter bounds, block label extraction,
parent module attribution, multi-file scan, multi-module-per-file,
non-generate instance filtering, unresolved parameters, missing files,
block permutation orbit counts, compression scaling with lane count,
bridge report formatting.

**test_coverage.py:** JSON round-trip, file load/save, hit count, partial
coverage, full coverage, zero coverage, non-rep hit propagation, unresolved
labels, wrong arity, merge across runs, overlapping run count summation,
holes report, `to_dict` structure, `is_complete`, integration test (RTL →
BinSpace → ExpansionEngine end-to-end), incremental regression closure.

---

## 10. Canonical JSON Format

The Dabih coverage result format. Designed to be emittable from a UVM testbench
with `$fwrite` calls, constructible by hand for debugging, and simulator-agnostic.

```json
{
  "run_id"     : "string — optional, identifies the simulation run",
  "simulator"  : "string — optional, e.g. questa, vcs, xcelium",
  "timestamp"  : "string — optional, ISO-8601",
  "covergroup" : "string — optional, for documentation only",
  "hits" : [
    {
      "bin"   : ["label0", "label1", "...labelN"],
      "count" : 7
    }
  ]
}
```

**Rules:**
- `bin` is an ordered list of bin label strings, one per coverpoint in the
  target `BinSpace`. Order must match coverpoint insertion order.
- Only hit bins need appear. Omitted bins are implicitly zero-hit.
- `count` is the raw simulator hit count (integer ≥ 1).
- Bins present in the file but not resolvable in the `BinSpace` are reported
  as unresolved and do not silently drop.

**Minimal valid file:**
```json
{ "hits": [{ "bin": ["IDLE", "ACTIVE"], "count": 1 }] }
```

---

## 11. Glossary

| Term | Definition |
|------|------------|
| **Bin** | A single point in a coverage space, identified by a tuple of values (one per coverpoint). |
| **BinSpace** | The full Cartesian product of coverpoint bin sets; the object on which the orbit engine operates. |
| **BinTuple** | A tuple of bin indices (integers), the internal representation of a bin. |
| **Block permutation** | A permutation that acts on groups of coverpoints (one group per instance) as a unit, preserving signal order within each instance. |
| **Compression ratio** | `total_bins / orbit_count`. Higher is better. |
| **CoverageResult** | Dabih's portable coverage output format; the set of bins hit during simulation with their hit counts. |
| **Coverpoint** | One observable signal dimension with a finite set of named bins. |
| **Equivalence class** | A set of bins that are behaviorally equivalent under the declared symmetry group; also called an orbit. |
| **ExpansionResult** | The output of the post-processor: full implied coverage map across the entire bin space. |
| **GenerateArray** | A `generate-for` loop that instantiates N copies of one module; the atomic unit of structural symmetry. |
| **Holes** | Equivalence classes (orbits) not covered by any simulation run; reported as missing representatives. |
| **LabelTuple** | A tuple of bin label strings (`tuple[str, ...]`), the human-readable form of a BinTuple. |
| **Orbit** | The set of all bins reachable from one starting bin by applying group elements; equivalent to an equivalence class. |
| **Pólya enumeration** | A theorem giving the number of orbits of a group action on a set of colorings; for Sₙ on k bins equals C(n+k−1, k). |
| **Representative** | The lexicographically minimal member of each orbit; the bin that must be hit in simulation. |
| **Symmetry group** | The set of all permutations of design elements (coverpoints) that leave verification semantics invariant. |
| **Value class** | One of six behaviorally distinct partitions of a data field's value space: ZERO, ONE_HOT, BOUNDARY_LO, BOUNDARY_HI, INTERIOR, ALL_ONES. |

---

## 12. Visual & Reporting Surfaces

Three visual outputs are in scope. All use a shared design language:

### Option 2 — HTML Coverage Report  ✅ Built

`dabih/reporting/html_report.py` — `render_html_report(er, title, path)`

A self-contained single-file HTML report generated from any
`ExpansionResult` or `SymbolicExpansionResult`. All CSS and JS are
inlined — no external dependencies at view time. Designed for archiving
alongside simulation results and for handing to a verification lead at
sign-off review.

**Panels:** Overview stats, equivalence class gauge, implied bin gauge,
coverage holes table (searchable), covered orbit detail (searchable),
symmetry declarations, coverpoint list.

**Branding hook:** `logo_src` parameter accepts a URL or data-URI for the
Dabih logo. CSS custom properties (`--accent`, `--bg`, etc.) control the
full palette from one location.

**Pending:** Logo asset integration once graphics are provided.

---

### Option 4 — Project Landing Page  ✅ Built

`web/landing.html` — static single-file project page.

Explains the tool to a new audience: compression concept, pipeline
diagram (Ideas A→E), scaling table with animated bars, feature cards,
quick-start code block, idea status tracker. Animated on scroll.

**Branding hook:** Replace the wordmark `<div>` with `<img>` and update
four CSS variables. Grid texture and radial glow backgrounds are
CSS-only — no images required.

---

### Option 5 — Interactive Coverage Dashboard  ✅ Built

`web/dashboard.jsx` — React component, renderable as a Claude artifact.

Full interactive SPA for coverage analysis:
- **Sidebar navigation** with per-tab views
- **Multi-run selector** (tabs per run + merged view)
- **Overview:** stat cards + dual radial gauges (class % and bin %)
- **Coverage:** stacked progress bars across runs with merged total
- **Holes:** searchable grid of uncovered orbit representatives
- **Run History:** bar chart + detail table, click-through to run view
- **Symmetry:** declaration cards with group name, instance indices, block size
- **Coverpoints:** chip list
- **Load JSON:** drag-and-drop or browse for real Dabih coverage JSON files

Ships with synthetic 3-run SerDes demo data (4-lane, 330 orbits, Pólya)
so it renders immediately without simulation data.

**Branding hook:** Replace the wordmark `div` with `img`. Update six hex
values in the `T` token object at the top of the file.

---

### Pending for All Three

All branding integration complete. No pending items for OQ-07.

Future enhancements (not in scope):
- SVG version of the logo for crisp scaling at all sizes
- Dark/light theme toggle (currently dark-only by design)
- UCDB/VCS adapter → HTML report pipeline wired through CLI (OQ-04 extension)
