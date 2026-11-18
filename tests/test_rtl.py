"""
tests/test_rtl.py
~~~~~~~~~~~~~~~~~
Tests for Idea A: RTL symmetry extraction via pyslang CST walking.

Covers:
  - GenerateArray data class (count resolution, path generation)
  - RtlExtractor (literal bounds, parameter bounds, label extraction,
                  multi-file, multi-module, non-generate filtering)
  - BinSpaceBuilder bridge (coverpoint wiring, block permutations, orbit counts)
  - bridge_report formatting
"""

import sys
import os
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dabih.rtl.generate_array import GenerateArray
from dabih.rtl.extractor import RtlExtractor
from dabih.rtl.bridge import (
    CoverSpec, BinSpaceBuilder, BridgeResult, auto_build, bridge_report
)

FIXTURES = os.path.join(os.path.dirname(__file__), "..", "examples", "rtl")

def fixture(name: str) -> str:
    return os.path.join(FIXTURES, name)


# ═══════════════════════════════════════════════════════════════════════════════
# GenerateArray unit tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestGenerateArray:

    def _make(self, **kwargs) -> GenerateArray:
        defaults = dict(
            parent_module="top", block_label="lane_gen",
            module_type="rx_lane", instance_base="u_rx",
            genvar="i", bound_kind="literal", bound_value=4,
            bound_param=None, param_default=None,
            source_file="top.sv", source_line=10,
        )
        defaults.update(kwargs)
        return GenerateArray(**defaults)

    def test_literal_count(self):
        arr = self._make(bound_kind="literal", bound_value=8)
        assert arr.count() == 8

    def test_param_count_from_default(self):
        arr = self._make(bound_kind="param", bound_value=None,
                         bound_param="N", param_default=6)
        assert arr.count() == 6

    def test_param_count_from_override(self):
        arr = self._make(bound_kind="param", bound_value=None,
                         bound_param="N", param_default=4)
        assert arr.count({"N": 16}) == 16

    def test_param_count_unresolvable(self):
        arr = self._make(bound_kind="param", bound_value=None,
                         bound_param="N", param_default=None)
        assert arr.count() is None
        assert arr.count({}) is None

    def test_instance_paths_literal(self):
        arr = self._make(bound_kind="literal", bound_value=3,
                         parent_module="top", block_label="rx_gen",
                         instance_base="u_rx")
        paths = arr.instance_paths()
        assert paths == [
            "top.rx_gen[0].u_rx",
            "top.rx_gen[1].u_rx",
            "top.rx_gen[2].u_rx",
        ]

    def test_instance_paths_no_label(self):
        arr = self._make(bound_kind="literal", bound_value=2,
                         block_label=None, parent_module="top",
                         instance_base="u_lane")
        paths = arr.instance_paths()
        assert paths == ["top[0].u_lane", "top[1].u_lane"]

    def test_instance_paths_unresolvable_is_empty(self):
        arr = self._make(bound_kind="param", bound_value=None,
                         bound_param="N", param_default=None)
        assert arr.instance_paths() == []

    def test_str_repr(self):
        arr = self._make()
        s = str(arr)
        assert "rx_lane" in s
        assert "top" in s


