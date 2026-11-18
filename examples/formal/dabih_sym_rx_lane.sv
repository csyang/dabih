// ══════════════════════════════════════════════════════════════════════
// Dabih — Formal Symmetry Property Wrapper
// Generated: 2026-11-17 11:31
// Tool target: Questa Formal (questa-formal/2024.3_1+)
// DUT: serdes_top
// Instance pattern: rx_gen[{i}].u_rx
// Proof depth: 20 cycles
// ══════════════════════════════════════════════════════════════════════

// SVA bind-point: this module may be used standalone or via `bind`.
// See dabih_questa_formal.tcl for the complete compile + verify flow.

module dabih_sym_check_rx_lane (
        input  logic clk,
        input  logic [3:0] valid_per_inst [0:3],
        input  logic [3:0] data_per_inst [0:3],
        output logic [3:0] state_per_inst [0:3],
        output logic [3:0] ready_per_inst [0:3]
);

    // ── DUT instantiation ────────────────────────────────────────────
    serdes_top #(.N_LANES(4)) u_dut (
        .clk (clk),
        // Connect remaining ports via .* or explicit mapping
        .*
    );

    // ── Symmetry assertions ──────────────────────────────────────────
    // Declaration 0: instance, group=S4
    // Instances: [0, 1, 2, 3]
    // Checking 4 generator-implied pair(s)

    // ── Pair (0, 1) ─────────────────────────────────
    // Assumption: instances 0 and 1 receive identical stimulus
    property p_ASM_D0_instance_inst0_vs_inst1_valid;
        @(posedge clk) 
        (u_dut.rx_gen[0].u_rx.valid === u_dut.rx_gen[1].u_rx.valid);
    endproperty
    ASM_D0_instance_inst0_vs_inst1_valid: assume property (p_ASM_D0_instance_inst0_vs_inst1_valid);

    property p_ASM_D0_instance_inst0_vs_inst1_data;
        @(posedge clk) 
        (u_dut.rx_gen[0].u_rx.data === u_dut.rx_gen[1].u_rx.data);
    endproperty
    ASM_D0_instance_inst0_vs_inst1_data: assume property (p_ASM_D0_instance_inst0_vs_inst1_data);

    // Assertion: identical inputs → identical outputs within 20 cycles
    property p_D0_instance_inst0_vs_inst1_state;
        @(posedge clk) 
        ((u_dut.rx_gen[0].u_rx.valid === u_dut.rx_gen[1].u_rx.valid) && (u_dut.rx_gen[0].u_rx.data === u_dut.rx_gen[1].u_rx.data))
        |-> ##[0:20] (u_dut.rx_gen[0].u_rx.state === u_dut.rx_gen[1].u_rx.state);
    endproperty
    SYM_D0_instance_inst0_vs_inst1_state: assert property (p_D0_instance_inst0_vs_inst1_state)
        else $error("Dabih symmetry violation: serdes_top.rx_gen[0].u_rx.state != rx_gen[1].u_rx.state");

    property p_D0_instance_inst0_vs_inst1_ready;
        @(posedge clk) 
        ((u_dut.rx_gen[0].u_rx.valid === u_dut.rx_gen[1].u_rx.valid) && (u_dut.rx_gen[0].u_rx.data === u_dut.rx_gen[1].u_rx.data))
        |-> ##[0:20] (u_dut.rx_gen[0].u_rx.ready === u_dut.rx_gen[1].u_rx.ready);
    endproperty
    SYM_D0_instance_inst0_vs_inst1_ready: assert property (p_D0_instance_inst0_vs_inst1_ready)
        else $error("Dabih symmetry violation: serdes_top.rx_gen[0].u_rx.ready != rx_gen[1].u_rx.ready");

    // ── Pair (1, 2) ─────────────────────────────────
    // Assumption: instances 1 and 2 receive identical stimulus
    property p_ASM_D0_instance_inst1_vs_inst2_valid;
        @(posedge clk) 
        (u_dut.rx_gen[1].u_rx.valid === u_dut.rx_gen[2].u_rx.valid);
    endproperty
    ASM_D0_instance_inst1_vs_inst2_valid: assume property (p_ASM_D0_instance_inst1_vs_inst2_valid);

    property p_ASM_D0_instance_inst1_vs_inst2_data;
        @(posedge clk) 
        (u_dut.rx_gen[1].u_rx.data === u_dut.rx_gen[2].u_rx.data);
    endproperty
    ASM_D0_instance_inst1_vs_inst2_data: assume property (p_ASM_D0_instance_inst1_vs_inst2_data);

    // Assertion: identical inputs → identical outputs within 20 cycles
    property p_D0_instance_inst1_vs_inst2_state;
        @(posedge clk) 
        ((u_dut.rx_gen[1].u_rx.valid === u_dut.rx_gen[2].u_rx.valid) && (u_dut.rx_gen[1].u_rx.data === u_dut.rx_gen[2].u_rx.data))
        |-> ##[0:20] (u_dut.rx_gen[1].u_rx.state === u_dut.rx_gen[2].u_rx.state);
    endproperty
    SYM_D0_instance_inst1_vs_inst2_state: assert property (p_D0_instance_inst1_vs_inst2_state)
        else $error("Dabih symmetry violation: serdes_top.rx_gen[1].u_rx.state != rx_gen[2].u_rx.state");

    property p_D0_instance_inst1_vs_inst2_ready;
        @(posedge clk) 
        ((u_dut.rx_gen[1].u_rx.valid === u_dut.rx_gen[2].u_rx.valid) && (u_dut.rx_gen[1].u_rx.data === u_dut.rx_gen[2].u_rx.data))
        |-> ##[0:20] (u_dut.rx_gen[1].u_rx.ready === u_dut.rx_gen[2].u_rx.ready);
    endproperty
    SYM_D0_instance_inst1_vs_inst2_ready: assert property (p_D0_instance_inst1_vs_inst2_ready)
        else $error("Dabih symmetry violation: serdes_top.rx_gen[1].u_rx.ready != rx_gen[2].u_rx.ready");

    // ── Pair (2, 3) ─────────────────────────────────
    // Assumption: instances 2 and 3 receive identical stimulus
    property p_ASM_D0_instance_inst2_vs_inst3_valid;
        @(posedge clk) 
        (u_dut.rx_gen[2].u_rx.valid === u_dut.rx_gen[3].u_rx.valid);
    endproperty
    ASM_D0_instance_inst2_vs_inst3_valid: assume property (p_ASM_D0_instance_inst2_vs_inst3_valid);

    property p_ASM_D0_instance_inst2_vs_inst3_data;
        @(posedge clk) 
        (u_dut.rx_gen[2].u_rx.data === u_dut.rx_gen[3].u_rx.data);
    endproperty
    ASM_D0_instance_inst2_vs_inst3_data: assume property (p_ASM_D0_instance_inst2_vs_inst3_data);

    // Assertion: identical inputs → identical outputs within 20 cycles
    property p_D0_instance_inst2_vs_inst3_state;
        @(posedge clk) 
        ((u_dut.rx_gen[2].u_rx.valid === u_dut.rx_gen[3].u_rx.valid) && (u_dut.rx_gen[2].u_rx.data === u_dut.rx_gen[3].u_rx.data))
        |-> ##[0:20] (u_dut.rx_gen[2].u_rx.state === u_dut.rx_gen[3].u_rx.state);
    endproperty
    SYM_D0_instance_inst2_vs_inst3_state: assert property (p_D0_instance_inst2_vs_inst3_state)
        else $error("Dabih symmetry violation: serdes_top.rx_gen[2].u_rx.state != rx_gen[3].u_rx.state");

    property p_D0_instance_inst2_vs_inst3_ready;
        @(posedge clk) 
        ((u_dut.rx_gen[2].u_rx.valid === u_dut.rx_gen[3].u_rx.valid) && (u_dut.rx_gen[2].u_rx.data === u_dut.rx_gen[3].u_rx.data))
        |-> ##[0:20] (u_dut.rx_gen[2].u_rx.ready === u_dut.rx_gen[3].u_rx.ready);
    endproperty
    SYM_D0_instance_inst2_vs_inst3_ready: assert property (p_D0_instance_inst2_vs_inst3_ready)
        else $error("Dabih symmetry violation: serdes_top.rx_gen[2].u_rx.ready != rx_gen[3].u_rx.ready");

    // ── Pair (3, 0) ─────────────────────────────────
    // Assumption: instances 3 and 0 receive identical stimulus
    property p_ASM_D0_instance_inst3_vs_inst0_valid;
        @(posedge clk) 
        (u_dut.rx_gen[3].u_rx.valid === u_dut.rx_gen[0].u_rx.valid);
    endproperty
    ASM_D0_instance_inst3_vs_inst0_valid: assume property (p_ASM_D0_instance_inst3_vs_inst0_valid);

    property p_ASM_D0_instance_inst3_vs_inst0_data;
        @(posedge clk) 
        (u_dut.rx_gen[3].u_rx.data === u_dut.rx_gen[0].u_rx.data);
    endproperty
    ASM_D0_instance_inst3_vs_inst0_data: assume property (p_ASM_D0_instance_inst3_vs_inst0_data);

    // Assertion: identical inputs → identical outputs within 20 cycles
    property p_D0_instance_inst3_vs_inst0_state;
        @(posedge clk) 
        ((u_dut.rx_gen[3].u_rx.valid === u_dut.rx_gen[0].u_rx.valid) && (u_dut.rx_gen[3].u_rx.data === u_dut.rx_gen[0].u_rx.data))
        |-> ##[0:20] (u_dut.rx_gen[3].u_rx.state === u_dut.rx_gen[0].u_rx.state);
    endproperty
    SYM_D0_instance_inst3_vs_inst0_state: assert property (p_D0_instance_inst3_vs_inst0_state)
        else $error("Dabih symmetry violation: serdes_top.rx_gen[3].u_rx.state != rx_gen[0].u_rx.state");

    property p_D0_instance_inst3_vs_inst0_ready;
        @(posedge clk) 
        ((u_dut.rx_gen[3].u_rx.valid === u_dut.rx_gen[0].u_rx.valid) && (u_dut.rx_gen[3].u_rx.data === u_dut.rx_gen[0].u_rx.data))
        |-> ##[0:20] (u_dut.rx_gen[3].u_rx.ready === u_dut.rx_gen[0].u_rx.ready);
    endproperty
    SYM_D0_instance_inst3_vs_inst0_ready: assert property (p_D0_instance_inst3_vs_inst0_ready)
        else $error("Dabih symmetry violation: serdes_top.rx_gen[3].u_rx.ready != rx_gen[0].u_rx.ready");

endmodule
