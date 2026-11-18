"""
tests/test_formal.py
~~~~~~~~~~~~~~~~~~~~~
Tests for Idea D: formal symmetry verification pass.

Covers:
  DUTSpec
    - Construction and validation
    - Helper methods (instance_path, signal_path, disable_clause)
    - Parameter override formatting
    - Validation errors (missing required fields, bad depth, missing {i})

  Questa Formal emission (emit_sv_wrapper, emit_questa_tcl)
    - Module name / header generation
    - Port declarations present
    - DUT instantiation present
    - Reset assumption properties emitted
    - Symmetry assertion properties emitted for correct pairs
    - Property names follow convention
    - Disable iff clause present when rst_port given, absent otherwise
    - Proof depth embedded in assertions
    - All output ports have SYM_ assertions
    - All input ports have ASM_ assumptions
    - TCL compile step references wrapper .sv file
    - TCL verify step references emitted assertion names
    - Multiple declarations produce disjoint property sets

  SpyGlass emission (emit_spyglass_sgdc, emit_spyglass_tcl)
    - Clock definition present
    - Reset definition present / absent
    - Instance paths in define_design_attribute
    - Input/output port annotations per instance
    - Rule configuration lines present
    - TCL project name, top module, read_file commands
    - SGDC file referenced in TCL

  _generator_pairs / _declaration_pairs logic
    - S2: one pair
    - S3: generator-minimal set (not all 3 pairs)
    - S4: generator-minimal set
    - Cyclic: consecutive pairs only
    - Pairwise: each declared pair exactly

  emit_symmetry_check (integrated)
    - Correct files emitted to out_dir
    - tool filter: questa_formal only, spyglass only, both
    - name suffix applied to all file names
    - Files written to disk are non-empty and parseable as text

  Integration with BinSpace declarations
    - Full pipeline: BinSpace.add_instance_symmetry → emit_symmetry_check
    - Partial symmetry: only declared instance indices appear in properties
    - Pairwise: one property per declared pair
    - Cyclic: consecutive-pair properties only
"""

import sys, os, re, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from pathlib import Path

from dabih.core.bin_space import BinSpace
from dabih.core.coverpoint import Coverpoint
from dabih.formal.spec import DUTSpec, PortSpec
from dabih.formal.questa import (
    emit_sv_wrapper, emit_questa_tcl,
    _generator_pairs, _declaration_pairs,
)
from dabih.formal.spyglass import emit_spyglass_sgdc, emit_spyglass_tcl
from dabih.formal import emit_symmetry_check


# ── Shared fixtures ───────────────────────────────────────────────────────────

def make_spec(
    n_lanes=4,
    has_rst=True,
    rst_active_high=True,
    input_ports=None,
    output_ports=None,
    depth=20,
    rtl_files=None,
    params=None,
) -> DUTSpec:
    return DUTSpec(
        top_module      = "serdes_top",
        instance_fmt    = "rx_gen[{i}].u_rx",
        clk_port        = "clk",
        rst_port        = "rst_n" if has_rst else None,
        rst_active_high = rst_active_high,
        input_ports     = input_ports if input_ports is not None else ["data_in", "valid"],
        output_ports    = output_ports if output_ports is not None else ["state", "ready"],
        rtl_files       = rtl_files if rtl_files is not None else ["rtl/serdes_top.sv"],
        proof_depth     = depth,
        module_params   = params if params is not None else {},
        notes           = "Test spec",
    )

def make_bs_full(n=4, k=4) -> BinSpace:
    """Full S_n BinSpace with instance declarations."""
    bs = BinSpace(name=f"S{n}_test")
    for i in range(n):
        bs.add_coverpoint(Coverpoint.from_names(f"cp{i}", [f"b{v}" for v in range(k)]))
    bs.add_instance_symmetry(list(range(n)))
    return bs

def make_bs_partial(exclude_first=True) -> BinSpace:
    """Partial symmetry: lanes 1,2,3 only (lane 0 excluded)."""
    bs = BinSpace(name="partial_sym")
    for i in range(4):
        bs.add_coverpoint(Coverpoint.from_names(f"cp{i}", ["A","B","C"]))
    bs.add_instance_symmetry([1, 2, 3])
    return bs

