"""
examples/python/rtl_demo.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~
End-to-end demonstration of Idea A:

    SystemVerilog sources → pyslang CST → GenerateArrays → BinSpaces
    → compressed coverage model with full orbit report

Three scenarios:
  1. SerDes top (parameter-bound, 4 → 8 lane scaling, two module types)
  2. Memory controller (literal-bound, 8 channels, value-class bins)
  3. Mixed design (generate + non-generate, verifying non-generate is ignored)

Run:  python examples/python/rtl_demo.py
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from dabih.rtl import (
    RtlExtractor, BinSpaceBuilder, CoverSpec,
    auto_build, bridge_report,
)

FIXTURES = os.path.join(os.path.dirname(__file__), "..", "rtl")

def fx(name: str) -> str:
    return os.path.join(FIXTURES, name)


# ─────────────────────────────────────────────────────────────────────────────
# Scenario 1: SerDes top — parameter-bound lanes, two module types
# ─────────────────────────────────────────────────────────────────────────────

def demo_serdes():
    print("\n" + "▓" * 70)
    print("  SCENARIO 1: SerDes Top — Parameter-Bound Lane Arrays")
    print("▓" * 70)
    print("""
  RTL file: serdes_top.sv
    module serdes_top #(parameter int N_LANES = 4) ( ... )
      for (genvar i = 0; i < N_LANES; i++) begin : rx_gen
          rx_lane u_rx ( ... );
      end
      for (genvar j = 0; j < N_LANES; j++) begin : tx_gen
          tx_lane u_tx ( ... );
      end
  """)

    # N_LANES = 4: full multi-signal coverage (state × ready cross)
    print(f"  {'─'*66}")
    print(f"  N_LANES = 4  (state:4bins × ready:2bins → (4×2)^4 = 4,096 bins)")

    ext4 = (RtlExtractor()
            .add_file(fx("serdes_top.sv"))
            .add_param("N_LANES", 4))
    print(ext4.report())

    results4 = (BinSpaceBuilder(ext4.extract())
                .cover("state", ["IDLE", "ACTIVE", "STALL", "ERROR"],
                       module_type="rx_lane")
                .cover("ready", ["LO", "HI"],
                       module_type="rx_lane")
                .cover("tx_state", ["IDLE", "SEND", "FLUSH", "ERROR"],
                       module_type="tx_lane")
                .build(ext4.param_overrides))

    print(bridge_report(results4))
    rx4 = next(r for r in results4 if r.array.module_type == "rx_lane")
    print(rx4.bin_space.report(max_orbits=10))

    # N_LANES = 8: single-signal only to stay within enumeration limits.
    # (4×2)^8 = 16.7M bins exceeds practical BFS capacity in pure Python;
    # multi-signal 8-lane coverage requires the symbolic orbit engine
    # planned for a later Dabih milestone.
    print(f"\n  {'─'*66}")
    print(f"  N_LANES = 8  (state:4bins only → 4^8 = 65,536 bins)")
    print(f"  Note: multi-signal cross at n=8 reaches 16M bins — symbolic")
    print(f"        orbit enumeration (future milestone) handles that range.")

    ext8 = (RtlExtractor()
            .add_file(fx("serdes_top.sv"))
            .add_param("N_LANES", 8))
    print(ext8.report())

    results8 = (BinSpaceBuilder(ext8.extract())
                .cover("state", ["IDLE", "ACTIVE", "STALL", "ERROR"],
                       module_type="rx_lane")
                .cover("tx_state", ["IDLE", "SEND", "FLUSH", "ERROR"],
                       module_type="tx_lane")
                .build(ext8.param_overrides))

    print(bridge_report(results8))


# ─────────────────────────────────────────────────────────────────────────────
# Scenario 2: Memory controller — literal bound, value-class bins
# ─────────────────────────────────────────────────────────────────────────────

def demo_mem_ctrl():
    print("\n" + "▓" * 70)
    print("  SCENARIO 2: Memory Controller — Literal Bound + Value Classes")
    print("▓" * 70)
    print("""
  RTL file: mem_ctrl.sv
    module mem_ctrl ( ... )
      for (genvar i = 0; i < 8; i++) begin : ch_gen
          mem_channel u_ch ( ... );
      end

  8 channels, literal bound — no parameter lookup needed.

  Tractability note:
    Single signal (ch_state, 4 bins): 4^8 = 65,536 → 165 orbits   ✓
    Two signals   (state×addr_class): (4×6)^8 ≈ 110B bins          ✗
    Multi-signal cross at 8+ instances requires the symbolic orbit
    engine (planned future milestone); enumeration-based BFS is
    bounded to roughly 1M bins in pure Python.
  """)

    ext = RtlExtractor().add_file(fx("mem_ctrl.sv"))
    print(ext.report())

    # Single signal — tractable at n=8
    results = (BinSpaceBuilder(ext.extract())
               .cover("ch_state", ["IDLE", "ACTIVE", "DRAIN", "ERROR"])
               .build())

    print(bridge_report(results))
    print(results[0].bin_space.report(max_orbits=12))


# ─────────────────────────────────────────────────────────────────────────────
# Scenario 3: Mixed design — verify non-generate instances are filtered
# ─────────────────────────────────────────────────────────────────────────────

def demo_mixed():
    print("\n" + "▓" * 70)
    print("  SCENARIO 3: Mixed Design — Generate + Non-Generate Filtering")
    print("▓" * 70)
    print("""
  RTL file: mixed_top.sv
    module mixed_top #(parameter int N_STAGES = 6) ( ... )
      for (genvar i = 0; i < N_STAGES; i++) begin : pipe_gen
          pipe_stage u_stage ( ... );    ← DETECTED
      end
      global_ctrl u_ctrl ( ... );        ← ignored (not generate)
      arbiter     u_arb  ( ... );        ← ignored (not generate)

  Only the generate-for array should appear in output.
  """)

    ext = RtlExtractor().add_file(fx("mixed_top.sv"))
    print(ext.report())

    results = auto_build(
        ext.extract(),
        cover_specs=[
            CoverSpec("stage_state", ["EMPTY","FILLING","FULL","FLUSHING"],
                      module_type="pipe_stage"),
        ],
    )

    print(bridge_report(results))
    print(results[0].bin_space.report(max_orbits=15))


# ─────────────────────────────────────────────────────────────────────────────
# Scenario 4: Multi-file scan — full project
# ─────────────────────────────────────────────────────────────────────────────

def demo_multi_file():
    print("\n" + "▓" * 70)
    print("  SCENARIO 4: Multi-File Project Scan")
    print("▓" * 70)
    print("""
  Scanning all fixture files in one pass — shows the project-level
  aggregated extraction and compression summary.
  """)

    ext = (RtlExtractor()
           .add_files([
               fx("serdes_top.sv"),
               fx("mem_ctrl.sv"),
               fx("mixed_top.sv"),
               fx("multi_module.sv"),
           ])
           .add_param("N_LANES", 4))

    print(ext.report())

    specs = [
        CoverSpec("state",       ["IDLE","ACTIVE","STALL","ERROR"], module_type="rx_lane"),
        CoverSpec("tx_state",    ["IDLE","SEND","FLUSH","ERROR"],   module_type="tx_lane"),
        CoverSpec("ch_state",    ["IDLE","BUSY","DRAIN","ERROR"],   module_type="mem_channel"),
        CoverSpec("stage_state", ["EMPTY","FILLING","FULL","FLUSH"],module_type="pipe_stage"),
        CoverSpec("flags",       ["ZERO","OVF","NEG","CARRY"],      module_type="alu_slice"),
        CoverSpec("overflow",    ["LO","HI"],                       module_type="mac_unit"),
    ]

    results = BinSpaceBuilder(ext.extract()).cover_specs(specs).build(ext.param_overrides)
    print(bridge_report(results))


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    demo_serdes()
    demo_mem_ctrl()
    demo_mixed()
    demo_multi_file()
    print()
