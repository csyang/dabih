// fixture: serdes_top.sv
// Multi-lane SerDes with 4 RX lanes and 4 TX lanes.
// Both lane arrays are generate-for loops → S4 symmetry on each.

module rx_lane (
    input  logic        clk,
    input  logic        valid,
    input  logic [7:0]  data,
    output logic [1:0]  state,
    output logic        ready
);
    // stub
endmodule

module tx_lane (
    input  logic        clk,
    input  logic [7:0]  payload,
    input  logic        start,
    output logic [1:0]  tx_state,
    output logic        done
);
    // stub
endmodule

module serdes_top #(
    parameter int N_LANES = 4
) (
    input  logic              clk,
    input  logic [N_LANES-1:0] rx_valid,
    input  logic [7:0]         rx_data  [N_LANES-1:0],
    output logic [1:0]         rx_state [N_LANES-1:0],
    output logic [N_LANES-1:0] rx_ready,
    input  logic [7:0]         tx_payload [N_LANES-1:0],
    input  logic [N_LANES-1:0] tx_start,
    output logic [1:0]         tx_state   [N_LANES-1:0],
    output logic [N_LANES-1:0] tx_done
);
    // RX lane array — named block
    for (genvar i = 0; i < N_LANES; i++) begin : rx_gen
        rx_lane u_rx (
            .clk   (clk),
            .valid (rx_valid[i]),
            .data  (rx_data[i]),
            .state (rx_state[i]),
            .ready (rx_ready[i])
        );
    end

    // TX lane array — named block
    for (genvar j = 0; j < N_LANES; j++) begin : tx_gen
        tx_lane u_tx (
            .clk      (clk),
            .payload  (tx_payload[j]),
            .start    (tx_start[j]),
            .tx_state (tx_state[j]),
            .done     (tx_done[j])
        );
    end

endmodule
