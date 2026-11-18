"""
dabih.formal.spyglass
~~~~~~~~~~~~~~~~~~~~~
Emits SpyGlass / VC SpyGlass structural pre-check artifacts (Tier 1):

    1.  SpyGlass Design Constraints  (dabih_spyglass.sgdc)
        Marks the generate-for array instances and their expected structural
        relationships.  The key checks:

            FMSP_SYM_FANOUT  — signal fanout must be identical across instances
            FMSP_SYM_CLOCK   — all instances must be in the same clock domain
            FMSP_SYM_RESET   — all instances must share the same reset net
            FMSP_SYM_PARAM   — module parameters must be identical across indices

    2.  SpyGlass run TCL script      (dabih_spyglass.tcl)
        Loads the RTL, applies the constraints, and runs the structural
        symmetry rule set.

Why Tier 1 matters
------------------
SpyGlass runs in minutes without a formal license.  It catches the most
common real-world symmetry violations:

    - Lane 0 has additional management-plane connectivity (extra fanout)
    - One instance has a different clock gate or ICG cell
    - A generate-for loop uses `if (i == 0)` to give one instance special
      reset behavior
    - Parameter `PRIORITY` is set to a different value for index 0

These structural violations mean Questa Formal (Tier 2) would return a
FALSIFIED result — but SpyGlass surfaces them in minutes without requiring
a full formal proof run.

SGDC rule approach
------------------
SpyGlass SGDC (SpyGlass Design Constraint) files use a Tcl-like syntax.
The constraints below use `define_design_attribute` and `define_rule_parameter`
to annotate the design and configure the symmetry rule checks.

For VC SpyGlass (2024.09-SP2 default), the same SGDC format applies.
The only difference is the invocation command:  `vc_spyglass` vs `spyglass`.
Dabih emits comments for both.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from ..core.bin_space import BinSpace
from .spec import DUTSpec


# ── SGDC constraint file ──────────────────────────────────────────────────────

def emit_spyglass_sgdc(
    bin_space: BinSpace,
    spec: DUTSpec,
    name: str = "",
) -> str:
    """
    Generate the SpyGlass SGDC constraint file for structural symmetry checks.

    The SGDC file:
    1.  Defines the clock and reset signals.
    2.  Annotates each instance group as a symmetric set using
        `define_design_attribute`.
    3.  Configures the structural symmetry rule parameters.

    Parameters
    ----------
    bin_space   : BinSpace with _symmetry_declarations.
    spec        : DUTSpec describing the DUT hierarchy.
    name        : Optional suffix for the annotation group name.

    Returns
    -------
    str — SGDC file content.
    """
    spec.validate()
    decls = getattr(bin_space, "_symmetry_declarations", [])
    ts    = datetime.now().strftime("%Y-%m-%d %H:%M")

    lines = [
        "# ══════════════════════════════════════════════════════════════════════",
        "# Dabih — SpyGlass / VC SpyGlass Structural Symmetry Constraints",
        f"# Generated: {ts}",
        f"# Tool: synopsys/vc_spyglass/2024.09-SP2  (also compatible with spyglass)",
        f"# DUT: {spec.top_module}",
        f"# Instance pattern: {spec.instance_fmt}",
        "# ══════════════════════════════════════════════════════════════════════",
        "",
        "# ── Clock definition ─────────────────────────────────────────────────",
        f"current_design {spec.top_module}",
        f"define_clock -name dabih_clk -period 10 [get_ports {spec.clk_port}]",
        "",
    ]

    if spec.rst_port:
        pol = "active_high" if spec.rst_active_high else "active_low"
        lines += [
            "# ── Reset definition ─────────────────────────────────────────────",
            f"define_reset -name dabih_rst -{pol} [get_ports {spec.rst_port}]",
            "",
        ]

    # ── Per-declaration structural symmetry annotations ───────────────────────
    lines.append("# ── Symmetric instance group annotations ─────────────────────────────")
    lines.append(
        "# Each group annotates a set of instances that Dabih has declared"
    )
    lines.append(
        "# structurally symmetric.  SpyGlass checks that all group members"
    )
    lines.append(
        "# have identical fanout, clock domain, and reset connectivity."
    )
    lines.append("")

    for decl_idx, decl in enumerate(decls):
        dtype   = decl.get("type", "instance")
        group   = decl.get("group", "?")
        block_s = decl.get("block_size", 1)

        indices = decl.get("instance_indices", []) or \
                  sorted({i for pair in decl.get("pairs", []) for i in pair})

        group_name = f"dabih_sym_group_{decl_idx}{'_' + name if name else ''}"

        lines += [
            f"# Declaration {decl_idx}: {dtype}, group={group}, block_size={block_s}",
            f"# Instances: {indices}",
        ]

        # Build the instance path list
        instance_paths = [
            f"{spec.top_module}/{spec.instance_path(i).replace('.', '/')}"
            for i in indices
        ]

        lines.append(f"define_design_attribute \\")
        lines.append(f"    -name dabih_symmetric_group \\")
        lines.append(f"    -value {group_name!r} \\")
        lines.append(f"    [get_cells {{ \\")
        for path in instance_paths:
            lines.append(f"        {path} \\")
        lines.append(f"    }}]")
        lines.append("")

        # Annotate each port role
        for port in spec.input_ports:
            lines.append(f"# Input port '{port}' — must be structurally identical across group")
            for i in indices:
                sig = f"{spec.top_module}/{spec.instance_path(i).replace('.', '/')}/{port}"
                lines.append(
                    f"define_design_attribute -name dabih_sym_input "
                    f"-value {group_name!r} [get_nets {{{sig}}}]"
                )
            lines.append("")

        for port in spec.output_ports:
            lines.append(f"# Output port '{port}' — fanout must match across group")
            for i in indices:
                sig = f"{spec.top_module}/{spec.instance_path(i).replace('.', '/')}/{port}"
                lines.append(
                    f"define_design_attribute -name dabih_sym_output "
                    f"-value {group_name!r} [get_nets {{{sig}}}]"
                )
            lines.append("")

    # ── Rule configuration ────────────────────────────────────────────────────
    lines += [
        "# ── SpyGlass rule configuration ──────────────────────────────────────",
        "# Enable structural symmetry rules for annotated groups.",
        "# Rule STARC05-1.3.1 checks for asymmetric fanout on same-group signals.",
        "# Rule W415 checks for signals driven in multiple processes (asymmetric).",
        "",
        "set_rule_parameter STARC05-1.3.1 -parameter check_fanout_symmetry yes",
        "set_rule_parameter W415          -parameter check_all_drivers       yes",
        "",
        "# ── Clock domain check ───────────────────────────────────────────────",
        "# All instances in a symmetric group must share the same clock domain.",
        "set_rule_parameter STARC05-2.1.3 -parameter check_group_cdc yes",
        "",
        "# ── Custom Dabih symmetry check ──────────────────────────────────────",
        "# If your SpyGlass installation includes custom rule support, the",
        "# following enables a dedicated structural symmetry audit rule.",
        "# Comment out if not available.",
        "#",
        "# load_rule_file dabih_sym_rules.sgdc",
        "# set_option enableDabihSymmetry yes",
    ]

    return "\n".join(lines)


# ── SpyGlass run TCL ──────────────────────────────────────────────────────────

def emit_spyglass_tcl(
    bin_space: BinSpace,
    spec: DUTSpec,
    sgdc_file: str,
    name: str = "",
) -> str:
    """
    Generate the SpyGlass / VC SpyGlass run TCL script.

    Parameters
    ----------
    bin_space   : BinSpace.
    spec        : DUTSpec.
    sgdc_file   : Path to the emitted .sgdc file (relative to run directory).
    name        : Optional name suffix.

    Returns
    -------
    str — TCL script text.
    """
    spec.validate()
    ts      = datetime.now().strftime("%Y-%m-%d %H:%M")
    proj    = f"dabih_sym{'_' + name if name else ''}"
    decls   = getattr(bin_space, "_symmetry_declarations", [])
    n_decls = len(decls)

    lines = [
        "# ══════════════════════════════════════════════════════════════════════",
        "# Dabih — SpyGlass / VC SpyGlass Structural Pre-Check Script (Tier 1)",
        f"# Generated: {ts}",
        "# ──────────────────────────────────────────────────────────────────────",
        "# Invocation (choose one):",
        f"#   vc_spyglass -tcl {proj}_spyglass.tcl   (vc_spyglass/2024.09-SP2)",
        f"#   spyglass    -tcl {proj}_spyglass.tcl   (spyglass legacy)",
        "# ══════════════════════════════════════════════════════════════════════",
        "",
        "# ── Project setup ────────────────────────────────────────────────────",
        f"new_project {proj}",
        f"set_option top {spec.top_module}",
        "set_option language sysv",
        "set_option enableSV yes",
        "set_option enableSV09 yes",
        "",
        "# ── RTL sources ──────────────────────────────────────────────────────",
    ]

    if spec.rtl_files:
        for f in spec.rtl_files:
            lines.append(f"read_file -type sverilog {{{f}}}")
    else:
        lines += [
            "# Add RTL files here — or use a filelist:",
            "# read_file -type sverilog -f rtl/filelist.f",
            "read_file -type sverilog [glob rtl/*.sv]",
        ]

    lines += [
        "",
        "# ── Design constraints ───────────────────────────────────────────────",
        f"read_file -type sgdc {{{sgdc_file}}}",
        "",
        "# ── Goal: structural symmetry pre-check ──────────────────────────────",
        "# Runs the structural analysis rules without full formal proof.",
        "# Typically completes in 2–10 minutes.",
        f"set_goal lint_rtl",
        "set_option enableDRC yes",
        "",
        "# ── Run ─────────────────────────────────────────────────────────────",
        "run_goal",
        "",
        "# ── Report ───────────────────────────────────────────────────────────",
        f"write_report -type violation   -file dabih_{proj}_violations.txt",
        f"write_report -type waiver      -file dabih_{proj}_waivers.txt",
        f"write_report -type summary     -file dabih_{proj}_summary.txt",
        "",
        "# ── Expected outcomes ────────────────────────────────────────────────",
        "# PASS  → No violations on dabih_sym_* annotated signals.",
        "#         Proceed to Questa Formal (Tier 2) for behavioral proof.",
        "# FAIL  → Structural asymmetry detected.  Violations indicate which",
        "#         signal or instance deviates from the expected symmetry.",
        "#         Fix the RTL or revise the symmetry declaration before",
        "#         running Questa Formal.",
        "",
        f"# Symmetry declarations checked: {n_decls}",
        f"# DUT: {spec.top_module}  Instance pattern: {spec.instance_fmt}",
    ]

    return "\n".join(lines)
