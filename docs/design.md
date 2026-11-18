<div align="center">
  <img src="../assets/banner.png" alt="Dabih" width="320" />
</div>

# Dabih — Design Document

**Dabih version:** 0.1.0  
**Date:** 2026-05-24  
**Status:** All five Ideas complete. 528 tests passing.

---

## 1. Purpose and Scope

Dabih compresses functional coverage models for ASIC/FPGA verification by
exploiting structural symmetry. The target audience is hardware verification
engineers who write cross-coverage groups over replicated hardware arrays
(lane arrays, pipeline stages, memory channels) and face exponential growth
in coverage closure time.

A conventional 8-lane SerDes with 4-state per-lane cross-coverage has
4⁸ = 65,536 bins. Dabih reduces this to 165 equivalence classes using the
symmetry of the full symmetric group S₈. Testing one representative bin
implies coverage for all 397 bins in the same equivalence class.

**Out of scope:**
- Functional coverage for non-symmetric designs (no compression possible)
- Code coverage (line, branch, FSM)
- Formal property verification of design correctness (only of symmetry)
- UVM agent architecture or testbench generation

---

## 2. Mathematical Foundation

### 2.1 Equivalence Classes and Orbits

Let **B** = B₀ × B₁ × … × Bₙ₋₁ be the cross-coverage bin space, where
Bᵢ is the set of bins for coverpoint i.

A symmetry group **G** acts on **B** by permuting coverpoint indices. Two
bins b and b′ are *equivalent* (in the same orbit) if there exists g ∈ G
such that g(b) = b′. The set of equivalence classes is the *orbit partition*
of **B** under G.

**Verification claim:** If a design is structurally symmetric under G, then
a hit on any bin b implies a hit on every bin in orbit(b). Testing one
representative from each orbit is sufficient for complete functional coverage.

### 2.2 Pólya Enumeration (Idea E, primary)

For the full symmetric group Sₙ acting on n identical instances, each with
K per-instance bin combinations, the orbit count is the multiset coefficient:

```
|orbits| = C(n + K − 1, n)
```

This is O(1) — no enumeration required. The 8-lane case:
K = 4 (4-state) → C(8+4-1, 8) = C(11,8) = 165 orbits.

Proof: orbits of Sₙ on K^n biject with multisets of size n from K elements.

### 2.3 Burnside's Lemma (fallback for partial symmetry)

For arbitrary groups G:

```
|orbits| = (1/|G|) Σ_{g∈G} K^{c_block(g)}
```

where c_block(g) = number of cycles of g acting on block positions.

This requires full group enumeration — O(|G|) — but never touches the bin
space. Used for partial symmetry groups (Z₂, Zₙ, Z₂×Z₂, etc.) where
|G| ≤ 500,000.

### 2.4 Representative Selection

For Sₙ: representatives are all non-decreasing sequences of K values of
length n. Enumerated via `itertools.combinations_with_replacement(range(K), n)`.
For block symmetry: enumerates combinations of per-block value tuples.

For general groups: the canonical form is the lexicographic minimum of the
orbit, computed by applying all group elements.

---

## 3. Architecture

### 3.1 Five Ideas

| Idea | Description | Status |
|------|-------------|--------|
| A | RTL extractor — parse `generate-for` arrays via pyslang CST | ✅ Done |
| B | BFS orbit engine — compute orbit partition via group closure | ✅ Done |
| C | Coverage post-processor — expand simulation hits to implied coverage | ✅ Done |
| D | Formal verification — emit SpyGlass + Questa Formal artifacts | ✅ Done |
| E | Symbolic orbit engine — Pólya/Burnside analytic counting | ✅ Done |

### 3.2 Data Flow

