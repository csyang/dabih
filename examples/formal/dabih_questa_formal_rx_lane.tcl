# ══════════════════════════════════════════════════════════════════════
# Dabih — Questa Formal Symmetry Verification Script
# Generated: 2026-11-17 11:31
# Tool: mentor/questa-formal/2024.3_1 (or later)
# DUT: serdes_top
# Proof depth: 20 cycles
# Timeout: 3600s
# ══════════════════════════════════════════════════════════════════════

# ── Step 1: Compile ─────────────────────────────────────────────────
questa_formal compile \
    -work dabih_sym_rx_lane \
    -sv \
    -f64 \
    dabih_sym_rx_lane.sv \
    "examples/rtl/serdes_top.sv"

# ── Step 2: Elaborate ───────────────────────────────────────────────
questa_formal elaborate \
    -work dabih_sym_rx_lane \
    -top serdes_top

# ── Step 3: Verify ──────────────────────────────────────────────────
# Uses k-induction (default engine).  Each assertion is proven or
# returns a counterexample showing which instance pair is asymmetric.
questa_formal verify \
    -work dabih_sym_rx_lane \
    -timeout 3600 \
    -init dabih_dabih_sym_rx_lane.fvinit \
    -prove_depth 20 \
    -property { \
        SYM_D0_instance_inst0_vs_inst1_state \
        SYM_D0_instance_inst0_vs_inst1_ready \
        SYM_D0_instance_inst1_vs_inst2_state \
        SYM_D0_instance_inst1_vs_inst2_ready \
        SYM_D0_instance_inst2_vs_inst3_state \
        SYM_D0_instance_inst2_vs_inst3_ready \
        SYM_D0_instance_inst3_vs_inst0_state \
        SYM_D0_instance_inst3_vs_inst0_ready \
    }

# ── Step 4: Report ──────────────────────────────────────────────────
questa_formal report -property -file dabih_dabih_sym_rx_lane_results.txt

# ── Expected results ────────────────────────────────────────────────
# PROVEN   for all SYM_* properties → symmetry is formally verified
# FALSIFIED → counterexample shows which instance pair is asymmetric
#            (check waveform: the falsifying trace shows where the
#             two instances diverge under identical stimulus)

# Total assertions: 8
#   SYM_D0_instance_inst0_vs_inst1_state
#   SYM_D0_instance_inst0_vs_inst1_ready
#   SYM_D0_instance_inst1_vs_inst2_state
#   SYM_D0_instance_inst1_vs_inst2_ready
#   SYM_D0_instance_inst2_vs_inst3_state
#   SYM_D0_instance_inst2_vs_inst3_ready
#   SYM_D0_instance_inst3_vs_inst0_state
#   SYM_D0_instance_inst3_vs_inst0_ready