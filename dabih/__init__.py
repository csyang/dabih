"""Dabih — Coverage Model Compression via Equivalence Classes."""
from .core.bin_space import BinSpace, Orbit
from .core.coverpoint import Coverpoint, BinLabel
from .core.symmetry import Permutation, SymmetryGroup
from .rtl.generate_array import GenerateArray
from .rtl.extractor import RtlExtractor
from .rtl.bridge import CoverSpec, BridgeResult, BinSpaceBuilder, auto_build, bridge_report
from .coverage.result import CoverageResult, BinHit
from .coverage.expander import ExpansionEngine, ExpansionResult

from .core.symbolic import SymbolicOrbitEngine, SymmetryProfile, SymbolicLimitError
from .coverage.symbolic_expander import SymbolicExpansionEngine, SymbolicExpansionResult

from .formal import emit_symmetry_check
from .formal.spec import DUTSpec, PortSpec

__all__ = [
    # Core orbit engine (Idea B)
    "BinSpace", "Orbit",
    "Coverpoint", "BinLabel",
    "Permutation", "SymmetryGroup",
    # Symbolic orbit engine (Idea E)
    "SymbolicOrbitEngine", "SymmetryProfile", "SymbolicLimitError",
    # RTL extraction layer (Idea A)
    "GenerateArray",
    "RtlExtractor",
    "CoverSpec", "BridgeResult", "BinSpaceBuilder",
    "auto_build", "bridge_report",
    # Coverage post-processor (Idea C)
    "CoverageResult", "BinHit",
    "ExpansionEngine", "ExpansionResult",
    # Symbolic expansion (Idea E + C)
    "SymbolicExpansionEngine", "SymbolicExpansionResult",
    # Formal symmetry verification (Idea D)
    "emit_symmetry_check", "DUTSpec", "PortSpec",
]
