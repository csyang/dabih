"""
dabih.core.coverpoint
~~~~~~~~~~~~~~~~~~~~~
Data structures for coverpoints and their bins.

A Coverpoint is an observable signal region with a finite set of named bins.
The bin *index* (position in the list) is the handle used by the symmetry
and orbit engines; the bin *label* is the human-readable name returned in
reports and emitted coverage specs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable


# ── BinLabel ─────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class BinLabel:
    """A named bin within a coverpoint, optionally annotated with a value."""
    name: str
    value: int | None = None

    def __str__(self) -> str:
        return self.name

    def __repr__(self) -> str:
        v = f", value={self.value}" if self.value is not None else ""
        return f"BinLabel({self.name!r}{v})"


# ── Coverpoint ────────────────────────────────────────────────────────────────

class Coverpoint:
    """
    A single dimension in a cross-coverage space.

    Bins are stored in insertion order; their index is used as the
    coordinate in BinTuple throughout the orbit engine.

    Builder pattern
    ---------------
        cp = (Coverpoint("lane_state")
              .add_bin("IDLE")
              .add_bin("ACTIVE")
              .add_bin("STALL")
              .add_bin("ERROR"))

    Convenience constructors
    ------------------------
        cp = Coverpoint.from_range("addr", 0, 15)     # 16 bins: addr_0 .. addr_15
        cp = Coverpoint.from_names("opcode", ["ADD","SUB","MUL","DIV"])
    """

    def __init__(self, name: str):
        self.name = name
        self._bins: list[BinLabel] = []

    # ── Builder methods ───────────────────────────────────────────────────────

    def add_bin(self, name: str, value: int | None = None) -> Coverpoint:
        self._bins.append(BinLabel(name, value))
        return self

    def add_bins(self, names: Iterable[str]) -> Coverpoint:
        for n in names:
            self.add_bin(n)
        return self

    # ── Convenience constructors ──────────────────────────────────────────────

    @classmethod
    def from_names(cls, name: str, bin_names: Iterable[str]) -> Coverpoint:
        return cls(name).add_bins(bin_names)

    @classmethod
    def from_range(
        cls,
        name: str,
        lo: int,
        hi: int,
        prefix: str | None = None,
    ) -> Coverpoint:
        """
        Create a coverpoint with bins for each integer in [lo, hi].
        Bin name: f"{prefix}{value}" or f"{name}_{value}" if prefix is None.
        """
        pfx = prefix if prefix is not None else f"{name}_"
        cp = cls(name)
        for v in range(lo, hi + 1):
            cp.add_bin(f"{pfx}{v}", value=v)
        return cp

    @classmethod
    def value_class_bins(cls, name: str) -> Coverpoint:
        """
        Standard value equivalence partitioning for a data field:
            zero | one_hot | boundary_lo | boundary_hi | interior | all_ones
        Covers the six behaviorally distinct value classes.
        """
        return cls.from_names(
            name,
            ["ZERO", "ONE_HOT", "BOUNDARY_LO", "BOUNDARY_HI", "INTERIOR", "ALL_ONES"],
        )

    # ── Inspection ────────────────────────────────────────────────────────────

    @property
    def bins(self) -> list[BinLabel]:
        return list(self._bins)

    def bin_count(self) -> int:
        return len(self._bins)

    def bin_label(self, index: int) -> str:
        return self._bins[index].name

    def bin_value(self, index: int) -> int | None:
        return self._bins[index].value

    def __repr__(self) -> str:
        return (
            f"Coverpoint({self.name!r}, "
            f"bins=[{', '.join(b.name for b in self._bins)}])"
        )