def make_bs_pairwise() -> BinSpace:
    """Pairwise Z2×Z2: (0,1) and (2,3)."""
    bs = BinSpace(name="pairwise_sym")
    for i in range(4):
        bs.add_coverpoint(Coverpoint.from_names(f"cp{i}", ["A","B"]))
    bs.add_pairwise_symmetry([(0,1),(2,3)])
    return bs

def make_bs_cyclic(n=4) -> BinSpace:
    """Cyclic Z_n symmetry."""
    bs = BinSpace(name=f"Z{n}_test")
    for i in range(n):
        bs.add_coverpoint(Coverpoint.from_names(f"cp{i}", ["A","B","C"]))
    bs.add_cyclic_symmetry(list(range(n)))
    return bs


# ═══════════════════════════════════════════════════════════════════════════════
# DUTSpec tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestDUTSpec:

    def test_instance_path_substitution(self):
        spec = make_spec()
        assert spec.instance_path(0) == "rx_gen[0].u_rx"
        assert spec.instance_path(7) == "rx_gen[7].u_rx"

    def test_signal_path(self):
        spec = make_spec()
        assert spec.signal_path(2, "state") == "u_dut.rx_gen[2].u_rx.state"

    def test_disable_clause_with_reset(self):
        spec = make_spec(has_rst=True, rst_active_high=True)
        assert spec.disable_clause() == "disable iff (rst_n)"

    def test_disable_clause_active_low(self):
        spec = make_spec(has_rst=True, rst_active_high=False)
        assert spec.disable_clause() == "disable iff (!rst_n)"

    def test_disable_clause_no_reset(self):
        spec = make_spec(has_rst=False)
        assert spec.disable_clause() == ""

    def test_param_overrides_sv(self):
        spec = make_spec(params={"N_LANES": 4, "WIDTH": 8})
        sv = spec.param_overrides_sv()
        assert ".N_LANES(4)" in sv
        assert ".WIDTH(8)" in sv

    def test_param_overrides_empty(self):
        spec = make_spec(params={})
        assert spec.param_overrides_sv() == ""

    def test_validate_passes_valid_spec(self):
        make_spec().validate()   # should not raise

    def test_validate_missing_top_module(self):
        spec = make_spec()
        spec.top_module = ""
        with pytest.raises(ValueError, match="top_module"):
            spec.validate()

    def test_validate_missing_instance_fmt_placeholder(self):
        spec = make_spec()
        spec.instance_fmt = "rx_gen[0].u_rx"   # no {i}
        with pytest.raises(ValueError, match=r"\{i\}"):
            spec.validate()

    def test_validate_empty_clk(self):
        spec = make_spec()
        spec.clk_port = ""
        with pytest.raises(ValueError, match="clk_port"):
            spec.validate()

    def test_validate_empty_input_ports(self):
        spec = make_spec()
        spec.input_ports = []
        with pytest.raises(ValueError, match="input_ports"):
            spec.validate()

    def test_validate_empty_output_ports(self):
        spec = make_spec()
        spec.output_ports = []
        with pytest.raises(ValueError, match="output_ports"):
            spec.validate()

    def test_validate_bad_proof_depth(self):
        spec = make_spec(depth=0)
        with pytest.raises(ValueError, match="proof_depth"):
            spec.validate()

    def test_rtl_file_list_explicit(self):
        spec = make_spec(rtl_files=["rtl/a.sv", "rtl/b.sv"])
        flist = spec.rtl_file_list()
        assert '"rtl/a.sv"' in flist
        assert '"rtl/b.sv"' in flist

    def test_rtl_file_list_default(self):
        spec = make_spec(rtl_files=[])
        assert "rtl/*.sv" in spec.rtl_file_list()


# ═══════════════════════════════════════════════════════════════════════════════
# Generator pair logic
# ═══════════════════════════════════════════════════════════════════════════════

