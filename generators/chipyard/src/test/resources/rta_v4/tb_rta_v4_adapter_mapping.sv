`timescale 1ns/1ps

// A synthetic raw top makes every input observable through hierarchy and
// drives a distinct value on every output. This tests only adapter wiring; the
// real RTA implementation is tested separately from RtaV4Bundle.sv.
module rta_v4_array (
    input  logic [7:0] ipin_x1y0_0,
    input  logic [7:0] ipin_x1y0_1,
    input  logic       ipin_x1y0_2,
    output logic [7:0] opin_x1y5_0,
    output logic [7:0] opin_x1y5_1,
    output logic       opin_x1y5_2,
    input  logic [7:0] ipin_x2y0_0,
    input  logic [7:0] ipin_x2y0_1,
    input  logic       ipin_x2y0_2,
    output logic [7:0] opin_x2y5_0,
    output logic [7:0] opin_x2y5_1,
    output logic       opin_x2y5_2,
    input  logic [7:0] ipin_x3y0_0,
    input  logic [7:0] ipin_x3y0_1,
    input  logic       ipin_x3y0_2,
    output logic [7:0] opin_x3y5_0,
    output logic [7:0] opin_x3y5_1,
    output logic       opin_x3y5_2,
    input  logic [7:0] ipin_x4y0_0,
    input  logic [7:0] ipin_x4y0_1,
    input  logic       ipin_x4y0_2,
    output logic [7:0] opin_x4y5_0,
    output logic [7:0] opin_x4y5_1,
    output logic       opin_x4y5_2,
    input  logic [7:0] ipin_x0y1_0,
    input  logic [7:0] ipin_x0y1_1,
    input  logic       ipin_x0y1_2,
    output logic [7:0] opin_x5y1_0,
    output logic [7:0] opin_x5y1_1,
    output logic       opin_x5y1_2,
    input  logic [7:0] ipin_x0y2_0,
    input  logic [7:0] ipin_x0y2_1,
    input  logic       ipin_x0y2_2,
    output logic [7:0] opin_x5y2_0,
    output logic [7:0] opin_x5y2_1,
    output logic       opin_x5y2_2,
    input  logic [7:0] ipin_x0y3_0,
    input  logic [7:0] ipin_x0y3_1,
    input  logic       ipin_x0y3_2,
    output logic [7:0] opin_x5y3_0,
    output logic [7:0] opin_x5y3_1,
    output logic       opin_x5y3_2,
    input  logic [7:0] ipin_x0y4_0,
    input  logic [7:0] ipin_x0y4_1,
    input  logic       ipin_x0y4_2,
    output logic [7:0] opin_x5y4_0,
    output logic [7:0] opin_x5y4_1,
    output logic       opin_x5y4_2,
    input  logic       clk_i,
    input  logic       reset_i,
    input  logic       en_i,
    output logic [3:0] n_input_active_o,
    output logic [3:0] w_input_active_o,
    output logic [3:0] s_output_active_o,
    output logic [3:0] e_output_active_o,
    input  logic       prog_clk_i,
    input  logic       prog_rst_i,
    input  logic       prog_done_i,
    input  logic       prog_we_i,
    input  logic       prog_din_i,
    output logic       prog_dout_o,
    output logic       prog_we_o
);
  assign opin_x1y5_0 = 8'h10;
  assign opin_x1y5_1 = 8'h11;
  assign opin_x1y5_2 = 1'b0;
  assign opin_x2y5_0 = 8'h20;
  assign opin_x2y5_1 = 8'h21;
  assign opin_x2y5_2 = 1'b1;
  assign opin_x3y5_0 = 8'h30;
  assign opin_x3y5_1 = 8'h31;
  assign opin_x3y5_2 = 1'b0;
  assign opin_x4y5_0 = 8'h40;
  assign opin_x4y5_1 = 8'h41;
  assign opin_x4y5_2 = 1'b1;

  assign opin_x5y1_0 = 8'h50;
  assign opin_x5y1_1 = 8'h51;
  assign opin_x5y1_2 = 1'b1;
  assign opin_x5y2_0 = 8'h60;
  assign opin_x5y2_1 = 8'h61;
  assign opin_x5y2_2 = 1'b0;
  assign opin_x5y3_0 = 8'h70;
  assign opin_x5y3_1 = 8'h71;
  assign opin_x5y3_2 = 1'b1;
  assign opin_x5y4_0 = 8'h80;
  assign opin_x5y4_1 = 8'h81;
  assign opin_x5y4_2 = 1'b0;

  assign n_input_active_o = 4'h1;
  assign w_input_active_o = 4'h2;
  assign s_output_active_o = 4'h4;
  assign e_output_active_o = 4'h8;
  assign prog_dout_o = 1'b1;
  assign prog_we_o = 1'b0;
endmodule

module tb_rta_v4_adapter_mapping;
  logic clk_i;
  logic reset_i;
  logic en_i;
  logic [31:0] west_data0_i;
  logic [31:0] west_data1_i;
  logic [3:0] west_pred_i;
  logic [31:0] north_data0_i;
  logic [31:0] north_data1_i;
  logic [3:0] north_pred_i;
  logic [31:0] east_data0_o;
  logic [31:0] east_data1_o;
  logic [3:0] east_pred_o;
  logic [31:0] south_data0_o;
  logic [31:0] south_data1_o;
  logic [3:0] south_pred_o;
  logic [3:0] n_input_active_o;
  logic [3:0] w_input_active_o;
  logic [3:0] s_output_active_o;
  logic [3:0] e_output_active_o;
  logic prog_clk_i;
  logic prog_rst_i;
  logic prog_done_i;
  logic prog_we_i;
  logic prog_din_i;
  logic prog_dout_o;
  logic prog_we_o;

  rta_v4_chipyard_adapter dut (.*);

  task automatic check_input_map;
    if (dut.array_i.ipin_x1y0_0 !== west_data0_i[7:0] ||
        dut.array_i.ipin_x2y0_0 !== west_data0_i[15:8] ||
        dut.array_i.ipin_x3y0_0 !== west_data0_i[23:16] ||
        dut.array_i.ipin_x4y0_0 !== west_data0_i[31:24] ||
        dut.array_i.ipin_x1y0_1 !== west_data1_i[7:0] ||
        dut.array_i.ipin_x2y0_1 !== west_data1_i[15:8] ||
        dut.array_i.ipin_x3y0_1 !== west_data1_i[23:16] ||
        dut.array_i.ipin_x4y0_1 !== west_data1_i[31:24] ||
        {dut.array_i.ipin_x4y0_2, dut.array_i.ipin_x3y0_2,
         dut.array_i.ipin_x2y0_2, dut.array_i.ipin_x1y0_2} !== west_pred_i)
      $fatal(1, "west input mapping mismatch");

    if (dut.array_i.ipin_x0y1_0 !== north_data0_i[7:0] ||
        dut.array_i.ipin_x0y2_0 !== north_data0_i[15:8] ||
        dut.array_i.ipin_x0y3_0 !== north_data0_i[23:16] ||
        dut.array_i.ipin_x0y4_0 !== north_data0_i[31:24] ||
        dut.array_i.ipin_x0y1_1 !== north_data1_i[7:0] ||
        dut.array_i.ipin_x0y2_1 !== north_data1_i[15:8] ||
        dut.array_i.ipin_x0y3_1 !== north_data1_i[23:16] ||
        dut.array_i.ipin_x0y4_1 !== north_data1_i[31:24] ||
        {dut.array_i.ipin_x0y4_2, dut.array_i.ipin_x0y3_2,
         dut.array_i.ipin_x0y2_2, dut.array_i.ipin_x0y1_2} !== north_pred_i)
      $fatal(1, "north input mapping mismatch");
  endtask

  task automatic check_control_map;
    if (dut.array_i.clk_i !== clk_i ||
        dut.array_i.reset_i !== reset_i ||
        dut.array_i.en_i !== en_i ||
        dut.array_i.prog_clk_i !== prog_clk_i ||
        dut.array_i.prog_rst_i !== prog_rst_i ||
        dut.array_i.prog_done_i !== prog_done_i ||
        dut.array_i.prog_we_i !== prog_we_i ||
        dut.array_i.prog_din_i !== prog_din_i)
      $fatal(1, "control or scan input mapping mismatch");
  endtask

  initial begin
    west_data0_i = 32'hd4c3_b2a1;
    west_data1_i = 32'h4433_2211;
    north_data0_i = 32'h8877_6655;
    north_data1_i = 32'hccbb_aa99;
    west_pred_i = 4'b0001;
    north_pred_i = 4'b1000;
    {clk_i, reset_i, en_i, prog_clk_i, prog_rst_i,
     prog_done_i, prog_we_i, prog_din_i} = '0;
    #1;
    check_input_map();

    for (int lane = 0; lane < 4; lane++) begin
      west_pred_i = 4'b0001 << lane;
      north_pred_i = 4'b1000 >> lane;
      #1;
      check_input_map();
    end

    for (int signal_index = 0; signal_index < 8; signal_index++) begin
      {clk_i, reset_i, en_i, prog_clk_i, prog_rst_i,
       prog_done_i, prog_we_i, prog_din_i} = 8'b1 << signal_index;
      #1;
      check_control_map();
    end

    if (east_data0_o !== 32'h4030_2010 ||
        east_data1_o !== 32'h4131_2111 ||
        east_pred_o !== 4'b1010 ||
        south_data0_o !== 32'h8070_6050 ||
        south_data1_o !== 32'h8171_6151 ||
        south_pred_o !== 4'b0101)
      $fatal(1, "packed data or predicate output mapping mismatch");

    if ({e_output_active_o, s_output_active_o,
         w_input_active_o, n_input_active_o} !== 16'h8421)
      $fatal(1, "activity-mask mapping mismatch");
    if (prog_dout_o !== 1'b1 || prog_we_o !== 1'b0)
      $fatal(1, "scan output mapping mismatch");

    $display("PASS: RTA V4 packed adapter mapping regression");
    $finish;
  end
endmodule