# ═══════════════════════════════════════════════════════════════════════════════
# RtlExtractor tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestRtlExtractor:

    # ── serdes_top.sv ─────────────────────────────────────────────────────────

    def test_serdes_detects_two_arrays(self):
        ext = RtlExtractor().add_file(fixture("serdes_top.sv"))
        arrays = ext.extract()
        assert len(arrays) == 2

    def test_serdes_module_types(self):
        ext = RtlExtractor().add_file(fixture("serdes_top.sv"))
        types = {a.module_type for a in ext.extract()}
        assert "rx_lane" in types
        assert "tx_lane" in types

    def test_serdes_parent_module(self):
        ext = RtlExtractor().add_file(fixture("serdes_top.sv"))
        parents = {a.parent_module for a in ext.extract()}
        assert parents == {"serdes_top"}

    def test_serdes_block_labels(self):
        ext = RtlExtractor().add_file(fixture("serdes_top.sv"))
        labels = {a.block_label for a in ext.extract()}
        assert "rx_gen" in labels
        assert "tx_gen" in labels

    def test_serdes_bound_is_param(self):
        ext = RtlExtractor().add_file(fixture("serdes_top.sv"))
        for arr in ext.extract():
            assert arr.bound_kind == "param"
            assert arr.bound_param == "N_LANES"

    def test_serdes_default_resolves_to_4(self):
        ext = RtlExtractor().add_file(fixture("serdes_top.sv"))
        for arr in ext.extract():
            # Default N_LANES = 4 in the source
            assert arr.count() == 4

    def test_serdes_param_override(self):
        ext = RtlExtractor().add_file(fixture("serdes_top.sv"))
        ext.add_param("N_LANES", 8)
        for arr in ext.extract():
            assert arr.count(ext.param_overrides) == 8

    def test_serdes_instance_bases(self):
        ext = RtlExtractor().add_file(fixture("serdes_top.sv"))
        bases = {a.instance_base for a in ext.extract()}
        assert "u_rx" in bases
        assert "u_tx" in bases

    # ── mem_ctrl.sv ───────────────────────────────────────────────────────────

    def test_mem_ctrl_literal_bound(self):
        ext = RtlExtractor().add_file(fixture("mem_ctrl.sv"))
        arrays = ext.extract()
        assert len(arrays) == 1
        arr = arrays[0]
        assert arr.bound_kind == "literal"
        assert arr.bound_value == 8
        assert arr.count() == 8

    def test_mem_ctrl_module_type(self):
        ext = RtlExtractor().add_file(fixture("mem_ctrl.sv"))
        assert ext.extract()[0].module_type == "mem_channel"

    def test_mem_ctrl_instance_base(self):
        ext = RtlExtractor().add_file(fixture("mem_ctrl.sv"))
        assert ext.extract()[0].instance_base == "u_ch"

    # ── mixed_top.sv ──────────────────────────────────────────────────────────

    def test_mixed_only_detects_generate_array(self):
        """Non-replicated instances (ctrl, arbiter) must not appear."""
        ext = RtlExtractor().add_file(fixture("mixed_top.sv"))
        arrays = ext.extract()
        assert len(arrays) == 1
        assert arrays[0].module_type == "pipe_stage"

    def test_mixed_param_default_resolves(self):
        ext = RtlExtractor().add_file(fixture("mixed_top.sv"))
        arr = ext.extract()[0]
        assert arr.count() == 6   # N_STAGES default = 6

    # ── multi_module.sv ───────────────────────────────────────────────────────

    def test_multi_module_two_arrays(self):
        ext = RtlExtractor().add_file(fixture("multi_module.sv"))
        arrays = ext.extract()
        assert len(arrays) == 2

    def test_multi_module_parent_attribution(self):
        ext = RtlExtractor().add_file(fixture("multi_module.sv"))
        parents = {a.parent_module for a in ext.extract()}
        assert "alu_top" in parents
        assert "mac_array" in parents

    def test_multi_module_counts(self):
        ext = RtlExtractor().add_file(fixture("multi_module.sv"))
        counts = {}
        for a in ext.extract():
            counts[a.parent_module] = a.count()
        # alu_top: N_SLICES default = 4
        assert counts.get("alu_top") == 4
        # mac_array: literal 8
        assert counts.get("mac_array") == 8

    # ── Multi-file ────────────────────────────────────────────────────────────

    def test_multi_file_aggregates(self):
        ext = (RtlExtractor()
               .add_file(fixture("serdes_top.sv"))
               .add_file(fixture("mem_ctrl.sv")))
        arrays = ext.extract()
        # serdes: 2, mem_ctrl: 1
        assert len(arrays) == 3

    # ── Filtered views ────────────────────────────────────────────────────────

    def test_arrays_for_module(self):
        ext = RtlExtractor().add_file(fixture("serdes_top.sv"))
        rx = ext.arrays_for_module("rx_lane")
        assert len(rx) == 1
        assert rx[0].module_type == "rx_lane"

    def test_arrays_in_parent(self):
        ext = (RtlExtractor()
               .add_file(fixture("serdes_top.sv"))
               .add_file(fixture("mem_ctrl.sv")))
        serdes = ext.arrays_in_parent("serdes_top")
        assert len(serdes) == 2

    def test_unresolved_with_no_default_or_override(self):
        # Write a temp SV with a parameter bound and NO default
        sv = '''
module m (input logic v);
endmodule
module top_no_default #(parameter int N) (input logic [3:0] v);
    for (genvar i = 0; i < N; i++) begin : gen
        m u (.v(v[i]));
    end
endmodule
'''
        import tempfile, os
        with tempfile.NamedTemporaryFile(suffix=".sv", mode="w", delete=False) as f:
            f.write(sv)
            tmp = f.name
        try:
            ext = RtlExtractor().add_file(tmp)
            arrays = ext.extract()
            assert len(arrays) == 1
            assert arrays[0].count() is None
            assert len(ext.unresolved()) == 1
        finally:
            os.unlink(tmp)

    def test_missing_file_raises(self):
        ext = RtlExtractor().add_file("/nonexistent/path/foo.sv")
        with pytest.raises(RuntimeError, match="Failed to parse"):
            ext.extract()

    # ── Report ────────────────────────────────────────────────────────────────

    def test_report_contains_module_names(self):
        ext = RtlExtractor().add_file(fixture("serdes_top.sv"))
        report = ext.report()
        assert "rx_lane" in report
        assert "tx_lane" in report
        assert "serdes_top" in report


