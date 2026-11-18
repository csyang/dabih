"""
dabih.formal
~~~~~~~~~~~~
Idea D — Formal Symmetry Verification Pass.

Two-tier emission for proving that Dabih's declared symmetry groups
are valid symmetries of the actual hardware.

Tier 1 — SpyGlass structural pre-check (fast, automatic)
    Emits SGDC constraints and a run TCL script.  Checks fanout
    uniformity, clock domain, reset connectivity across the instance
    group.  Runs in minutes without SVA authorship.

Tier 2 — Questa Formal SVA proof (authoritative, sign-off quality)
    Emits a SystemVerilog property wrapper and a Questa Formal TCL
    compile + verify script.  Proves (or falsifies) the behavioral
    symmetry claim using k-induction.

Quick start
-----------
    from dabih.formal import emit_symmetry_check
    from dabih.formal.spec import DUTSpec

    spec = DUTSpec(
        top_module   = "serdes_top",
        instance_fmt = "rx_gen[{i}].u_rx",
        clk_port     = "clk",
        rst_port     = "rst_n",
        rst_active_high = False,
        input_ports  = ["data_in", "valid"],
        output_ports = ["state", "ready"],
        rtl_files    = ["rtl/serdes_top.sv", "rtl/rx_lane.sv"],
        proof_depth  = 20,
    )

    paths = emit_symmetry_check(bin_space, spec, out_dir="formal/")
    # Returns dict of emitted file paths.
"""

from __future__ import annotations

from pathlib import Path

from ..core.bin_space import BinSpace
from .spec import DUTSpec, PortSpec
from .questa import emit_sv_wrapper, emit_questa_tcl
from .spyglass import emit_spyglass_sgdc, emit_spyglass_tcl


def emit_symmetry_check(
    bin_space: BinSpace,
    spec: DUTSpec,
    out_dir: str | Path = ".",
    name: str = "",
    tools: list[str] | None = None,
) -> dict[str, Path]:
    """
    Emit all formal verification artifacts for the symmetry declarations
    on `bin_space`.

    Parameters
    ----------
    bin_space   : BinSpace with _symmetry_declarations populated.
                  Use add_instance_symmetry(), add_cyclic_symmetry(), or
                  add_pairwise_symmetry() to build declarations.
    spec        : DUTSpec — port names, hierarchy, RTL files, proof depth.
    out_dir     : Directory to write emitted files.  Created if absent.
    name        : Optional suffix appended to all emitted file names,
                  e.g. "rx_lane" → "dabih_sym_rx_lane.sv".
    tools       : Which tools to emit for.  Options: "questa_formal",
                  "spyglass".  Default: both.

    Returns
    -------
    dict mapping tool name to emitted file Path(s):
        {
          "sv"            : Path("formal/dabih_sym_<name>.sv"),
          "questa_tcl"    : Path("formal/dabih_questa_formal_<name>.tcl"),
          "spyglass_sgdc" : Path("formal/dabih_spyglass_<name>.sgdc"),
          "spyglass_tcl"  : Path("formal/dabih_spyglass_<name>.tcl"),
        }
    """
    spec.validate()
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    if tools is None:
        tools = ["questa_formal", "spyglass"]

    suffix  = f"_{name}" if name else ""
    emitted: dict[str, Path] = {}

    if "questa_formal" in tools:
        # SystemVerilog property wrapper
        sv_name = f"dabih_sym{suffix}.sv"
        sv_path = out / sv_name
        sv_path.write_text(emit_sv_wrapper(bin_space, spec, name))
        emitted["sv"] = sv_path

        # Questa Formal TCL
        tcl_name = f"dabih_questa_formal{suffix}.tcl"
        tcl_path = out / tcl_name
        tcl_path.write_text(emit_questa_tcl(bin_space, spec, sv_name, name))
        emitted["questa_tcl"] = tcl_path

    if "spyglass" in tools:
        # SpyGlass SGDC constraints
        sgdc_name = f"dabih_spyglass{suffix}.sgdc"
        sgdc_path = out / sgdc_name
        sgdc_path.write_text(emit_spyglass_sgdc(bin_space, spec, name))
        emitted["spyglass_sgdc"] = sgdc_path

        # SpyGlass run TCL
        sg_tcl_name = f"dabih_spyglass{suffix}.tcl"
        sg_tcl_path = out / sg_tcl_name
        sg_tcl_path.write_text(emit_spyglass_tcl(bin_space, spec, sgdc_name, name))
        emitted["spyglass_tcl"] = sg_tcl_path

    return emitted


__all__ = [
    "emit_symmetry_check",
    "DUTSpec", "PortSpec",
    "emit_sv_wrapper", "emit_questa_tcl",
    "emit_spyglass_sgdc", "emit_spyglass_tcl",
]
