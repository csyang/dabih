// fixture: mixed_top.sv
// Contains both replicated (generate) and non-replicated instantiations.
// The non-replicated ctrl and arbiter should NOT appear in Dabih output.

module pipe_stage (
    input  logic       clk,
    input  logic [3:0] opcode,
    output logic [1:0] stage_state
);
    // stub
endmodule

module global_ctrl (
    input  logic clk,
    output logic ready
);
    // stub — unique, not symmetric
endmodule

module arbiter (
    input  logic [3:0] req,
    output logic [1:0] grant
);
    // stub — unique
endmodule

module mixed_top #(parameter int N_STAGES = 6) (
    input  logic       clk,
    input  logic [3:0] opcode [N_STAGES-1:0],
    output logic [1:0] stage_state [N_STAGES-1:0],
    output logic       ctrl_ready,
    output logic [1:0] grant
);
    // Replicated pipeline stages — should be detected
    for (genvar i = 0; i < N_STAGES; i++) begin : pipe_gen
        pipe_stage u_stage (
            .clk        (clk),
            .opcode     (opcode[i]),
            .stage_state(stage_state[i])
        );
    end

    // Non-replicated — should NOT be detected
    global_ctrl u_ctrl (.clk(clk), .ready(ctrl_ready));
    arbiter     u_arb  (.req(4'b0), .grant(grant));

endmodule