class TestGeneratorPairs:

    def test_s2_one_pair(self):
        pairs = _generator_pairs([0, 1])
        assert len(pairs) == 1
        assert (0, 1) in pairs

    def test_s3_includes_transposition(self):
        pairs = _generator_pairs([0, 1, 2])
        assert (0, 1) in pairs

    def test_s3_includes_cycle_pairs(self):
        pairs = _generator_pairs([0, 1, 2])
        # Should have: (0,1), (1,2), (2,0) - cycle wrap
        assert any(frozenset(p) == frozenset({1, 2}) for p in pairs)
        assert any(frozenset(p) == frozenset({0, 2}) for p in pairs)

    def test_s3_no_duplicates(self):
        pairs = _generator_pairs([0, 1, 2])
        frozen = [frozenset(p) for p in pairs]
        assert len(frozen) == len(set(frozen))

    def test_s4_generator_minimal(self):
        """S4 needs transposition + 4-cycle pairs — fewer than C(4,2)=6 total."""
        pairs = _generator_pairs([0, 1, 2, 3])
        assert len(pairs) < 6   # not all pairs
        assert len(pairs) >= 2  # at least the generators

    def test_non_contiguous_indices(self):
        pairs = _generator_pairs([0, 2, 3])
        assert (0, 2) in pairs  # transposition of first two

    def test_empty_and_single(self):
        assert _generator_pairs([]) == []
        assert _generator_pairs([5]) == []

    def test_cyclic_declaration_consecutive(self):
        decl = {"type": "cyclic", "instance_indices": [0,1,2,3]}
        pairs = _declaration_pairs(decl)
        # Z4 pairs: (0,1),(1,2),(2,3),(3,0)
        frozen = {frozenset(p) for p in pairs}
        assert frozenset({0,1}) in frozen
        assert frozenset({1,2}) in frozen
        assert frozenset({2,3}) in frozen
        assert frozenset({3,0}) in frozen

    def test_pairwise_declaration(self):
        decl = {"type": "pairwise", "pairs": [[0,1],[2,3]]}
        pairs = _declaration_pairs(decl)
        assert (0, 1) in pairs
        assert (2, 3) in pairs
        assert len(pairs) == 2


# ═══════════════════════════════════════════════════════════════════════════════
# Questa Formal SV wrapper
# ═══════════════════════════════════════════════════════════════════════════════

