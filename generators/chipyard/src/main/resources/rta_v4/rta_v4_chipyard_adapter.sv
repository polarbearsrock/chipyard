// Packed, platform-neutral boundary adapter for the DORA RTA V4 array.
//
// Lane packing follows the existing RTA V4 testbench convention:
//   packed_data[8*lane +: 8]
//   packed_pred[lane]
//
// The adapter deliberately leaves configuration serialization, MMIO, DMA,
// and clock-domain policy to the surrounding SoC integration shell.

`timescale 1ns/1ps

module rta_v4_chipyard_adapter (
    input  logic        clk_i,
    input  logic        reset_i,
    input  logic        en_i,

    input  logic [31:0] west_data0_i,
    input  logic [31:0] west_data1_i,
    input  logic [3:0]  west_pred_i,
    input  logic [31:0] north_data0_i,
    input  logic [31:0] north_data1_i,
    input  logic [3:0]  north_pred_i,

    output logic [31:0] east_data0_o,
    output logic [31:0] east_data1_o,
    output logic [3:0]  east_pred_o,
    output logic [31:0] south_data0_o,
    output logic [31:0] south_data1_o,
    output logic [3:0]  south_pred_o,

    output logic [3:0]  n_input_active_o,
    output logic [3:0]  w_input_active_o,
    output logic [3:0]  s_output_active_o,
    output logic [3:0]  e_output_active_o,

    input  logic        prog_clk_i,
    input  logic        prog_rst_i,
    input  logic        prog_done_i,
    input  logic        prog_we_i,
    input  logic        prog_din_i,
    output logic        prog_dout_o,
    output logic        prog_we_o
);

  rta_v4_array array_i (
      // West boundary: lane r maps to ipin_x(r+1)y0.
      .ipin_x1y0_0 (west_data0_i[7:0]),
      .ipin_x1y0_1 (west_data1_i[7:0]),
      .ipin_x1y0_2 (west_pred_i[0]),
      .ipin_x2y0_0 (west_data0_i[15:8]),
      .ipin_x2y0_1 (west_data1_i[15:8]),
      .ipin_x2y0_2 (west_pred_i[1]),
      .ipin_x3y0_0 (west_data0_i[23:16]),
      .ipin_x3y0_1 (west_data1_i[23:16]),
      .ipin_x3y0_2 (west_pred_i[2]),
      .ipin_x4y0_0 (west_data0_i[31:24]),
      .ipin_x4y0_1 (west_data1_i[31:24]),
      .ipin_x4y0_2 (west_pred_i[3]),

      // North boundary: lane c maps to ipin_x0y(c+1).
      .ipin_x0y1_0 (north_data0_i[7:0]),
      .ipin_x0y1_1 (north_data1_i[7:0]),
      .ipin_x0y1_2 (north_pred_i[0]),
      .ipin_x0y2_0 (north_data0_i[15:8]),
      .ipin_x0y2_1 (north_data1_i[15:8]),
      .ipin_x0y2_2 (north_pred_i[1]),
      .ipin_x0y3_0 (north_data0_i[23:16]),
      .ipin_x0y3_1 (north_data1_i[23:16]),
      .ipin_x0y3_2 (north_pred_i[2]),
      .ipin_x0y4_0 (north_data0_i[31:24]),
      .ipin_x0y4_1 (north_data1_i[31:24]),
      .ipin_x0y4_2 (north_pred_i[3]),

      // East boundary: lane r maps to opin_x(r+1)y5.
      .opin_x1y5_0 (east_data0_o[7:0]),
      .opin_x1y5_1 (east_data1_o[7:0]),
      .opin_x1y5_2 (east_pred_o[0]),
      .opin_x2y5_0 (east_data0_o[15:8]),
      .opin_x2y5_1 (east_data1_o[15:8]),
      .opin_x2y5_2 (east_pred_o[1]),
      .opin_x3y5_0 (east_data0_o[23:16]),
      .opin_x3y5_1 (east_data1_o[23:16]),
      .opin_x3y5_2 (east_pred_o[2]),
      .opin_x4y5_0 (east_data0_o[31:24]),
      .opin_x4y5_1 (east_data1_o[31:24]),
      .opin_x4y5_2 (east_pred_o[3]),

      // South boundary: lane c maps to opin_x5y(c+1).
      .opin_x5y1_0 (south_data0_o[7:0]),
      .opin_x5y1_1 (south_data1_o[7:0]),
      .opin_x5y1_2 (south_pred_o[0]),
      .opin_x5y2_0 (south_data0_o[15:8]),
      .opin_x5y2_1 (south_data1_o[15:8]),
      .opin_x5y2_2 (south_pred_o[1]),
      .opin_x5y3_0 (south_data0_o[23:16]),
      .opin_x5y3_1 (south_data1_o[23:16]),
      .opin_x5y3_2 (south_pred_o[2]),
      .opin_x5y4_0 (south_data0_o[31:24]),
      .opin_x5y4_1 (south_data1_o[31:24]),
      .opin_x5y4_2 (south_pred_o[3]),

      .clk_i             (clk_i),
      .reset_i           (reset_i),
      .en_i              (en_i),
      .n_input_active_o  (n_input_active_o),
      .w_input_active_o  (w_input_active_o),
      .s_output_active_o (s_output_active_o),
      .e_output_active_o (e_output_active_o),
      .prog_clk_i        (prog_clk_i),
      .prog_rst_i        (prog_rst_i),
      .prog_done_i       (prog_done_i),
      .prog_we_i         (prog_we_i),
      .prog_din_i        (prog_din_i),
      .prog_dout_o       (prog_dout_o),
      .prog_we_o         (prog_we_o)
  );

endmodule
