// fixture: mem_ctrl.sv
// 8-channel memory controller with literal-bound generate loop.
// Tests that literal bounds (i < 8) resolve without parameter lookup.

module mem_channel (
    input  logic        clk,
    input  logic        req,
    input  logic [31:0] addr,
    input  logic [63:0] wdata,
    output logic [63:0] rdata,
    output logic [2:0]  ch_state,
    output logic        ack
);
    // stub
endmodule

module mem_ctrl (
    input  logic        clk,
    input  logic [7:0]  req,
    input  logic [31:0] addr   [7:0],
    input  logic [63:0] wdata  [7:0],
    output logic [63:0] rdata  [7:0],
    output logic [2:0]  ch_state [7:0],
    output logic [7:0]  ack
);
    // Literal bound — 8 channels, no parameter
    for (genvar i = 0; i < 8; i++) begin : ch_gen
        mem_channel u_ch (
            .clk     (clk),
            .req     (req[i]),
            .addr    (addr[i]),
            .wdata   (wdata[i]),
            .rdata   (rdata[i]),
            .ch_state(ch_state[i]),
            .ack     (ack[i])
        );
    end

endmodule