```
RTL source files (.sv)
        │
        ▼ Idea A — RtlExtractor (pyslang, no elaboration)
GenerateArray[]           (one per generate-for loop)
        │
        ▼ Idea A+B bridge — BinSpaceBuilder
BinSpace                  (coverpoints + symmetry group + orbit partition)
        │
        ├──▶ spec_io.dump_bin_space() ──▶ spec.json  (CLI contract)
        │
        ├──▶ Idea E — SymbolicOrbitEngine
        │         ├── count_orbits()       O(1) for Sₙ
        │         ├── representatives()    O(orbit_count)
        │         └── canonical(bt)        O(n log n) for Sₙ
        │
        ├──▶ Idea D — emit_symmetry_check()
        │         ├── dabih_sym.sv         (SVA property wrapper)
        │         ├── questa_formal.tcl    (Questa Formal script)
        │         └── spyglass.sgdc/.tcl   (SpyGlass pre-check)
        │
Simulation results (JSON or vcover/urg text)
        │
        ▼ Idea C — ExpansionEngine / SymbolicExpansionEngine
ExpansionResult           (orbit coverage map + holes + provenance)
        │
        ├──▶ report()          (text to stdout)
        ├──▶ to_dict()         (JSON)
        └──▶ render_html_report()  (self-contained HTML)
```

### 3.3 Module Descriptions

**`core/symmetry.py`** — `Permutation` and `SymmetryGroup`.

`SymmetryGroup` stores generators and computes the full group by BFS closure
over generators and their inverses. Key constraint: closure uses generators
only — O(k×|B|) not O(|G|²). `order()` enumerates the full group for
reporting but is not on the critical path.

**`core/bin_space.py`** — `BinSpace` and `Orbit`.

`BinSpace` is the central object: a list of coverpoints, a symmetry group,
and the computed orbit partition. The ergonomic symmetry API
(`add_instance_symmetry`, `add_cyclic_symmetry`, `add_pairwise_symmetry`)
stores structured `_symmetry_declarations` in addition to group generators.
These declarations are consumed by Idea D and the symbolic profile detector.

`add_full_lane_symmetry(n)` delegates to `add_instance_symmetry([0..n-1])`.
This was changed during OQ-05 to ensure declarations are always populated.

**`core/symbolic.py`** — `SymbolicOrbitEngine`.

Profile detection priority:
1. `_symmetry_declarations` on BinSpace (most reliable — set by ergonomic API)
2. `_symbolic_hint` set by BinSpaceBuilder bridge (exact — set at build time)
3. Heuristic from group order + `_is_block_permutation()` validation

`_is_block_permutation()` validates that generators genuinely permute whole
blocks — prevents false Sₙ detection when a Z₂ group (order 2) happens to
equal 2! = S₂ (same order, not the same group).

**`rtl/extractor.py`** — `RtlExtractor`.

Walks pyslang's concrete syntax tree (CST) without elaboration. Detects
`generate-for` patterns and extracts: parent module, block label, instance
module type, genvar name, and the bound expression (either a literal integer
or a parameter name). Parameter defaults are scraped from the CST; missing
defaults require `add_param()` override.

**`rtl/bridge.py`** — `BinSpaceBuilder`.

Converts extracted `GenerateArray[]` into `BinSpace` objects. Sets
`_symbolic_hint` for the symbolic engine and calls `add_instance_symmetry()`
(not raw `add_symmetry()`) so formal emission works correctly.

**`coverage/expander.py`** — `ExpansionEngine` and `ExpansionResult`.

BFS-based expansion. Builds a `_bin_to_orbit` lookup dict at construction
time (O(|B|)) and uses it for O(1) per-bin orbit lookup during expansion.
The ceiling is ~1M bins before memory becomes prohibitive.

Provenance (OQ-06): `merge_and_expand(results, track_provenance=True)` builds
a `dict[BinTuple, set[str]]` mapping each covered orbit representative to
the set of `run_id` values that contributed a hit. Stored as `_provenance`
on the result; accessed via `coverage_histogram()`, `fragile_orbits()`, etc.

**`coverage/symbolic_expander.py`** — `SymbolicExpansionEngine`.

No full bin space enumeration. Translates each hit bin to its canonical form
and tracks covered canonicals as a set. For Sₙ, this is O(hits × n log n)
instead of O(|B|). Holes enumerated via `representatives()` — O(orbit_count).

**`adapters/`** — `questa.py` and `vcs.py`.

Pure text parsers. No EDA binary APIs. Parse `vcover report -details` and
`urg -format text` output respectively, extracting cross-coverage bin rows.

