"""
dabih.formal.questa
~~~~~~~~~~~~~~~~~~~
Emits Questa Formal artifacts for symmetry verification (Tier 2):

    1.  SystemVerilog property wrapper  (dabih_sym_<name>.sv)
        Instantiates the DUT and asserts SVA symmetry properties for
        all instance pairs implied by the symmetry declarations.

    2.  Questa Formal TCL script        (dabih_questa_formal.tcl)
        Compiles the property wrapper + RTL and runs the formal proof.

Property formulation
--------------------
For each pair of instance indices (i, j) in a symmetry declaration,
Dabih emits two SVA properties:

    (a) Input-identity assumption:
            assume property (@clk) (in[i] === in[j])

        This constrains the formal tool to only explore states where the
        two instances receive identical stimulus — which is the precondition
        for the symmetry claim.

    (b) Output-identity assertion:
            assert property (@clk disable iff (rst)
                             (in[i] === in[j]) |-> ##[0:DEPTH] (out[i] === out[j]))

        If inputs have been identical, outputs must be identical within
        DEPTH clock cycles.

For S_n, only the generator-implied pairs are emitted:
    - The transposition (instance_indices[0], instance_indices[1])
    - All consecutive pairs in the n-cycle

Together these are sufficient: transitivity through the generator closure
covers the full group without redundant properties.

Inductive proof note
--------------------
Questa Formal's default engine uses k-induction.  For the symmetry proof
to be complete, the reset assumption ensures that instances start in the
same state (base case).  The inductive step is: if instances are symmetric
at cycle t, and they receive identical input at t+1, they are symmetric at
t+1.  The proof is complete when Questa Formal reports PROVEN for all
asserted properties.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Iterable

from ..core.bin_space import BinSpace
from .spec import DUTSpec


# ── Pair generation ───────────────────────────────────────────────────────────

def _generator_pairs(indices: list[int]) -> list[tuple[int, int]]:
    """
    Return the minimal set of (i, j) pairs that, together with transitivity,
    cover the full symmetric group on `indices`.

    For a list [a, b, c, d]:
        transposition:  (a, b)
        cycle pairs:    (a, b), (b, c), (c, d)  [plus (d, a) for wrap]

    Deduplicated preserving order.
    """
    if len(indices) < 2:
        return []
    pairs: list[tuple[int, int]] = []
    seen: set[frozenset] = set()

    def add(i: int, j: int):
        key = frozenset({i, j})
        if key not in seen:
            seen.add(key)
            pairs.append((i, j))

    # Transposition: first two
    add(indices[0], indices[1])
    # Cycle: consecutive pairs
    for k in range(len(indices) - 1):
        add(indices[k], indices[k + 1])
    # Cycle wrap (completes the n-cycle generator)
    if len(indices) >= 3:
        add(indices[-1], indices[0])

    return pairs


def _all_pairs(indices: list[int]) -> list[tuple[int, int]]:
    """All unique (i, j) pairs with i < j — for pairwise declarations."""
    return [(indices[a], indices[b])
            for a in range(len(indices))
            for b in range(a + 1, len(indices))]


def _declaration_pairs(decl: dict) -> list[tuple[int, int]]:
    """Return the pairs to check for a given symmetry declaration."""
    dtype = decl.get("type", "instance")
    if dtype == "instance":
        return _generator_pairs(decl.get("instance_indices", []))
    elif dtype == "cyclic":
        # For Zn, check consecutive pairs in the cycle
        indices = decl.get("instance_indices", [])
        pairs = []
        seen: set[frozenset] = set()
        for k in range(len(indices)):
            i, j = indices[k], indices[(k + 1) % len(indices)]
            key = frozenset({i, j})
            if key not in seen:
                seen.add(key)
                pairs.append((i, j))
        return pairs
    elif dtype == "pairwise":
        # Each declared pair is independent — check each directly
        return [tuple(p) for p in decl.get("pairs", [])]
    return []


# ── SVA property wrapper ──────────────────────────────────────────────────────

def _property_name(prefix: str, i: int, j: int) -> str:
    return f"{prefix}_inst{i}_vs_inst{j}"


def _emit_sv_property(
    spec: DUTSpec,
    i: int,
    j: int,
    prop_prefix: str,
    ports_in: list[str],
    ports_out: list[str],
) -> list[str]:
    """
    Emit SVA property and assertion for one instance pair (i, j).

    Returns a list of SV lines.
    """
    lines = []
    dc = spec.disable_clause()
    depth = spec.proof_depth
    pname = _property_name(prop_prefix, i, j)
    clk = spec.clk_port

    # ── Input identity assumption ─────────────────────────────────────────────
    # Constrain the formal search to states where both instances see identical
    # stimulus.  This is an ASSUME — the tool is not asked to prove it, but
    # only to explore state space consistent with it.
    lines.append(f"    // ── Pair ({i}, {j}) ─────────────────────────────────")
    lines.append(f"    // Assumption: instances {i} and {j} receive identical stimulus")
    for port in ports_in:
        sig_i = spec.signal_path(i, port)
        sig_j = spec.signal_path(j, port)
        aname = f"ASM_{pname}_{port}"
        lines.append(f"    property p_{aname};")
        lines.append(f"        @(posedge {clk}) {dc}")
        lines.append(f"        ({sig_i} === {sig_j});")
        lines.append(f"    endproperty")
        lines.append(f"    {aname}: assume property (p_{aname});")
        lines.append("")

    # ── Output identity assertion ─────────────────────────────────────────────
    # Assert that identical inputs produce identical outputs within DEPTH cycles.
    lines.append(f"    // Assertion: identical inputs → identical outputs within {depth} cycles")
    for port in ports_out:
        sig_i = spec.signal_path(i, port)
        sig_j = spec.signal_path(j, port)
        # Antecedent: all input ports are currently identical
        antecedents = " && ".join(
            f"({spec.signal_path(i, p)} === {spec.signal_path(j, p)})"
            for p in ports_in
        )
        aname = _property_name(prop_prefix, i, j) + f"_{port}"
        lines.append(f"    property p_{aname};")
        lines.append(f"        @(posedge {clk}) {dc}")
        lines.append(f"        ({antecedents})")
        lines.append(f"        |-> ##[0:{depth}] ({sig_i} === {sig_j});")
        lines.append(f"    endproperty")
        lines.append(f"    SYM_{aname}: assert property (p_{aname})")
        lines.append(
            f'        else $error("Dabih symmetry violation: '
            f'{spec.top_module}.{spec.instance_path(i)}.{port} '
            f'!= {spec.instance_path(j)}.{port}");'
        )
        lines.append("")

    return lines


def _sv_port_declarations(spec: DUTSpec, all_indices: set[int]) -> list[str]:
    """
    Emit top-level port declarations for the property wrapper module.
    Infers ports from DUTSpec if top_ports is empty.
    """
    lines = [f"    input  logic {spec.clk_port},"]
    if spec.rst_port:
        lines.append(f"    input  logic {spec.rst_port},")

    if spec.top_ports:
        for ps in spec.top_ports:
            direction = "input " if ps.is_input else "output"
            lines.append(f"    {direction} {ps.sv_type()} {ps.name},")
    else:
        # Infer array-indexed ports for each instance's input/output signals
        max_idx = max(all_indices) if all_indices else 0
        for port in spec.input_ports:
            lines.append(f"    input  logic [{max_idx}:0] {port}_per_inst [0:{max_idx}],")
        for port in spec.output_ports:
            lines.append(f"    output logic [{max_idx}:0] {port}_per_inst [0:{max_idx}],")

    # Remove trailing comma from last line
    if lines:
        lines[-1] = lines[-1].rstrip(",")
    return lines


def emit_sv_wrapper(
    bin_space: BinSpace,
    spec: DUTSpec,
    name: str = "",
) -> str:
    """
    Generate the SystemVerilog property wrapper for Questa Formal.

    Parameters
    ----------
    bin_space   : BinSpace with _symmetry_declarations populated.
    spec        : DUTSpec describing the DUT ports and hierarchy.
    name        : Optional name suffix for the module and file.

    Returns
    -------
    str — complete SV source text.
    """
    spec.validate()
    decls       = getattr(bin_space, "_symmetry_declarations", [])
    module_name = f"dabih_sym_check{'_' + name if name else ''}"
    timestamp   = datetime.now().strftime("%Y-%m-%d %H:%M")
    params_sv   = spec.param_overrides_sv()

    # Collect all instance indices across all declarations
    all_indices: set[int] = set()
    for d in decls:
        all_indices.update(d.get("instance_indices", []))
        for pair in d.get("pairs", []):
            all_indices.update(pair)

    lines = [
        "// ══════════════════════════════════════════════════════════════════════",
        f"// Dabih — Formal Symmetry Property Wrapper",
        f"// Generated: {timestamp}",
        f"// Tool target: Questa Formal (questa-formal/2024.3_1+)",
        f"// DUT: {spec.top_module}",
        f"// Instance pattern: {spec.instance_fmt}",
        f"// Proof depth: {spec.proof_depth} cycles",
    ]
    if spec.notes:
        lines.append(f"// Notes: {spec.notes}")
    lines += [
        "// ══════════════════════════════════════════════════════════════════════",
        "",
        "// SVA bind-point: this module may be used standalone or via `bind`.",
        "// See dabih_questa_formal.tcl for the complete compile + verify flow.",
        "",
        f"module {module_name} (",
    ]

    # Port declarations
    port_lines = _sv_port_declarations(spec, all_indices)
    for pl in port_lines:
        lines.append(f"    {pl}")
    lines += [");", ""]

    # Parameters
    lines += [
        f"    // ── DUT instantiation ────────────────────────────────────────────",
        f"    {spec.top_module} {params_sv} u_dut (",
        f"        .{spec.clk_port} ({spec.clk_port}),",
    ]
    if spec.rst_port:
        lines.append(f"        .{spec.rst_port}  ({spec.rst_port}),")
    lines += [
        "        // Connect remaining ports via .* or explicit mapping",
        "        .*",
        "    );",
        "",
    ]

    # Reset assumption: all instances start in identical state after reset
    if spec.rst_port:
        rst_active = spec.rst_port if spec.rst_active_high else f"!{spec.rst_port}"
        lines += [
            "    // ── Reset assumption ─────────────────────────────────────────────",
            "    // All instances must be in identical state after reset.",
            "    // This forms the base case of the k-induction proof.",
        ]
        for port in spec.output_ports:
            indices_sorted = sorted(all_indices)
            for k in range(len(indices_sorted) - 1):
                ia = indices_sorted[k]
                ib = indices_sorted[k + 1]
                sig_a = spec.signal_path(ia, port)
                sig_b = spec.signal_path(ib, port)
                aname = f"RESET_SYM_{ia}_{ib}_{port}"
                lines.append(f"    property p_{aname};")
                lines.append(f"        @(posedge {spec.clk_port})")
                lines.append(f"        {rst_active} |-> ({sig_a} === {sig_b});")
                lines.append(f"    endproperty")
                lines.append(f"    {aname}: assume property (p_{aname});")
                lines.append("")

    # Symmetry properties per declaration
    lines.append("    // ── Symmetry assertions ──────────────────────────────────────────")
    for decl_idx, decl in enumerate(decls):
        dtype = decl.get("type", "instance")
        group = decl.get("group", "?")
        indices = decl.get("instance_indices", []) or \
                  [i for pair in decl.get("pairs", []) for i in pair]
        pairs = _declaration_pairs(decl)
        prop_prefix = f"D{decl_idx}_{dtype}"

        lines += [
            f"    // Declaration {decl_idx}: {dtype}, group={group}",
            f"    // Instances: {indices}",
            f"    // Checking {len(pairs)} generator-implied pair(s)",
            "",
        ]

        for i, j in pairs:
            prop_lines = _emit_sv_property(
                spec, i, j, prop_prefix,
                spec.input_ports, spec.output_ports
            )
            lines.extend(prop_lines)

    lines += ["endmodule", ""]
    return "\n".join(lines)


# ── Questa Formal TCL script ──────────────────────────────────────────────────

def emit_questa_tcl(
    bin_space: BinSpace,
    spec: DUTSpec,
    wrapper_sv: str,
    name: str = "",
) -> str:
    """
    Generate the Questa Formal compile + verify TCL script.

    Parameters
    ----------
    bin_space   : BinSpace with declarations.
    spec        : DUTSpec.
    wrapper_sv  : Path to the emitted property wrapper .sv file (relative).
    name        : Optional name suffix for the work library.

    Returns
    -------
    str — complete TCL script text.
    """
    spec.validate()
    work    = f"dabih_sym{'_' + name if name else ''}"
    timeout = spec.questa_timeout
    depth   = spec.proof_depth
    ts      = datetime.now().strftime("%Y-%m-%d %H:%M")
    decls   = getattr(bin_space, "_symmetry_declarations", [])

    # Collect all assertion names for the verify step
    all_assertions: list[str] = []
    all_indices: set[int] = set()
    for d in decls:
        all_indices.update(d.get("instance_indices", []))
        for pair in d.get("pairs", []):
            all_indices.update(pair)

    for decl_idx, decl in enumerate(decls):
        dtype = decl.get("type", "instance")
        pairs = _declaration_pairs(decl)
        prop_prefix = f"D{decl_idx}_{dtype}"
        for i, j in pairs:
            for port in spec.output_ports:
                aname = _property_name(prop_prefix, i, j) + f"_{port}"
                all_assertions.append(f"SYM_{aname}")

    lines = [
        "# ══════════════════════════════════════════════════════════════════════",
        "# Dabih — Questa Formal Symmetry Verification Script",
        f"# Generated: {ts}",
        f"# Tool: mentor/questa-formal/2024.3_1 (or later)",
        f"# DUT: {spec.top_module}",
        f"# Proof depth: {depth} cycles",
        f"# Timeout: {timeout}s",
        "# ══════════════════════════════════════════════════════════════════════",
        "",
        "# ── Step 1: Compile ─────────────────────────────────────────────────",
        f"questa_formal compile \\",
        f"    -work {work} \\",
        f"    -sv \\",
        f"    -f64 \\",
        f"    {wrapper_sv} \\",
        f"    {spec.rtl_file_list()}",
        "",
        "# ── Step 2: Elaborate ───────────────────────────────────────────────",
        f"questa_formal elaborate \\",
        f"    -work {work} \\",
        f"    -top {spec.top_module}",
        "",
        "# ── Step 3: Verify ──────────────────────────────────────────────────",
        "# Uses k-induction (default engine).  Each assertion is proven or",
        "# returns a counterexample showing which instance pair is asymmetric.",
        f"questa_formal verify \\",
        f"    -work {work} \\",
        f"    -timeout {timeout} \\",
        f"    -init dabih_{work}.fvinit \\",
        f"    -prove_depth {depth} \\",
        f"    -property {{ \\",
    ]

    for aname in all_assertions:
        lines.append(f"        {aname} \\")
    lines += [
        "    }",
        "",
        "# ── Step 4: Report ──────────────────────────────────────────────────",
        f"questa_formal report -property -file dabih_{work}_results.txt",
        "",
        "# ── Expected results ────────────────────────────────────────────────",
        "# PROVEN   for all SYM_* properties → symmetry is formally verified",
        "# FALSIFIED → counterexample shows which instance pair is asymmetric",
        "#            (check waveform: the falsifying trace shows where the",
        "#             two instances diverge under identical stimulus)",
        "",
        f"# Total assertions: {len(all_assertions)}",
    ]
    for aname in all_assertions:
        lines.append(f"#   {aname}")

    return "\n".join(lines)
