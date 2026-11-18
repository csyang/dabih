"""
dabih.rtl.generate_array
~~~~~~~~~~~~~~~~~~~~~~~~
Data class representing one generate-for loop containing module instantiations.

A GenerateArray is the atomic unit of structurally provable symmetry: all N
instances of the same module type inside a generate-for loop are equivalent
by construction, giving a symmetry group of at least S_N on those coverpoints.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable


@dataclass
class GenerateArray:
    """
    One generate-for loop that instantiates N copies of the same module.

    Attributes
    ----------
    parent_module   : Name of the enclosing module (e.g. "top")
    block_label     : Named begin/end block label (e.g. "lane_gen"), or None
    module_type     : Module being instantiated (e.g. "rx_lane")
    instance_base   : Instance name pattern inside the loop (e.g. "u_lane")
    genvar          : Loop variable name (e.g. "i")
    bound_kind      : "literal" if the bound is a numeric constant,
                      "param"   if it references a module parameter
    bound_value     : Resolved integer count, or None if unresolved
    bound_param     : Parameter name when bound_kind == "param" (e.g. "N")
    param_default   : Default value of bound_param if found in the module
                      header, or None
    source_file     : Path to the source file containing this loop
    source_line     : Approximate source line number
    """

    parent_module : str
    block_label   : str | None
    module_type   : str
    instance_base : str
    genvar        : str
    bound_kind    : str         # "literal" | "param"
    bound_value   : int | None  # set for literals; resolved params override this
    bound_param   : str | None  # parameter name if bound_kind == "param"
    param_default : int | None  # default value of the parameter, if parseable
    source_file   : str
    source_line   : int = 0

    # ── Count resolution ──────────────────────────────────────────────────────

    def count(self, param_overrides: dict[str, int] | None = None) -> int | None:
        """
        Return the number of instances in this array.

        For literal bounds this is immediate.
        For parameter bounds, checks (in order):
          1. param_overrides[bound_param]
          2. param_default (from the source module header)
          3. None — unresolved

        Parameters
        ----------
        param_overrides :
            Dict mapping parameter names to resolved integer values.
            Overrides the default found in the source.
        """
        if self.bound_kind == "literal":
            return self.bound_value

        name = self.bound_param
        if param_overrides and name in param_overrides:
            return param_overrides[name]
        if self.param_default is not None:
            return self.param_default
        return None

    # ── Hierarchical path helpers ─────────────────────────────────────────────

    def instance_paths(self, param_overrides: dict[str, int] | None = None) -> list[str]:
        """
        Return the list of hierarchical instance paths this array creates.

        Example:  ["top.lane_gen[0].u_lane", "top.lane_gen[1].u_lane", ...]
        """
        n = self.count(param_overrides)
        if n is None:
            return []
        block = f".{self.block_label}" if self.block_label else ""
        return [
            f"{self.parent_module}{block}[{i}].{self.instance_base}"
            for i in range(n)
        ]

    # ── Display ───────────────────────────────────────────────────────────────

    def bound_str(self) -> str:
        if self.bound_kind == "literal":
            return str(self.bound_value)
        default = f"={self.param_default}" if self.param_default is not None else ""
        return f"{self.bound_param}{default} (parameter)"

    def __str__(self) -> str:
        label = f":{self.block_label}" if self.block_label else ""
        return (
            f"{self.parent_module}{label}  "
            f"for({self.genvar}<{self.bound_str()})  "
            f"{self.module_type} × {self.count() or '?'}"
        )

    def __repr__(self) -> str:
        return (
            f"GenerateArray(parent={self.parent_module!r}, "
            f"module={self.module_type!r}, "
            f"count={self.count()})"
        )
