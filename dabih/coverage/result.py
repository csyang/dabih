"""
dabih.coverage.result
~~~~~~~~~~~~~~~~~~~~~
Data classes representing raw simulation coverage output.

The canonical Dabih coverage result format is a simple JSON file that a
UVM testbench or simulator wrapper can emit without EDA toolchain APIs.
UCDB (Questa/VCS) and other proprietary formats are out of scope here;
adapters from those formats are a later concern.

Canonical JSON schema
---------------------
{
  "run_id"     : "sim_run_042",          // optional
  "simulator"  : "questa",              // optional
  "timestamp"  : "2026-05-22T10:30:00", // optional ISO-8601
  "covergroup" : "lane_cross_cg",       // optional, for documentation
  "hits" : [
    { "bin": ["IDLE",   "IDLE",   "IDLE"  ], "count": 47 },
    { "bin": ["ACTIVE", "IDLE",   "ACTIVE"], "count":  3 },
    { "bin": ["STALL",  "ACTIVE", "IDLE"  ], "count":  1 }
  ]
}

Rules
-----
- `bin` is an ordered list of bin *label strings*, one per coverpoint in the
  target BinSpace.  Order must match the coverpoint insertion order.
- Only bins that were *actually hit* during simulation need to appear.
  Omitted bins are treated as zero-hit (uncovered).
- `count` is the raw hit count (≥ 1).  The expander only needs hit/not-hit,
  but preserving counts enables future weighted-coverage analysis.
- Bins that appear in the file but cannot be resolved in the BinSpace are
  flagged as unresolved (not silently dropped).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Iterable

# A bin identified by its label tuple (human-readable names, not indices).
LabelTuple = tuple[str, ...]


# ── BinHit ────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class BinHit:
    """One bin that was observed during simulation."""
    labels : LabelTuple   # e.g. ("IDLE", "ACTIVE", "STALL")
    count  : int = 1      # raw hit count from simulator


# ── CoverageResult ────────────────────────────────────────────────────────────

@dataclass
class CoverageResult:
    """
    Raw simulation coverage output: the set of bins hit, with hit counts.

    Constructed directly or loaded from the canonical JSON format via
    CoverageResult.from_json() / CoverageResult.from_file().

    The result does not know about the BinSpace or orbit structure — that
    mapping is performed by the ExpansionEngine.
    """
    hits       : list[BinHit] = field(default_factory=list)
    run_id     : str = ""
    simulator  : str = ""
    timestamp  : str = ""
    covergroup : str = ""

    # ── Construction ─────────────────────────────────────────────────────────

    @classmethod
    def from_hits(
        cls,
        hits: Iterable[tuple[tuple, int] | tuple],
        **meta,
    ) -> CoverageResult:
        """
        Convenience constructor from an iterable of (label_tuple, count) pairs
        or bare label_tuples (count defaults to 1).

        Example:
            CoverageResult.from_hits([
                (("IDLE", "IDLE", "IDLE"), 47),
                (("ACTIVE", "IDLE", "ACTIVE"),),   # count=1
            ])
        """
        bin_hits = []
        for item in hits:
            if isinstance(item[0], (list, tuple)):
                labels = tuple(item[0])
                count  = item[1] if len(item) > 1 else 1
            else:
                labels = tuple(item)
                count  = 1
            bin_hits.append(BinHit(labels=labels, count=count))
        return cls(hits=bin_hits, **meta)

    @classmethod
    def from_json(cls, text: str) -> CoverageResult:
        """Parse the canonical Dabih JSON format from a string."""
        data = json.loads(text)
        hits = []
        for entry in data.get("hits", []):
            labels = tuple(str(b) for b in entry["bin"])
            count  = int(entry.get("count", 1))
            hits.append(BinHit(labels=labels, count=count))
        return cls(
            hits       = hits,
            run_id     = data.get("run_id",    ""),
            simulator  = data.get("simulator", ""),
            timestamp  = data.get("timestamp", ""),
            covergroup = data.get("covergroup",""),
        )

    @classmethod
    def from_file(cls, path: str | Path) -> CoverageResult:
        """Load from a JSON file on disk."""
        return cls.from_json(Path(path).read_text())

    # ── Serialisation ─────────────────────────────────────────────────────────

    def to_dict(self) -> dict:
        """Serialise to a plain dict (round-trips cleanly through JSON)."""
        d: dict = {}
        if self.run_id:     d["run_id"]     = self.run_id
        if self.simulator:  d["simulator"]  = self.simulator
        if self.timestamp:  d["timestamp"]  = self.timestamp
        if self.covergroup: d["covergroup"] = self.covergroup
        d["hits"] = [
            {"bin": list(h.labels), "count": h.count}
            for h in self.hits
        ]
        return d

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)

    def save(self, path: str | Path) -> None:
        Path(path).write_text(self.to_json())

    # ── Inspection ────────────────────────────────────────────────────────────

    def hit_labels(self) -> set[LabelTuple]:
        """Set of all label-tuples with at least one hit."""
        return {h.labels for h in self.hits}

    def hit_count(self, labels: LabelTuple) -> int:
        """Hit count for a specific label-tuple (0 if not present)."""
        for h in self.hits:
            if h.labels == labels:
                return h.count
        return 0

    def total_hits(self) -> int:
        return sum(h.count for h in self.hits)

    def __len__(self) -> int:
        return len(self.hits)

    def __repr__(self) -> str:
        return (
            f"CoverageResult(bins_hit={len(self.hits)}, "
            f"total_hits={self.total_hits()}, "
            f"run_id={self.run_id!r})"
        )
