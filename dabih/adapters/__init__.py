"""
dabih.adapters
~~~~~~~~~~~~~~
Simulator-native coverage report adapters.

Each adapter parses a simulator's text coverage output and produces a
`CoverageResult` consumable by Dabih's expansion engine — no EDA license
or binary tool required at post-processing time.

Available adapters
------------------
questa   — Questa / ModelSim `vcover report -details` text output
vcs      — Synopsys VCS `urg` text report output

Both adapters follow the same contract:

    from dabih.adapters.questa import from_vcover_report
    from dabih.adapters.vcs    import from_urg_report

    cr = from_vcover_report(path, covergroup="lane_cross_cg")
    cr = from_urg_report(path, covergroup="lane_cross_cg")

The `covergroup` parameter selects which covergroup to extract.
Both return a `CoverageResult` containing only the **cross-coverage bins**
that were hit (count > 0); individual coverpoint bins are not included,
as Dabih's orbit engine works on the cross space.
"""

from .questa import from_vcover_report, from_vcover_text
from .vcs    import from_urg_report, from_urg_text

__all__ = [
    "from_vcover_report", "from_vcover_text",
    "from_urg_report",    "from_urg_text",
]
