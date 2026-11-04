// 8-bit combinational adder with carry in/out.
// Benchmark design for the sg13g2_stdcell baseline (issue #9): purely
// combinational, because this library has no sequential cells in scope.
module add8 (
    // Unused by the logic. Present only because `klt place-and-route` refuses
    // target_stage "route" without constraints.clock_port (friction, see flow/README.md).
    input  wire       clk,
    input  wire [7:0] a,
    input  wire [7:0] b,
    input  wire       cin,
    output wire [7:0] sum,
    output wire       cout
);
    assign {cout, sum} = a + b + cin;
endmodule
