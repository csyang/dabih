"""
dabih.adapters.vcs
~~~~~~~~~~~~~~~~~~
Adapter for Synopsys VCS `urg` text report output.

Typical invocation to produce the input file:

    urg -dir simv.vdb -report urgReport -format text
    # Output: urgReport/coverage.txt

    # Or targeting a specific testplan:
    urg -dir simv.vdb -tp <testplan> -report urgReport -format text

Parsed elements
---------------
Only **cross-coverage** bins are extracted.  Individual coverpoint bins
are ignored — Dabih's orbit engine operates on the cross space.

Cross bin format in VCS urg output:

    lane0_state##lane1_state##lane2_state##lane3_state
                             37.50%    100%   Uncovered
        bin <IDLE,IDLE,IDLE,IDLE>              5    1   Covered
        bin <IDLE,ACTIVE,IDLE,IDLE>            3    1   Covered
        bin <ACTIVE,IDLE,IDLE,IDLE>            0    1   Zero

VCS uses `##` (double hash) to join coverpoint names in cross headers,
distinguishing them from Questa's single `#`.
Each bin row begins with `bin <label0,label1,...>` followed by hit count.
Zero-hit bins (`Zero`) are skipped.

Covergroup detection
--------------------
VCS urg reports mark each covergroup section with a line of the form:

    /tb/some_path/rx_lane_cross_cg    66.67%    100%   Uncovered

The `covergroup` parameter matches the last component of this path
(i.e. the covergroup type name).  If `covergroup` is None, the first
cross section found is used.
"""

from __future__ import annotations

import re
from pathlib import Path

from ..coverage.result import BinHit, CoverageResult


# ── Regex patterns ────────────────────────────────────────────────────────────

# /tb/some_path/rx_lane_cross_cg    66.67%    100%   Uncovered
# The covergroup path line — first token begins with /
_RE_CG_HEADER = re.compile(
    r"^\s*(/\S+/(\S+))\s+[\d.]+%"
)

# lane0_state##lane1_state##... (cross header — double hash, no leading keyword)
# Must have ## present to distinguish from single coverpoint lines.
# The line may end immediately after the name (no trailing content).
_RE_CROSS_HEADER = re.compile(
    r"^\s+(\S+##\S+)\s*$|^\s+(\S+##\S+)\s"
)

# bin <IDLE,ACTIVE,STALL,IDLE>    5    1    Covered
_RE_CROSS_BIN = re.compile(
    r"^\s+bin\s+<([^>]+)>\s+(\d+)\s+\d+\s+(\S+)"
)


# ── Parser ────────────────────────────────────────────────────────────────────

def _parse_cross_bins(
    lines: list[str],
    start: int,
) -> tuple[list[BinHit], int]:
    """
    Parse cross bin rows starting at `start`.

    Stops when a non-bin, non-blank line is encountered.
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
            status     = m.group(3).lower()
            labels     = tuple(lbl.strip() for lbl in raw_labels.split(","))
            if count > 0 and status != "zero":
                hits.append(BinHit(labels=labels, count=count))
            i += 1
        elif line.strip() == "":
            i += 1
        else:
            # Check for another bin variant or stop
            if line.lstrip().startswith("bin "):
                i += 1   # malformed bin line — skip
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

    in_target_cg   = covergroup is None
    cross_hits: list[BinHit] = []
    found_cross    = False
    i = 0

    while i < n:
        line = lines[i]

        # Detect covergroup header line (starts with /)
        m_cg = _RE_CG_HEADER.match(line)
        if m_cg:
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

        # Detect cross header (double-hash name)
        m_cross = _RE_CROSS_HEADER.match(line)
        if m_cross:
            # Skip the metric/goal/status line that follows the cross name
            i += 1
            # Skip any lines between header and first bin row
            while i < n and not _RE_CROSS_BIN.match(lines[i]):
                if lines[i].strip() == "":
                    i += 1
                elif _RE_CROSS_HEADER.match(lines[i]):
                    break
                elif _RE_CG_HEADER.match(lines[i]):
                    break
                else:
                    i += 1

            found_cross = True
            bins, i = _parse_cross_bins(lines, i)
            cross_hits.extend(bins)

            if covergroup is not None:
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

def from_urg_text(
    text: str,
    covergroup: str | None = None,
    run_id: str = "",
) -> CoverageResult:
    """
    Parse a VCS `urg` text report string.

    Parameters
    ----------
    text        : Full content of the urg text report.
    covergroup  : Name of the target covergroup (last component of the
                  path in the report header, e.g. "rx_lane_cross_cg").
                  If None, the first cross section found is used.
    run_id      : Optional label for this simulation run.

    Returns
    -------
    CoverageResult containing only cross-coverage bins with count > 0.
    """
    return _parse(text, covergroup, run_id, simulator="vcs")


def from_urg_report(
    path: str | Path,
    covergroup: str | None = None,
    run_id: str = "",
    encoding: str = "utf-8",
) -> CoverageResult:
    """
    Parse a VCS `urg` text report file from disk.

    Parameters
    ----------
    path        : Path to the urg text report file (typically
                  urgReport/coverage.txt).
    covergroup  : Target covergroup name (see `from_urg_text`).
    run_id      : Optional simulation run label.  Defaults to the
                  parent directory name of the report file.
    encoding    : File encoding (default utf-8).

    Returns
    -------
    CoverageResult containing only cross-coverage bins with count > 0.
    """
    p = Path(path)
    text = p.read_text(encoding=encoding)
    default_id = p.parent.name if p.name == "coverage.txt" else p.stem
    return from_urg_text(
        text,
        covergroup = covergroup,
        run_id     = run_id or default_id,
    )


def list_covergroups(path: str | Path, encoding: str = "utf-8") -> list[str]:
    """Return all covergroup names present in a VCS urg report file."""
    return _list_covergroups(Path(path).read_text(encoding=encoding))
