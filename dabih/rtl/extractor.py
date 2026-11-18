"""
dabih.rtl.extractor
~~~~~~~~~~~~~~~~~~~
Walks the pyslang Concrete Syntax Tree to detect generate-for loops that
instantiate replicated module arrays, which constitute structurally provable
symmetry groups for coverage compression.

Design
------
Uses pyslang.syntax.SyntaxTree (parse-only, no elaboration required).
This means:
  - Parameter-based bounds (i < N) are resolved by looking for a default
    value in the enclosing module's parameter list, then by user-supplied
    param_overrides.
  - No simulator or elaboration tool is needed — the extractor runs on raw
    RTL sources with zero external dependencies beyond pyslang.

The extractor produces GenerateArray objects.  These are then wired to
BinSpace instances by the user, who supplies the coverpoints that correspond
to each instantiated module.

Detected pattern
----------------
    for (genvar i = 0; i < <bound>; i++) begin [: <label>]
        <module_type> [#(...)] <instance_name> (...);
    end

Where <bound> is either an integer literal or a parameter identifier.

Not detected (out of scope for Idea A)
---------------------------------------
  - if-generate symmetry
  - Loops with non-unit stride (i += 2)
  - Loops with non-zero start (i = 1)
  - Multiple module types within one generate block
  - Nested generate loops (reported as separate arrays)
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable

try:
    import pyslang.syntax as _syn
    _PYSLANG_AVAILABLE = True
except ImportError:
    _PYSLANG_AVAILABLE = False

from .generate_array import GenerateArray


# ── Internal CST helpers ──────────────────────────────────────────────────────

def _iter_children(node):
    """Safely iterate CST children, skipping tokens."""
    try:
        for child in node:
            if child is not None:
                yield child
    except TypeError:
        pass


def _extract_label(block) -> str | None:
    """Extract named block label from a GenerateBlock's beginName node."""
    try:
        bn = block.beginName
        if bn is None:
            return None
        return str(bn.name).strip() or None
    except AttributeError:
        return None


def _extract_bound(stop_expr) -> tuple[str, int | None, str | None]:
    """
    Parse the stop expression of a for-generate loop.

    Returns (bound_kind, bound_value, bound_param):
      - ("literal",  N,    None)   for   i < 4
      - ("param",    None, "N")    for   i < N
      - ("unknown",  None, None)   for anything else
    """
    kind = str(stop_expr.kind)
    if "LessThan" not in kind:
        return ("unknown", None, None)
    try:
        rhs = stop_expr.right
        rhs_kind = str(rhs.kind)
        rhs_str = str(rhs).strip()
        if "IntegerLiteral" in rhs_kind:
            return ("literal", int(rhs_str), None)
        if "IdentifierName" in rhs_kind:
            return ("param", None, rhs_str)
    except (AttributeError, ValueError):
        pass
    return ("unknown", None, None)


def _extract_param_default(module_decl, param_name: str) -> int | None:
    """
    Search a ModuleDeclaration's parameter port list for `param_name` and
    return its default integer value if present and parseable.

    CST path:
        ModuleHeader
          ParameterPortList
            ParameterDeclaration          ← direct child
              Declarator
                Identifier                ← param name
                EqualsValueClause
                  IntegerLiteralExpression ← default value
    """
    try:
        params = module_decl.header.parameters
        if params is None:
            return None
        # ParameterDeclaration nodes are direct children of ParameterPortList
        for child in _iter_children(params):
            if "ParameterDeclaration" not in str(child.kind):
                continue
            for decl_node in _iter_children(child):
                if "Declarator" not in str(decl_node.kind):
                    continue
                # Check the Identifier token matches param_name
                try:
                    ident = str(decl_node.name).strip()
                except AttributeError:
                    continue
                if ident != param_name:
                    continue
                # Found the right declarator — extract the initializer value
                try:
                    init = decl_node.initializer  # EqualsValueClause node
                    if init is None:
                        return None
                    # Walk initializer children for the integer literal
                    for init_child in _iter_children(init):
                        ik = str(init_child.kind)
                        if "IntegerLiteral" in ik:
                            val_str = str(init_child).strip()
                            m = re.search(r"\d+", val_str)
                            if m:
                                return int(m.group())
                except AttributeError:
                    pass
    except Exception:
        pass
    return None