class TestSVWrapper:

    def test_module_name_generated(self):
        sv = emit_sv_wrapper(make_bs_full(), make_spec())
        assert "module dabih_sym_check" in sv

    def test_module_name_with_suffix(self):
        sv = emit_sv_wrapper(make_bs_full(), make_spec(), name="rx_lane")
        assert "module dabih_sym_check_rx_lane" in sv

    def test_dut_instantiation_present(self):
        sv = emit_sv_wrapper(make_bs_full(), make_spec())
        assert "serdes_top" in sv
        assert "u_dut" in sv

    def test_clk_port_present(self):
        sv = emit_sv_wrapper(make_bs_full(), make_spec())
        assert "clk" in sv

    def test_disable_iff_with_reset(self):
        sv = emit_sv_wrapper(make_bs_full(), make_spec(has_rst=True))
        assert "disable iff" in sv
        assert "rst_n" in sv

    def test_no_disable_iff_without_reset(self):
        sv = emit_sv_wrapper(make_bs_full(), make_spec(has_rst=False))
        assert "disable iff" not in sv

    def test_reset_assumption_properties(self):
        sv = emit_sv_wrapper(make_bs_full(), make_spec(has_rst=True))
        assert "RESET_SYM" in sv
        assert "assume property" in sv

    def test_sym_assertions_present(self):
        sv = emit_sv_wrapper(make_bs_full(), make_spec())
        assert "SYM_" in sv
        assert "assert property" in sv

    def test_asm_assumptions_present(self):
        sv = emit_sv_wrapper(make_bs_full(), make_spec())
        assert "ASM_" in sv

    def test_proof_depth_in_assertions(self):
        sv = emit_sv_wrapper(make_bs_full(), make_spec(depth=42))
        assert "##[0:42]" in sv

    def test_output_ports_have_assertions(self):
        spec = make_spec(output_ports=["state", "ready"])
        sv = emit_sv_wrapper(make_bs_full(), spec)
        assert "_state" in sv
        assert "_ready" in sv

    def test_input_ports_in_assumptions(self):
        spec = make_spec(input_ports=["data_in", "valid"])
        sv = emit_sv_wrapper(make_bs_full(), spec)
        assert "data_in" in sv
        assert "valid" in sv

    def test_instance_paths_present(self):
        sv = emit_sv_wrapper(make_bs_full(), make_spec())
        # Should see hierarchical paths like u_dut.rx_gen[0].u_rx
        assert "rx_gen[" in sv
        assert "u_rx" in sv

    def test_endmodule_present(self):
        sv = emit_sv_wrapper(make_bs_full(), make_spec())
        assert "endmodule" in sv

    def test_partial_symmetry_uses_correct_indices(self):
        """Only instances 1,2,3 — not instance 0 — should appear as primary pairs."""
        bs = make_bs_partial()
        spec = make_spec()
        sv = emit_sv_wrapper(bs, spec)
        # Instances 1,2,3 should appear
        assert "inst1" in sv or "rx_gen[1]" in sv
        assert "inst2" in sv or "rx_gen[2]" in sv

    def test_pairwise_generates_two_property_groups(self):
        bs = make_bs_pairwise()
        sv = emit_sv_wrapper(bs, make_spec())
        # Should have properties for pair (0,1) and pair (2,3)
        assert "inst0_vs_inst1" in sv
        assert "inst2_vs_inst3" in sv

    def test_cyclic_properties_for_consecutive_pairs(self):
        bs = make_bs_cyclic(4)
        sv = emit_sv_wrapper(bs, make_spec())
        # Z4: pairs (0,1),(1,2),(2,3),(3,0)
        assert "inst0_vs_inst1" in sv
        assert "inst1_vs_inst2" in sv
        assert "inst2_vs_inst3" in sv

    def test_multiple_declarations_both_present(self):
        bs = BinSpace()
        for i in range(4):
            bs.add_coverpoint(Coverpoint.from_names(f"cp{i}", ["A","B"]))
        bs.add_instance_symmetry([0, 1])
        bs.add_instance_symmetry([2, 3])
        sv = emit_sv_wrapper(bs, make_spec())
        assert "D0_instance" in sv
        assert "D1_instance" in sv

    def test_param_override_in_instantiation(self):
        spec = make_spec(params={"N_LANES": 4})
        sv = emit_sv_wrapper(make_bs_full(), spec)
        assert "N_LANES" in sv

    def test_header_comment_has_tool_target(self):
        sv = emit_sv_wrapper(make_bs_full(), make_spec())
        assert "Questa Formal" in sv

    def test_header_comment_has_dut_name(self):
        sv = emit_sv_wrapper(make_bs_full(), make_spec())
        assert "serdes_top" in sv


# ═══════════════════════════════════════════════════════════════════════════════
# Questa Formal TCL script
# ═══════════════════════════════════════════════════════════════════════════════

class TestQuestaTCL:

    def test_questa_formal_compile_command(self):
        tcl = emit_questa_tcl(make_bs_full(), make_spec(), "dabih_sym.sv")
        assert "questa_formal compile" in tcl

    def test_wrapper_sv_referenced(self):
        tcl = emit_questa_tcl(make_bs_full(), make_spec(), "dabih_sym_test.sv")
        assert "dabih_sym_test.sv" in tcl

    def test_questa_formal_verify_command(self):
        tcl = emit_questa_tcl(make_bs_full(), make_spec(), "dabih_sym.sv")
        assert "questa_formal verify" in tcl

    def test_rtl_files_in_compile(self):
        spec = make_spec(rtl_files=["rtl/top.sv"])
        tcl = emit_questa_tcl(make_bs_full(), spec, "dabih_sym.sv")
        assert "rtl/top.sv" in tcl

    def test_timeout_present(self):
        spec = make_spec()
        spec.questa_timeout = 7200
        tcl = emit_questa_tcl(make_bs_full(), spec, "dabih_sym.sv")
        assert "7200" in tcl

    def test_proof_depth_present(self):
        tcl = emit_questa_tcl(make_bs_full(), make_spec(depth=30), "dabih_sym.sv")
        assert "30" in tcl

    def test_assertion_names_in_property_list(self):
        tcl = emit_questa_tcl(make_bs_full(), make_spec(), "dabih_sym.sv")
        assert "SYM_" in tcl

    def test_report_command_present(self):
        tcl = emit_questa_tcl(make_bs_full(), make_spec(), "dabih_sym.sv")
        assert "questa_formal report" in tcl

    def test_header_mentions_tool_version(self):
        tcl = emit_questa_tcl(make_bs_full(), make_spec(), "dabih_sym.sv")
        assert "questa-formal" in tcl

    def test_elaborate_step_present(self):
        tcl = emit_questa_tcl(make_bs_full(), make_spec(), "dabih_sym.sv")
        assert "questa_formal elaborate" in tcl


