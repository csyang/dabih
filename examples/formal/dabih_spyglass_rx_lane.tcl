# ══════════════════════════════════════════════════════════════════════
# Dabih — SpyGlass / VC SpyGlass Structural Pre-Check Script (Tier 1)
# Generated: 2026-11-17 11:31
# ──────────────────────────────────────────────────────────────────────
# Invocation (choose one):
#   vc_spyglass -tcl dabih_sym_rx_lane_spyglass.tcl   (vc_spyglass/2024.09-SP2)
#   spyglass    -tcl dabih_sym_rx_lane_spyglass.tcl   (spyglass legacy)
# ══════════════════════════════════════════════════════════════════════

# ── Project setup ────────────────────────────────────────────────────
new_project dabih_sym_rx_lane
set_option top serdes_top
set_option language sysv
set_option enableSV yes
set_option enableSV09 yes

# ── RTL sources ──────────────────────────────────────────────────────
read_file -type sverilog {examples/rtl/serdes_top.sv}

# ── Design constraints ───────────────────────────────────────────────
read_file -type sgdc {dabih_spyglass_rx_lane.sgdc}

# ── Goal: structural symmetry pre-check ──────────────────────────────
# Runs the structural analysis rules without full formal proof.
# Typically completes in 2–10 minutes.
set_goal lint_rtl
set_option enableDRC yes

# ── Run ─────────────────────────────────────────────────────────────
run_goal

# ── Report ───────────────────────────────────────────────────────────
write_report -type violation   -file dabih_dabih_sym_rx_lane_violations.txt
write_report -type waiver      -file dabih_dabih_sym_rx_lane_waivers.txt
write_report -type summary     -file dabih_dabih_sym_rx_lane_summary.txt

# ── Expected outcomes ────────────────────────────────────────────────
# PASS  → No violations on dabih_sym_* annotated signals.
#         Proceed to Questa Formal (Tier 2) for behavioral proof.
# FAIL  → Structural asymmetry detected.  Violations indicate which
#         signal or instance deviates from the expected symmetry.
#         Fix the RTL or revise the symmetry declaration before
#         running Questa Formal.

# Symmetry declarations checked: 1
# DUT: serdes_top  Instance pattern: rx_gen[{i}].u_rx