def _extract_module_name(module_decl) -> str:
    """Return the module name from a ModuleDeclaration node."""
    try:
        return str(module_decl.header.name).strip()
    except AttributeError:
        return "<unknown>"


def _walk_module(module_decl, source_file: str) -> list[GenerateArray]:
    """Walk one ModuleDeclaration and collect all generate-for arrays."""
    module_name = _extract_module_name(module_decl)
    results = []

    def walk(node):
        kind = str(node.kind)

        if "LoopGenerate" in kind:
            _process_loop(node, module_decl, module_name, source_file, results)
            # Still recurse — nested loops are independent arrays
            for child in _iter_children(node.block):
                walk(child)
            return  # don't double-recurse the block

        for child in _iter_children(node):
            walk(child)

    walk(module_decl)
    return results


def _process_loop(
    loop_node,
    module_decl,
    module_name: str,
    source_file: str,
    results: list[GenerateArray],
) -> None:
    """
    Extract one LoopGenerate node into a GenerateArray, if it matches the
    supported pattern (single module type, unit stride, zero-based start).
    """
    try:
        genvar = str(loop_node.identifier).strip()
        bound_kind, bound_value, bound_param = _extract_bound(loop_node.stopExpr)
        if bound_kind == "unknown":
            return  # unsupported stop expression

        block = loop_node.block
        label = _extract_label(block)

        # Find instantiated module type(s) in the block members
        instantiations = []
        for member in block.members:
            if "HierarchyInstantiation" in str(member.kind):
                mod_type = str(member.type).strip()
                for inst in member.instances:
                    inst_base = str(inst.decl).strip()
                    instantiations.append((mod_type, inst_base))

        if not instantiations:
            return  # no module instantiations in this block

        # Resolve parameter default if needed
        param_default = None
        if bound_kind == "param" and bound_param:
            param_default = _extract_param_default(module_decl, bound_param)

        # Approximate source line from sourceRange
        try:
            loc = loop_node.sourceRange
            line = int(str(loc).split(":")[1]) if ":" in str(loc) else 0
        except Exception:
            line = 0

        # One GenerateArray per distinct (module_type, instance_base) pair.
        # Usually there is exactly one; guard against unusual multi-instance blocks.
        seen = set()
        for mod_type, inst_base in instantiations:
            key = (mod_type, inst_base)
            if key in seen:
                continue
            seen.add(key)
            results.append(GenerateArray(
                parent_module = module_name,
                block_label   = label,
                module_type   = mod_type,
                instance_base = inst_base,
                genvar        = genvar,
                bound_kind    = bound_kind,
                bound_value   = bound_value,
                bound_param   = bound_param,
                param_default = param_default,
                source_file   = source_file,
                source_line   = line,
            ))

    except Exception:
        # Robustness: a malformed or unsupported node should not crash the tool
        pass


# ── RtlExtractor ──────────────────────────────────────────────────────────────