Key format differences:
- Questa: cross header uses single `#` (`lane0#lane1#lane2`)
- VCS: cross header uses double `##` (`lane0##lane1##lane2`)
- Questa: bins as `<IDLE,ACTIVE>  count  goal  status`
- VCS: bins as `bin <IDLE,ACTIVE>  count  at_least  status`

Zero-count bins present in both (with `ZERO`/`Zero` status) — silently skipped.

**`formal/`** — Idea D emission.

`DUTSpec` captures: top module name, instance path format string (with `{i}`
placeholder), clock/reset ports, input/output port lists, RTL file list, and
proof depth.

Property formulation:
```
assume property: (in[i] === in[j])           — identical stimulus
assert property: (in[i] === in[j]) |->       — implies
                 ##[0:DEPTH] (out[i] === out[j])  — identical response
```

Reset assumptions force all instances to identical initial state (k-induction
base case). Generator-minimal pairs are emitted — for S₄ that is 4 pairs
(transposition + 3 cycle pairs), sufficient by group closure transitivity.

**`reporting/html_report.py`** — `render_html_report()`.

Generates a single self-contained HTML file (all CSS/JS/images inlined).
The `◐ Confidence` nav section appears only when `D.provenance` is non-null
in the injected data JSON. The `dabihScrollTo()` function name avoids
collision with the native browser `window.scrollTo()` method.

---

## 4. Key Algorithms

### 4.1 BFS Orbit Computation

```python
def compute_orbits(bin_space):
    unvisited = set(all_bins)
    orbits = []
    while unvisited:
        seed = min(unvisited)
        orbit = {seed}
        queue = [seed]
        while queue:
            bt = queue.pop()
            for g in generators_and_inverses:
                neighbour = g.apply(bt)
                if neighbour not in orbit:
                    orbit.add(neighbour)
                    queue.append(neighbour)
        unvisited -= orbit
        orbits.append(Orbit(min(orbit), orbit))
    return orbits
```

Complexity: O(k × |B|) where k = number of generators+inverses.

### 4.2 Canonical Form (Sₙ)

```python
def canonical(bt, n_blocks, block_size):
    blocks = [bt[i*s:(i+1)*s] for i in range(n_blocks)]
    return tuple(v for block in sorted(blocks) for v in block)
```

O(n log n). Used by `SymbolicExpansionEngine` to group hits without
enumerating the full bin space.

### 4.3 Pólya Closed-Form

```python
import math
def polya_orbit_count(n_instances, k_per_block_combo):
    return math.comb(n_instances + k_per_block_combo - 1, n_instances)
```

Single integer arithmetic operation. No enumeration.

---

## 5. Coverage JSON Format

### 5.1 Result file (simulation output)

```json
{
  "run_id"    : "seed_042",
  "simulator" : "questa",
  "covergroup": "lane_cross_cg",
  "hits": [
    {"bin": ["IDLE", "ACTIVE", "STALL", "IDLE"], "count": 7},
    {"bin": ["ACTIVE", "IDLE", "IDLE", "IDLE"], "count": 3}
  ]
}
```

Only hit bins appear. Zero-count bins are implicit (absent = zero).

### 5.2 Spec file (from `dabih spec`)

```json
{
  "version"          : "1",
  "name"             : "serdes_top.rx_lane × 4",
  "coverpoints"      : [{"name": "u_rx[0].state", "bins": ["IDLE","ACTIVE","STALL","ERROR"]}, ...],
  "declarations"     : [{"type": "instance", "instance_indices": [0,1,2,3],
                         "block_size": 1, "group": "S4", "n_generators": 2}],
  "orbit_count"      : 35,
  "total_bins"       : 256,
  "compression_ratio": 7.3143,
  "method"           : "polya",
  "representatives"  : [["IDLE","IDLE","IDLE","IDLE"], ["ACTIVE","IDLE","IDLE","IDLE"], ...]
}
```

---

## 6. Formal Verification Design (Idea D)

### 6.1 Two-tier approach