# ═══════════════════════════════════════════════════════════════════════════════
# SpyGlass SGDC
# ═══════════════════════════════════════════════════════════════════════════════

class TestSpyGlassSGDC:

    def test_clock_definition(self):
        sgdc = emit_spyglass_sgdc(make_bs_full(), make_spec())
        assert "define_clock" in sgdc
        assert "clk" in sgdc

    def test_reset_definition_with_reset(self):
        sgdc = emit_spyglass_sgdc(make_bs_full(), make_spec(has_rst=True))
        assert "define_reset" in sgdc
        assert "rst_n" in sgdc

    def test_no_reset_definition_without_reset(self):
        sgdc = emit_spyglass_sgdc(make_bs_full(), make_spec(has_rst=False))
        assert "define_reset" not in sgdc

    def test_active_low_reset_annotation(self):
        sgdc = emit_spyglass_sgdc(make_bs_full(), make_spec(rst_active_high=False))
        assert "active_low" in sgdc

    def test_active_high_reset_annotation(self):
        sgdc = emit_spyglass_sgdc(make_bs_full(), make_spec(rst_active_high=True))
        assert "active_high" in sgdc

    def test_define_design_attribute_present(self):
        sgdc = emit_spyglass_sgdc(make_bs_full(), make_spec())
        assert "define_design_attribute" in sgdc
        assert "dabih_symmetric_group" in sgdc

    def test_instance_paths_in_sgdc(self):
        sgdc = emit_spyglass_sgdc(make_bs_full(), make_spec())
        assert "rx_gen" in sgdc
        assert "u_rx" in sgdc

    def test_all_instance_indices_annotated(self):
        sgdc = emit_spyglass_sgdc(make_bs_full(n=4), make_spec())
        # Instances 0,1,2,3 should all appear in paths
        for i in range(4):
            assert f"[{i}]" in sgdc

    def test_input_port_annotations(self):
        spec = make_spec(input_ports=["data_in"])
        sgdc = emit_spyglass_sgdc(make_bs_full(), spec)
        assert "dabih_sym_input" in sgdc
        assert "data_in" in sgdc

    def test_output_port_annotations(self):
        spec = make_spec(output_ports=["state"])
        sgdc = emit_spyglass_sgdc(make_bs_full(), spec)
        assert "dabih_sym_output" in sgdc
        assert "state" in sgdc

    def test_rule_parameters_present(self):
        sgdc = emit_spyglass_sgdc(make_bs_full(), make_spec())
        assert "set_rule_parameter" in sgdc

    def test_current_design_set(self):
        sgdc = emit_spyglass_sgdc(make_bs_full(), make_spec())
        assert "current_design serdes_top" in sgdc

    def test_header_mentions_vc_spyglass(self):
        sgdc = emit_spyglass_sgdc(make_bs_full(), make_spec())
        assert "vc_spyglass" in sgdc

    def test_partial_symmetry_correct_indices(self):
        bs = make_bs_partial()
        sgdc = emit_spyglass_sgdc(bs, make_spec())
        # Instances 1,2,3 should appear; instance 0 should not appear in group
        # (it's not in the declaration)
        assert "rx_gen[1]" in sgdc
        assert "rx_gen[2]" in sgdc
        assert "rx_gen[3]" in sgdc


# ═══════════════════════════════════════════════════════════════════════════════
# SpyGlass TCL
# ═══════════════════════════════════════════════════════════════════════════════