class RtlExtractor:
    """
    Scans RTL source files for generate-for loops and extracts the resulting
    GenerateArray symmetry descriptors.

    Usage
    -----
        ext = (RtlExtractor()
               .add_file("rtl/top.sv")
               .add_file("rtl/rx_lane.sv")
               .add_param("N_LANES", 8))

        arrays = ext.extract()
        print(ext.report())

        # Wire to BinSpace manually:
        for arr in arrays:
            bs = BinSpace(name=str(arr))
            n = arr.count(ext.param_overrides)
            for i in range(n):
                bs.add_coverpoint(Coverpoint.from_names(
                    f"{arr.instance_base}[{i}]_state",
                    ["IDLE", "ACTIVE", "STALL", "ERROR"]
                ))
            bs.add_full_lane_symmetry(n)
    """

    def __init__(self):
        if not _PYSLANG_AVAILABLE:
            raise ImportError(
                "pyslang is required for RTL extraction.  "
                "Install with: pip install pyslang"
            )
        self._files: list[str] = []
        self.param_overrides: dict[str, int] = {}
        self._cached_arrays: list[GenerateArray] | None = None

    # ── Builder ───────────────────────────────────────────────────────────────

    def add_file(self, path: str | Path) -> RtlExtractor:
        """Add a SystemVerilog source file to scan."""
        self._files.append(str(path))
        self._cached_arrays = None
        return self

    def add_files(self, paths: Iterable[str | Path]) -> RtlExtractor:
        for p in paths:
            self.add_file(p)
        return self

    def add_param(self, name: str, value: int) -> RtlExtractor:
        """
        Provide a top-level parameter override for bound resolution.
        Used when the generate bound is a parameter without a default.
        """
        self.param_overrides[name] = value
        self._cached_arrays = None
        return self

    # ── Extraction ────────────────────────────────────────────────────────────

    def extract(self) -> list[GenerateArray]:
        """
        Parse all registered source files and return detected generate arrays.

        Results are cached; re-runs only if files or params change.
        Sorted by (source_file, source_line) for stable output.
        """
        if self._cached_arrays is not None:
            return self._cached_arrays

        arrays: list[GenerateArray] = []

        for src in self._files:
            try:
                tree = _syn.SyntaxTree.fromFile(src)
            except Exception as exc:
                raise RuntimeError(f"Failed to parse {src!r}: {exc}") from exc

            arrays.extend(self._extract_from_tree(tree, src))

        # Stable sort
        arrays.sort(key=lambda a: (a.source_file, a.source_line, a.parent_module))
        self._cached_arrays = arrays
        return arrays

    def _extract_from_tree(
        self, tree, source_file: str
    ) -> list[GenerateArray]:
        """Walk one syntax tree and return all GenerateArrays found."""
        results = []

        def walk(node):
            kind = str(node.kind)
            if "ModuleDeclaration" in kind:
                results.extend(_walk_module(node, source_file))
                return  # _walk_module recurses internally
            for child in _iter_children(node):
                walk(child)

        walk(tree.root)
        return results

    # ── Filtered views ────────────────────────────────────────────────────────

    def arrays_for_module(self, module_type: str) -> list[GenerateArray]:
        """All generate arrays that instantiate a given module type."""
        return [a for a in self.extract() if a.module_type == module_type]

    def arrays_in_parent(self, parent_module: str) -> list[GenerateArray]:
        """All generate arrays declared inside a given parent module."""
        return [a for a in self.extract() if a.parent_module == parent_module]

    def unresolved(self) -> list[GenerateArray]:
        """Arrays whose count cannot be determined without more information."""
        return [
            a for a in self.extract()
            if a.count(self.param_overrides) is None
        ]

    # ── Report ────────────────────────────────────────────────────────────────

    def report(self) -> str:
        """Return a formatted summary of all detected generate arrays."""
        arrays = self.extract()
        W = 70
        lines = [
            "═" * W,
            "  Dabih — RTL Generate Array Extraction Report",
            "═" * W,
            f"  Files scanned  : {len(self._files)}",
            f"  Arrays detected: {len(arrays)}",
            f"  Unresolved     : {len(self.unresolved())}",
            "─" * W,
        ]

        if not arrays:
            lines.append("  No generate-for module arrays detected.")
        else:
            col = f"  {'Parent Module':<22} {'Module Type':<18} {'N':>4}  {'Block Label':<18}  Source"
            lines.append(col)
            lines.append("  " + "-" * (W - 2))
            for a in arrays:
                n = a.count(self.param_overrides)
                n_str = str(n) if n is not None else "?"
                label = a.block_label or "-"
                fname = Path(a.source_file).name
                unres = "  ⚠ unresolved" if n is None else ""
                lines.append(
                    f"  {a.parent_module:<22} {a.module_type:<18} {n_str:>4}  "
                    f"{label:<18}  {fname}{unres}"
                )

        lines.append("═" * W)
        return "\n".join(lines)