**Tier 1 — SpyGlass structural pre-check** (fast, minutes)
- Annotates instances with `define_design_attribute` in SGDC format
- Checks: fanout uniformity, clock domain consistency, reset connectivity
- Rule configuration: STARC05-1.3.1 (fanout), STARC05-2.1.3 (CDC), W415 (drivers)
- Target: `synopsys/vc_spyglass/2024.09-SP2`

**Tier 2 — Questa Formal SVA proof** (thorough, hours)
- Emits SystemVerilog property wrapper + TCL compile/verify script
- Formal engine: k-induction (Questa Formal default)
- Result: PROVEN or FALSIFIED with counterexample waveform
- Target: `mentor/questa-formal/2024.3_1` (compatible through 2026.1)

### 6.2 Property structure

For each generator-implied pair (i, j) and each output port:
1. `assume property`: inputs i and j are identical (constrains search space)
2. `assume property`: after reset, all outputs are identical (base case)
3. `assert property`: identical inputs → identical outputs within DEPTH cycles

### 6.3 Proof depth guidance

- Start at depth 20 for most designs
- Increase by 10 if result is UNKNOWN (neither proven nor falsified)
- Most structural symmetry proofs close within 30–50 cycles for pipelines ≤ 8 deep
- A FALSIFIED result means the RTL is not symmetric — the counterexample
  waveform shows exactly where instances diverge

---

## 7. Visual Surfaces

### 7.1 HTML Coverage Report

Self-contained single-file HTML. All CSS, JS, and brand images are inlined
as base64 data-URIs. Sidebar navigation uses `dabihScrollTo()` to avoid
collision with `window.scrollTo()`.

Sections: Overview, Coverage (dual gauges), Holes (searchable table),
Orbit Detail, Symmetry declarations, Coverpoints, Confidence (provenance,
when available).

### 7.2 Landing Page

Static HTML explaining the project. Sections: hero with infographic banner,
compression callout (65,536 → 165), pipeline diagram (Ideas A→E), scaling
table, feature cards, quick-start code block, idea status tracker.

### 7.3 Interactive Dashboard

React artifact. Tabs: Overview, Coverage, Holes, Run History, Confidence,
Symmetry, Coverpoints. Loads real Dabih JSON via drag-and-drop. Ships with
3-run SerDes demo data. Confidence tab renders histogram bars and fragile
orbit chip grid.

### 7.4 Brand palette

| Token | Value | Role |
|-------|-------|------|
| Background | `#04060e` | Deep space black |
| Surface | `#090c18` | Card/panel |
| Primary | `#00c8ff` | Cyan — "Cut the Redundant" |
| Secondary | `#a855f7` | Purple — "Keep What Matters" |
| Midpoint | `#6366f1` | Indigo gradient bridge |
| Alert | `#eab308` | Yellow (Essential Set) |

---

## 8. Test Strategy

All tests use `pytest`. No mocking of the core library — all tests exercise
real data through real code paths.

| Suite | Strategy |
|-------|----------|
| `test_core.py` | BinSpace, group closure, orbit correctness |
| `test_coverage.py` | ExpansionEngine, CoverageResult, JSON round-trip |
| `test_rtl.py` | Real SV fixture files through full extractor + bridge pipeline |
| `test_symbolic.py` | Pólya/Burnside counts verified against BFS for 18 (n,k) pairs |
| `test_partial_symmetry.py` | All three ergonomic symmetry methods + validation |
| `test_adapters.py` | Cross-adapter consistency: Questa and VCS fixtures produce identical results |
| `test_formal.py` | SVA property content, SpyGlass SGDC content, file emission |
| `test_cli.py` | All 5 commands + OQ-09 adapter flags, end-to-end pipeline |
| `test_provenance.py` | Provenance tracking, histogram, fragile orbits, backward compat |

Critical parametric invariant: `test_symbolic.py` tests `bfs_count == sym_count`
across 18 `(n, k)` combinations. If this fails, the symbolic engine has a bug.

Tests read their input data from the top-level `examples/` folder — RTL from
`examples/rtl/` and simulator reports from `examples/simulator/` — so the
example commands in the documentation and the test suite exercise the same files.
