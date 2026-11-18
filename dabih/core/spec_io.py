"""
dabih.core.spec_io
~~~~~~~~~~~~~~~~~~
Serialise and deserialise a BinSpace to/from Dabih's portable spec JSON
format.

The spec file is the contract between `dabih spec` (which runs RTL extraction
and builds the BinSpace) and `dabih expand` / `dabih report` / `dabih verify`
(which consume the compressed coverage model without re-running extraction).

Schema (version 1)
------------------
{
  "version"          : "1",
  "name"             : str,                 // BinSpace.name
  "coverpoints"      : [                    // in insertion order
    {"name": str, "bins": [str, ...]}
  ],
  "declarations"     : [                    // from _symmetry_declarations
    {
      "type"              : str,            // "instance"|"cyclic"|"pairwise"
      "instance_indices"  : [int, ...],     // for instance/cyclic
      "pairs"             : [[int,int],...],// for pairwise
      "block_size"        : int,
      "group"             : str,
      "n_generators"      : int
    }
  ],
  "orbit_count"      : int,
  "total_bins"       : int,
  "compression_ratio": float,
  "method"           : str,                 // "polya"|"burnside"
  "representatives"  : [[str,...],...]      // label-tuples, one per orbit
}

Round-trip guarantee
--------------------
  bs2 = load_bin_space(dump_bin_space(bs1))
  assert bs2.orbit_count()     == bs1.orbit_count()
  assert bs2.total_bin_count() == bs1.total_bin_count()
  assert bs2.compression_ratio() == bs1.compression_ratio()
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Union

from .bin_space import BinSpace, BinTuple
from .coverpoint import Coverpoint
from .symbolic import SymbolicOrbitEngine


# ── Version ───────────────────────────────────────────────────────────────────

SPEC_VERSION = "1"


# ── Dump ─────────────────────────────────────────────────────────────────────

def dump_bin_space(bs: BinSpace) -> dict:
    """
    Serialise a BinSpace to a plain dict (JSON-safe).

    Computes and caches:
    - orbit count and method (via SymbolicOrbitEngine for large spaces)
    - representatives as label-tuples (pre-computed for fast expand)
    """
    sym_eng   = SymbolicOrbitEngine(bs)
    n_orbits  = sym_eng.count_orbits()
    method    = sym_eng.method_used()
    total     = bs.total_bin_count()
    ratio     = total / n_orbits if n_orbits else 1.0
    reps      = sym_eng.representatives()
    rep_labels = [list(bs.bin_label(r)) for r in reps]

    return {
        "version"          : SPEC_VERSION,
        "name"             : bs.name,
        "coverpoints"      : [
            {"name": cp.name, "bins": [b.name for b in cp.bins]}
            for cp in bs._coverpoints
        ],
        "declarations"     : list(getattr(bs, "_symmetry_declarations", [])),
        "orbit_count"      : n_orbits,
        "total_bins"       : total,
        "compression_ratio": round(ratio, 4),
        "method"           : method,
        "representatives"  : rep_labels,
    }


def save_bin_space(bs: BinSpace, path: Union[str, Path], indent: int = 2) -> None:
    """Write a BinSpace spec JSON to disk."""
    Path(path).write_text(json.dumps(dump_bin_space(bs), indent=indent))


# ── Load ──────────────────────────────────────────────────────────────────────

def load_bin_space(data: dict) -> BinSpace:
    """
    Reconstruct a BinSpace from a spec dict.

    Coverpoints and declarations are fully restored.  The resulting BinSpace
    has the same orbit structure as the original.
    """
    version = data.get("version", "1")
    if version != SPEC_VERSION:
        raise ValueError(
            f"Unsupported spec version {version!r} (expected {SPEC_VERSION!r}). "
            f"Re-run 'dabih spec' to regenerate."
        )

    bs = BinSpace(name=data.get("name", ""))

    # Restore coverpoints
    for cp_data in data.get("coverpoints", []):
        bs.add_coverpoint(
            Coverpoint.from_names(cp_data["name"], cp_data["bins"])
        )

    # Restore symmetry declarations via the ergonomic API — this re-populates
    # both the group generators and the _symmetry_declarations store.
    for decl in data.get("declarations", []):
        dtype = decl.get("type", "instance")
        s     = decl.get("block_size", 1)
        if dtype == "instance":
            bs.add_instance_symmetry(decl["instance_indices"], block_size=s)
        elif dtype == "cyclic":
            bs.add_cyclic_symmetry(decl["instance_indices"], block_size=s)
        elif dtype == "pairwise":
            bs.add_pairwise_symmetry(
                [tuple(p) for p in decl["pairs"]], block_size=s
            )

    return bs


def load_bin_space_file(path: Union[str, Path]) -> BinSpace:
    """Load a BinSpace from a spec JSON file on disk."""
    data = json.loads(Path(path).read_text())
    return load_bin_space(data)


def load_representatives(data: dict) -> list[tuple]:
    """
    Load the pre-computed representative label-tuples from a spec dict.

    Returns a list of label-tuples (tuple of str), one per orbit.
    Faster than recomputing from BinSpace for large spaces.
    """
    return [tuple(r) for r in data.get("representatives", [])]


def load_spec_file(path: Union[str, Path]) -> dict:
    """Load and return the raw spec dict from disk."""
    return json.loads(Path(path).read_text())