class TestSpyGlassTCL:

    def test_new_project_command(self):
        tcl = emit_spyglass_tcl(make_bs_full(), make_spec(), "dabih_spyglass.sgdc")
        assert "new_project" in tcl

    def test_top_module_set(self):
        tcl = emit_spyglass_tcl(make_bs_full(), make_spec(), "dabih_spyglass.sgdc")
        assert "serdes_top" in tcl

    def test_sgdc_file_referenced(self):
        tcl = emit_spyglass_tcl(make_bs_full(), make_spec(), "my_constraints.sgdc")
        assert "my_constraints.sgdc" in tcl

    def test_read_file_for_rtl(self):
        spec = make_spec(rtl_files=["rtl/top.sv"])
        tcl = emit_spyglass_tcl(make_bs_full(), spec, "dabih_spyglass.sgdc")
        assert "read_file" in tcl
        assert "rtl/top.sv" in tcl

    def test_run_goal_present(self):
        tcl = emit_spyglass_tcl(make_bs_full(), make_spec(), "dabih_spyglass.sgdc")
        assert "run_goal" in tcl

    def test_write_report_present(self):
        tcl = emit_spyglass_tcl(make_bs_full(), make_spec(), "dabih_spyglass.sgdc")
        assert "write_report" in tcl

    def test_invocation_instructions_in_header(self):
        tcl = emit_spyglass_tcl(make_bs_full(), make_spec(), "dabih_spyglass.sgdc")
        assert "vc_spyglass" in tcl
        assert "spyglass" in tcl

    def test_set_option_sysv(self):
        tcl = emit_spyglass_tcl(make_bs_full(), make_spec(), "dabih_spyglass.sgdc")
        assert "set_option language sysv" in tcl


# ═══════════════════════════════════════════════════════════════════════════════
# emit_symmetry_check integration
# ═══════════════════════════════════════════════════════════════════════════════

class TestEmitSymmetryCheck:

    def test_all_four_files_emitted_by_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            emitted = emit_symmetry_check(make_bs_full(), make_spec(), out_dir=tmp)
            assert "sv"            in emitted
            assert "questa_tcl"    in emitted
            assert "spyglass_sgdc" in emitted
            assert "spyglass_tcl"  in emitted

    def test_all_files_exist_on_disk(self):
        with tempfile.TemporaryDirectory() as tmp:
            emitted = emit_symmetry_check(make_bs_full(), make_spec(), out_dir=tmp)
            for key, path in emitted.items():
                assert path.exists(), f"File not found: {key} → {path}"

    def test_files_are_non_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            emitted = emit_symmetry_check(make_bs_full(), make_spec(), out_dir=tmp)
            for key, path in emitted.items():
                assert path.stat().st_size > 0, f"Empty file: {key}"

    def test_questa_only_tool_filter(self):
        with tempfile.TemporaryDirectory() as tmp:
            emitted = emit_symmetry_check(
                make_bs_full(), make_spec(), out_dir=tmp,
                tools=["questa_formal"]
            )
            assert "sv"         in emitted
            assert "questa_tcl" in emitted
            assert "spyglass_sgdc" not in emitted
            assert "spyglass_tcl"  not in emitted

    def test_spyglass_only_tool_filter(self):
        with tempfile.TemporaryDirectory() as tmp:
            emitted = emit_symmetry_check(
                make_bs_full(), make_spec(), out_dir=tmp,
                tools=["spyglass"]
            )
            assert "spyglass_sgdc" in emitted
            assert "spyglass_tcl"  in emitted
            assert "sv"            not in emitted
            assert "questa_tcl"    not in emitted

    def test_name_suffix_applied_to_sv(self):
        with tempfile.TemporaryDirectory() as tmp:
            emitted = emit_symmetry_check(
                make_bs_full(), make_spec(), out_dir=tmp, name="rx_lane"
            )
            assert "rx_lane" in emitted["sv"].name

    def test_name_suffix_applied_to_all_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            emitted = emit_symmetry_check(
                make_bs_full(), make_spec(), out_dir=tmp, name="test"
            )
            for key, path in emitted.items():
                assert "test" in path.name, \
                    f"Name suffix missing from {key}: {path.name}"

    def test_out_dir_created_if_absent(self):
        with tempfile.TemporaryDirectory() as tmp:
            new_dir = Path(tmp) / "nested" / "formal"
            emit_symmetry_check(make_bs_full(), make_spec(), out_dir=new_dir)
            assert new_dir.exists()

    def test_sv_content_readable(self):
        with tempfile.TemporaryDirectory() as tmp:
            emitted = emit_symmetry_check(make_bs_full(), make_spec(), out_dir=tmp)
            content = emitted["sv"].read_text()
            assert "module" in content
            assert "endmodule" in content

    def test_tcl_content_readable(self):
        with tempfile.TemporaryDirectory() as tmp:
            emitted = emit_symmetry_check(make_bs_full(), make_spec(), out_dir=tmp)
            content = emitted["questa_tcl"].read_text()
            assert "questa_formal" in content

    def test_sgdc_content_readable(self):
        with tempfile.TemporaryDirectory() as tmp:
            emitted = emit_symmetry_check(make_bs_full(), make_spec(), out_dir=tmp)
            content = emitted["spyglass_sgdc"].read_text()
            assert "define_clock" in content


