"""
dabih.adapters.questa
~~~~~~~~~~~~~~~~~~~~~
Adapter for Questa / ModelSim `vcover report -details` text output.

Typical invocation to produce the input file:

    vcover report -details -cvg <ucdb_file> > questa_report.txt

    # Or targeting a specific instance/design-unit:
    vcover report -details -cvg <ucdb_file> \\
        -du <design_unit> -inst <instance_path> > questa_report.txt

Parsed elements
---------------
Only **cross-coverage** bins are extracted.  Individual coverpoint bins
are ignored — Dabih's orbit engine operates on the cross space.

Cross bin format in Questa output:

    Cross lane0_state#lane1_state#lane2_state#lane3_state
        <IDLE,IDLE,IDLE,IDLE>     5     1     Covered
        <IDLE,ACTIVE,IDLE,IDLE>   3     1     Covered
        <ACTIVE,IDLE,IDLE,IDLE>   0     1     ZERO

The cross header uses `#` to join coverpoint names.
Each bin row begins with `<label0,label1,...>` followed by hit count.
Zero-hit bins are present in `-details` output; they are skipped
(Dabih treats absent bins as zero implicitly).

Multiple covergroups
--------------------
`vcover report` may output several covergroups in one file.  The
`covergroup` parameter selects the target by matching the TYPE name
(the string after `TYPE /path/`).  If `covergroup` is None, the first
cross-coverage section found is used.
"""

from __future__ import annotations

import re
from pathlib import Path

from ..coverage.result import BinHit, CoverageResult


# ── Regex patterns ────────────────────────────────────────────────────────────

# TYPE /tb/some_path/rx_lane_cross_cg rx_lane_cross_cg
_RE_CG_HEADER = re.compile(
    r"^\s*TYPE\s+\S+/(\S+)\s+(\S+)", re.IGNORECASE
)

# Cross lane0_state#lane1_state#...
_RE_CROSS_HEADER = re.compile(
    r"^\s*Cross\s+(\S+)", re.IGNORECASE
)

# <IDLE,ACTIVE,STALL,IDLE>    5    1    Covered
# Handles optional spaces inside angle brackets and after the closing >
_RE_CROSS_BIN = re.compile(
    r"^\s*<([^>]+)>\s+(\d+)\s+\d+\s+(\S+)"
)


# ── Parser ────────────────────────────────────────────────────────────────────

def _parse_cross_bins(
    lines: list[str],
    start: int,
) -> tuple[list[BinHit], int]:
    """
    Parse cross bin rows starting at `start`.  Stop when a line does not
    match the cross-bin pattern and is not blank/continuation.

    Returns (bin_hits, next_line_index).
    """
    hits: list[BinHit] = []
    i = start
    while i < len(lines):
        line = lines[i]
        m = _RE_CROSS_BIN.match(line)
        if m:
            raw_labels = m.group(1)
            count      = int(m.group(2))
            # Split on comma, strip whitespace from each label
            labels = tuple(lbl.strip() for lbl in raw_labels.split(","))
            if count > 0:
                hits.append(BinHit(labels=labels, count=count))
            i += 1
        elif line.strip() == "" or line.startswith(" ") or line.startswith("\t"):
            # Blank or indented line — could be continuation or spacing
            # Only advance if the NEXT non-blank line also looks like a bin
            i += 1
        else:
            break
    return hits, i


def _parse(
    text: str,
    covergroup: str | None,
    run_id: str,
    simulator: str,
) -> CoverageResult:
    lines = text.splitlines()
    n     = len(lines)

    in_target_cg   = covergroup is None   # if None, accept any first cross
    cross_hits: list[BinHit] = []
    found_cross    = False
    i = 0

    while i < n:
        line = lines[i]

        # Detect covergroup TYPE header
        m_cg = _RE_CG_HEADER.match(line)
        if m_cg:
            # Name is the shorter of the two captures (last path component
            # and the explicit name after the path).  Both should match.
            cg_name = m_cg.group(2).strip()
            if covergroup is None:
                in_target_cg = True
            else:
                in_target_cg = (cg_name == covergroup)
            i += 1
            continue

        if not in_target_cg:
            i += 1
            continue

        # Detect cross header inside target covergroup
        m_cross = _RE_CROSS_HEADER.match(line)
        if m_cross:
            found_cross = True
            i += 1
            bins, i = _parse_cross_bins(lines, i)
            cross_hits.extend(bins)
            if covergroup is not None:
                # We've captured the one cross we care about; done
                break
            continue

        i += 1

    if not found_cross and covergroup is not None:
        raise ValueError(
            f"Covergroup {covergroup!r} or its cross section not found in report. "
            f"Covergroups present: {_list_covergroups(text)}"
        )

    return CoverageResult(
        hits       = cross_hits,
        run_id     = run_id,
        simulator  = simulator,
        covergroup = covergroup or "",
    )


def _list_covergroups(text: str) -> list[str]:
    """Return all covergroup names found in the report text."""
    names = []
    for line in text.splitlines():
        m = _RE_CG_HEADER.match(line)
        if m:
            names.append(m.group(2).strip())
    return names


# ── Public API ─────────────────────────────────────────────────────────────────

def from_vcover_text(
    text: str,
    covergroup: str | None = None,
    run_id: str = "",
) -> CoverageResult:
    """
    Parse a Questa `vcover report -details` text string.

    Parameters
    ----------
    text        : Full content of the vcover report.
    covergroup  : Name of the covergroup to extract (as it appears after
                  `TYPE /path/` in the report header).  If None, the first
                  cross section found is used.
    run_id      : Optional label for this simulation run.

    Returns
    -------
    CoverageResult containing only cross-coverage bins with count > 0.
    """
    return _parse(text, covergroup, run_id, simulator="questa")


def from_vcover_report(
    path: str | Path,
    covergroup: str | None = None,
    run_id: str = "",
    encoding: str = "utf-8",
) -> CoverageResult:
    """
    Parse a Questa `vcover report -details` file from disk.

    Parameters
    ----------
    path        : Path to the report text file.
    covergroup  : Target covergroup name (see `from_vcover_text`).
    run_id      : Optional simulation run label.  Defaults to the file stem.
    encoding    : File encoding (default utf-8).

    Returns
    -------
    CoverageResult containing only cross-coverage bins with count > 0.
    """
    p = Path(path)
    text = p.read_text(encoding=encoding)
    return from_vcover_text(
        text,
        covergroup = covergroup,
        run_id     = run_id or p.stem,
    )


def list_covergroups(path: str | Path, encoding: str = "utf-8") -> list[str]:
    """Return all covergroup names present in a vcover report file."""
    return _list_covergroups(Path(path).read_text(encoding=encoding))
