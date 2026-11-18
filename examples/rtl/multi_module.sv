// fixture: multi_module.sv
// Multiple modules in one file.
// Tests that the extractor correctly attributes each generate loop
// to its enclosing parent module.

module alu_slice (
    input  logic [7:0] a, b,
    input  logic [2:0] opcode,
    output logic [7:0] result,
    output logic [1:0] flags
);
endmodule

module mac_unit (
    input  logic [7:0] x, y,
    output logic [15:0] product,
    output logic        overflow
);
endmodule

// First parent module: 4-slice ALU
module alu_top #(parameter int N_SLICES = 4) (
    input  logic [7:0] a [N_SLICES-1:0],
    input  logic [7:0] b [N_SLICES-1:0],
    input  logic [2:0] opcode [N_SLICES-1:0],
    output logic [7:0] result [N_SLICES-1:0],
    output logic [1:0] flags  [N_SLICES-1:0]
);
    for (genvar i = 0; i < N_SLICES; i++) begin : slice_gen
        alu_slice u_slice (
            .a      (a[i]),
            .b      (b[i]),
            .opcode (opcode[i]),
            .result (result[i]),
            .flags  (flags[i])
        );
    end
endmodule

// Second parent module: 8-unit MAC array
module mac_array (
    input  logic [7:0]  x [7:0],
    input  logic [7:0]  y [7:0],
    output logic [15:0] product  [7:0],
    output logic [7:0]  overflow
);
    for (genvar k = 0; k < 8; k++) begin : mac_gen
        mac_unit u_mac (
            .x        (x[k]),
            .y        (y[k]),
            .product  (product[k]),
            .overflow (overflow[k])
        );
    end
endmodule