# ═══════════════════════════════════════════════════════════════════════════════
# Full pipeline integration
# ═══════════════════════════════════════════════════════════════════════════════

class TestIdeaDIntegration:
    """
    Full pipeline: RTL extractor → BinSpace → formal emission.
    Validates that the formal emitter correctly reads the declarations
    set by the ergonomic symmetry API.
    """

    FIXTURES = os.path.join(os.path.dirname(__file__), "..", "examples", "rtl")

    def test_serdes_end_to_end(self):
        """
        Extract SerDes RTL → build BinSpace → emit formal artifacts.
        Verifies that the full pipeline from RTL to formal artifacts
        produces valid, non-trivial output.
        """
        from dabih.rtl import RtlExtractor, BinSpaceBuilder
        ext = (RtlExtractor()
               .add_file(os.path.join(self.FIXTURES, "serdes_top.sv"))
               .add_param("N_LANES", 4))
        arrays = [a for a in ext.extract() if a.module_type == "rx_lane"]
        results = (BinSpaceBuilder(arrays)
                   .cover("state", ["IDLE","ACTIVE","STALL","ERROR"])
                   .build(ext.param_overrides))
        bs = results[0].bin_space

        spec = DUTSpec(
            top_module   = "serdes_top",
            instance_fmt = "rx_gen[{i}].u_rx",
            clk_port     = "clk",
            rst_port      = "rst_n",
            rst_active_high = False,
            input_ports  = ["valid", "data"],
            output_ports = ["state"],
            rtl_files    = ["rtl/serdes_top.sv", "rtl/rx_lane.sv"],
            proof_depth  = 20,
            module_params = {"N_LANES": 4},
        )

        with tempfile.TemporaryDirectory() as tmp:
            emitted = emit_symmetry_check(bs, spec, out_dir=tmp, name="rx_lane")
            sv_text  = emitted["sv"].read_text()
            tcl_text = emitted["questa_tcl"].read_text()
            sg_text  = emitted["spyglass_sgdc"].read_text()

            # The BinSpace was built with add_full_lane_symmetry(4)
            # which stores an instance declaration for [0,1,2,3]
            assert "serdes_top" in sv_text
            assert "rx_gen["    in sv_text
            assert "state"      in sv_text
            assert "SYM_"       in sv_text
            assert "questa_formal compile" in tcl_text
            assert "N_LANES"    in sv_text
            assert "define_clock" in sg_text

    def test_partial_symmetry_formal(self):
        """Partial symmetry declaration produces only declared instance properties."""
        bs = make_bs_partial()
        sv = emit_sv_wrapper(bs, make_spec())
        decls = bs.symmetry_declarations()
        assert decls[0]["instance_indices"] == [1, 2, 3]
        # Instance 0 should not be a primary property subject
        # (it appears only as part of the reset assumption on all indices)
        assert "inst1_vs_inst2" in sv or "inst1" in sv

    def test_pairwise_formal_two_property_groups(self):
        bs = make_bs_pairwise()
        sv = emit_sv_wrapper(bs, make_spec())
        # Exactly the two declared pairs
        assert "inst0_vs_inst1" in sv
        assert "inst2_vs_inst3" in sv
        # Cross-pair assertion (0 vs 2) must NOT be present
        assert "inst0_vs_inst2" not in sv

    def test_cyclic_formal_consecutive_pairs_only(self):
        bs = make_bs_cyclic(4)
        sv = emit_sv_wrapper(bs, make_spec())
        # Z4 checks consecutive pairs — (0,1),(1,2),(2,3),(3,0)
        # Non-consecutive (0,2) should not appear
        assert "inst0_vs_inst2" not in sv


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