# ═══════════════════════════════════════════════════════════════════════════════
# BinSpaceBuilder / Bridge tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestBinSpaceBuilder:

    def _serdes_arrays(self, n_lanes: int = 4) -> list:
        ext = (RtlExtractor()
               .add_file(fixture("serdes_top.sv"))
               .add_param("N_LANES", n_lanes))
        return ext.extract()

    def _mem_arrays(self) -> list:
        ext = RtlExtractor().add_file(fixture("mem_ctrl.sv"))
        return ext.extract()

    # ── Basic wiring ─────────────────────────────────────────────────────────

    def test_build_produces_one_result_per_matching_array(self):
        arrays = self._serdes_arrays(4)
        results = (BinSpaceBuilder(arrays)
                   .cover("state", ["IDLE","ACTIVE","STALL","ERROR"])
                   .build({"N_LANES": 4}))
        assert len(results) == 2

    def test_build_per_module_type(self):
        arrays = self._serdes_arrays(4)
        results = (BinSpaceBuilder(arrays)
                   .cover("state", ["IDLE","ACTIVE","STALL","ERROR"],
                          module_type="rx_lane")
                   .cover("tx_st", ["IDLE","SEND","FLUSH"],
                          module_type="tx_lane")
                   .build({"N_LANES": 4}))
        assert len(results) == 2

    def test_no_matching_spec_skips_array(self):
        arrays = self._serdes_arrays(4)
        results = (BinSpaceBuilder(arrays)
                   .cover("state", ["A","B"], module_type="nonexistent")
                   .build({"N_LANES": 4}))
        assert len(results) == 0

    def test_unresolvable_count_skipped(self):
        import tempfile, os
        sv = '''
module m (input logic v);
endmodule
module t #(parameter int N) (input logic v);
    for (genvar i = 0; i < N; i++) begin : g
        m u (.v(v));
    end
endmodule
'''
        with tempfile.NamedTemporaryFile(suffix=".sv", mode="w", delete=False) as f:
            f.write(sv)
            tmp = f.name
        try:
            ext = RtlExtractor().add_file(tmp)
            arrays = ext.extract()
            results = (BinSpaceBuilder(arrays)
                       .cover("state", ["A","B"])
                       .build())   # no override → unresolvable
            assert len(results) == 0
        finally:
            os.unlink(tmp)

    # ── Coverpoint count ─────────────────────────────────────────────────────

    def test_coverpoint_count_single_signal(self):
        """n_lanes instances × 1 signal = n_lanes coverpoints."""
        arrays = self._serdes_arrays(4)
        rx_arrays = [a for a in arrays if a.module_type == "rx_lane"]
        results = (BinSpaceBuilder(rx_arrays)
                   .cover("state", ["IDLE","ACTIVE","STALL","ERROR"])
                   .build({"N_LANES": 4}))
        assert len(results) == 1
        bs = results[0].bin_space
        assert len(bs._coverpoints) == 4   # 4 instances × 1 signal

    def test_coverpoint_count_two_signals(self):
        """4 instances × 2 signals = 8 coverpoints."""
        arrays = self._serdes_arrays(4)
        rx_arrays = [a for a in arrays if a.module_type == "rx_lane"]
        results = (BinSpaceBuilder(rx_arrays)
                   .cover("state", ["IDLE","ACTIVE","STALL","ERROR"])
                   .cover("ready", ["LO","HI"])
                   .build({"N_LANES": 4}))
        bs = results[0].bin_space
        assert len(bs._coverpoints) == 8   # 4 instances × 2 signals

    # ── Orbit counts (mathematical correctness) ───────────────────────────────

    def test_single_signal_s4_orbit_count(self):
        """
        S4 on 4 instances, 4-bin state:
        orbit count = multisets(4 bins, 4 instances) = C(7,4) = 35.
        """
        arrays = self._serdes_arrays(4)
        rx = [a for a in arrays if a.module_type == "rx_lane"]
        results = (BinSpaceBuilder(rx)
                   .cover("state", ["IDLE","ACTIVE","STALL","ERROR"])
                   .build({"N_LANES": 4}))
        bs = results[0].bin_space
        assert bs.orbit_count() == 35    # C(4+4-1, 4) = C(7,4)

    def test_single_signal_s8_orbit_count(self):
        """
        S8 on 8 channels, 3-bin state:
        orbit count = C(3+8-1, 8) = C(10,8) = C(10,2) = 45.
        """
        arrays = self._mem_arrays()
        results = (BinSpaceBuilder(arrays)
                   .cover("ch_state", ["IDLE","BUSY","ERROR"])
                   .build())
        bs = results[0].bin_space
        # 8 instances, 3 bins: C(10,8)=45
        assert bs.orbit_count() == 45

    def test_two_signal_block_symmetry(self):
        """
        2 instances, 2 signals each (state:4bins, ready:2bins):
        Full space = (4×2)^2 = 64 bins.
        S2 block symmetry: orbits = fixed(swap(0,1)) / 2 + fixed
        Symmetry on blocks of size 2: multisets of 2 from (4×2)=8 combos
        = C(8+2-1,2) = C(9,2) = 36.
        """
        import tempfile, os
        sv = '''
module rx_lane (input logic valid, output logic [1:0] state, output logic ready);
endmodule
module t (input logic [1:0] valid, output logic [1:0] state [1:0], output logic ready [1:0]);
    for (genvar i = 0; i < 2; i++) begin : rx_gen
        rx_lane u_rx (.valid(valid[i]), .state(state[i]), .ready(ready[i]));
    end
endmodule
'''
        with tempfile.NamedTemporaryFile(suffix=".sv", mode="w", delete=False) as f:
            f.write(sv)
            tmp = f.name
        try:
            ext = RtlExtractor().add_file(tmp)
            arrays = ext.extract()
            results = (BinSpaceBuilder(arrays)
                       .cover("state", ["IDLE","ACTIVE","STALL","ERROR"])
                       .cover("ready", ["LO","HI"])
                       .build())
            bs = results[0].bin_space
            # 2 instances × 2 signals = 4 coverpoints
            # bins per intra-instance combo: 4×2 = 8
            # S2 block-symmetry orbit count = C(9,2) = 36
            assert bs.orbit_count() == 36
        finally:
            os.unlink(tmp)

    # ── Compression metrics ───────────────────────────────────────────────────

    def test_compression_improves_with_lane_count(self):
        """More lanes → higher compression ratio."""
        ratios = []
        for n in [2, 4, 8]:
            ext = (RtlExtractor()
                   .add_file(fixture("serdes_top.sv"))
                   .add_param("N_LANES", n))
            arrays = [a for a in ext.extract() if a.module_type == "rx_lane"]
            results = (BinSpaceBuilder(arrays)
                       .cover("state", ["IDLE","ACTIVE","STALL","ERROR"])
                       .build({"N_LANES": n}))
            ratios.append(results[0].compression_ratio())
        assert ratios[0] < ratios[1] < ratios[2]

    def test_bridge_result_str(self):
        arrays = self._serdes_arrays(4)
        results = (BinSpaceBuilder(arrays)
                   .cover("state", ["IDLE","ACTIVE","STALL","ERROR"])
                   .build({"N_LANES": 4}))
        for r in results:
            s = str(r)
            assert "bins" in s
            assert "orbits" in s

    # ── auto_build ────────────────────────────────────────────────────────────

    def test_auto_build_default_spec(self):
        arrays = self._serdes_arrays(4)
        results = auto_build(arrays, param_overrides={"N_LANES": 4})
        assert len(results) == 2

    def test_auto_build_custom_specs(self):
        arrays = self._mem_arrays()
        specs = [
            CoverSpec("ch_state", ["IDLE","BUSY","DRAIN","ERROR"],
                      module_type="mem_channel"),
        ]
        results = auto_build(arrays, cover_specs=specs)
        assert len(results) == 1
        assert results[0].n_instances == 8

    # ── bridge_report ─────────────────────────────────────────────────────────

    def test_bridge_report_content(self):
        arrays = self._serdes_arrays(4)
        results = (BinSpaceBuilder(arrays)
                   .cover("state", ["IDLE","ACTIVE","STALL","ERROR"])
                   .build({"N_LANES": 4}))
        report = bridge_report(results)
        assert "rx_lane" in report
        assert "tx_lane" in report
        assert "TOTAL" in report

    # ── cover_value_classes ───────────────────────────────────────────────────

    def test_cover_value_classes_bins(self):
        arrays = self._mem_arrays()
        results = (BinSpaceBuilder(arrays)
                   .cover_value_classes("data")
                   .build())
        bs = results[0].bin_space
        # 8 instances × 6 bins: C(6+8-1,8) = C(13,8) = 1287
        assert bs.orbit_count() == 1287


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
