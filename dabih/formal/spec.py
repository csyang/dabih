"""
dabih.formal.spec
~~~~~~~~~~~~~~~~~
User-supplied specification of the Design Under Test (DUT) for formal
symmetry property emission.

The DUTSpec bridges the gap between Dabih's structural symmetry model
(which knows which instances are symmetric and why) and the formal tools
(which need to know signal names, hierarchy paths, and port roles).

Typical usage
-------------
    from dabih.formal.spec import DUTSpec, PortSpec

    spec = DUTSpec(
        top_module   = "serdes_top",
        instance_fmt = "rx_gen[{i}].u_rx",  # {i} is substituted
        clk_port     = "clk",
        rst_port     = "rst",
        rst_active_high = True,
        input_ports  = ["data_in", "valid"],
        output_ports = ["state", "ready"],
        rtl_files    = ["rtl/serdes_top.sv", "rtl/rx_lane.sv"],
        proof_depth  = 20,
    )

    from dabih.formal import emit_symmetry_check
    emit_symmetry_check(bin_space, spec, out_dir="formal/")
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


# ── PortSpec ──────────────────────────────────────────────────────────────────

@dataclass
class PortSpec:
    """
    One port (or bus) on the replicated module instance.

    Attributes
    ----------
    name        : Port name as it appears in the RTL (e.g. "data_in").
    width       : Bit width.  1 for scalar signals.
    is_input    : True for stimulus ports (driven externally into the instance).
                  False for observable response ports (driven by the instance).
    """
    name     : str
    width    : int  = 1
    is_input : bool = True

    def sv_type(self) -> str:
        """Return a SystemVerilog type declaration fragment."""
        if self.width == 1:
            return "logic"
        return f"logic [{self.width - 1}:0]"


# ── DUTSpec ───────────────────────────────────────────────────────────────────

@dataclass
class DUTSpec:
    """
    Everything Dabih needs to know about the DUT to emit formal properties.

    Required fields
    ---------------
    top_module      : Name of the top-level RTL module to instantiate
                      in the property wrapper (e.g. "serdes_top").
    instance_fmt    : Hierarchical path to one instance relative to the top,
                      using {i} as the index placeholder:
                        "rx_gen[{i}].u_rx"
                        "lane[{i}]"
                        "gen_blk[{i}].inst"
    clk_port        : Clock port name on the top module.
    input_ports     : List of port names that constitute stimulus.
                      Symmetry is checked: if input[i] == input[j], then ...
    output_ports    : List of port names that constitute observable response.
                      ... then output[i] == output[j].

    Optional fields
    ---------------
    rst_port        : Reset port name.  If None, no disable iff clause is
                      emitted (reset-less design).
    rst_active_high : True if reset is active-high (default).
    top_ports       : Explicit list of top-module ports for the wrapper's
                      port declaration.  If empty, Dabih infers minimal ports
                      (clk, rst, plus array-indexed versions of input/output
                      ports for each instance index in the declaration).
    rtl_files       : RTL source files for the Questa Formal compile command.
                      Glob patterns are accepted (e.g. "rtl/*.sv").
    proof_depth     : SVA implication depth — the maximum number of cycles
                      between identical inputs and expected identical outputs.
                      Default 20.  Increase for deeply pipelined designs.
    questa_timeout  : Questa Formal verification timeout in seconds.
                      Default 3600 (1 hour).
    module_params   : Optional parameter overrides for the top module
                      instantiation, e.g. {"N_LANES": 4}.
    notes           : Free-text annotation included as a comment in emitted
                      files.  Documents why this symmetry claim is made.
    """
    # ── Required ──────────────────────────────────────────────────────────────
    top_module   : str
    instance_fmt : str               # e.g. "rx_gen[{i}].u_rx"
    clk_port     : str
    input_ports  : list[str]
    output_ports : list[str]

    # ── Optional ──────────────────────────────────────────────────────────────
    rst_port        : str | None       = None
    rst_active_high : bool             = True
    top_ports       : list[PortSpec]   = field(default_factory=list)
    rtl_files       : list[str]        = field(default_factory=list)
    proof_depth     : int              = 20
    questa_timeout  : int              = 3600
    module_params   : dict[str, int]   = field(default_factory=dict)
    notes           : str              = ""

    # ── Helpers ───────────────────────────────────────────────────────────────

    def instance_path(self, i: int) -> str:
        """Return the hierarchical path to instance i."""
        return self.instance_fmt.format(i=i)

    def signal_path(self, i: int, port: str) -> str:
        """Return the full hierarchical signal path: u_dut.<instance_path>.<port>."""
        return f"u_dut.{self.instance_path(i)}.{port}"

    def disable_clause(self) -> str:
        """Return the SVA disable iff clause, or empty string if no reset."""
        if self.rst_port is None:
            return ""
        polarity = "" if self.rst_active_high else "!"
        return f"disable iff ({polarity}{self.rst_port})"

    def rtl_file_list(self) -> str:
        """Return the RTL file list as a Tcl-compatible string."""
        if not self.rtl_files:
            return "[glob rtl/*.sv]"
        return " ".join(f'"{f}"' for f in self.rtl_files)

    def param_overrides_sv(self) -> str:
        """Return SystemVerilog parameter override string."""
        if not self.module_params:
            return ""
        items = ", ".join(f".{k}({v})" for k, v in self.module_params.items())
        return f"#({items})"

    def validate(self) -> None:
        """Raise ValueError if the spec is inconsistent."""
        if not self.top_module:
            raise ValueError("DUTSpec.top_module must not be empty.")
        if "{i}" not in self.instance_fmt:
            raise ValueError(
                f"DUTSpec.instance_fmt must contain {{i}} placeholder, "
                f"got: {self.instance_fmt!r}"
            )
        if not self.clk_port:
            raise ValueError("DUTSpec.clk_port must not be empty.")
        if not self.input_ports:
            raise ValueError("DUTSpec.input_ports must not be empty.")
        if not self.output_ports:
            raise ValueError("DUTSpec.output_ports must not be empty.")
        if self.proof_depth < 1:
            raise ValueError(f"DUTSpec.proof_depth must be ≥ 1, got {self.proof_depth}.")

    def __repr__(self) -> str:
        return (
            f"DUTSpec(top={self.top_module!r}, "
            f"fmt={self.instance_fmt!r}, "
            f"in={self.input_ports}, out={self.output_ports}, "
            f"depth={self.proof_depth})"
        )
