`timescale 1ns/1ps

module tb_rta_v4_chipyard_adapter;

  localparam int BITSTREAM_BITS = 3140;
  localparam int BITSTREAM_BYTES = (BITSTREAM_BITS + 7) / 8;
  localparam int VALID_BITS_LAST_BYTE = BITSTREAM_BITS % 8;
  localparam int TAIL_TIMEOUT_CYCLES = BITSTREAM_BITS / 4;
  localparam int EXPECTED_FIRST_PROG_WE_O_HIGH_BIT = 66;
  localparam int EXPECTED_TAIL_CYCLES = 65;
  localparam int CHAIN_LATENCY = 13;
  localparam int STREAM_LENGTH = 32;

  logic clk_i = 1'b0;
  logic prog_clk_i = 1'b0;
  logic reset_i;
  logic en_i;

  logic [31:0] west_data0_i;
  logic [31:0] west_data1_i;
  logic [3:0]  west_pred_i;
  logic [31:0] north_data0_i;
  logic [31:0] north_data1_i;
  logic [3:0]  north_pred_i;

  logic [31:0] east_data0_o;
  logic [31:0] east_data1_o;
  logic [3:0]  east_pred_o;
  logic [31:0] south_data0_o;
  logic [31:0] south_data1_o;
  logic [3:0]  south_pred_o;

  logic [3:0] n_input_active_o;
  logic [3:0] w_input_active_o;
  logic [3:0] s_output_active_o;
  logic [3:0] e_output_active_o;

  logic prog_rst_i;
  logic prog_done_i;
  logic prog_we_i;
  logic prog_din_i;
  logic prog_dout_o;
  logic prog_we_o;

  logic [7:0] stream [0:STREAM_LENGTH-1];
  string bitstream_path;

  always #5 clk_i = ~clk_i;
  always #3 prog_clk_i = ~prog_clk_i;

  rta_v4_chipyard_adapter dut (
      .clk_i,
      .reset_i,
      .en_i,
      .west_data0_i,
      .west_data1_i,
      .west_pred_i,
      .north_data0_i,
      .north_data1_i,
      .north_pred_i,
      .east_data0_o,
      .east_data1_o,
      .east_pred_o,
      .south_data0_o,
      .south_data1_o,
      .south_pred_o,
      .n_input_active_o,
      .w_input_active_o,
      .s_output_active_o,
      .e_output_active_o,
      .prog_clk_i,
      .prog_rst_i,
      .prog_done_i,
      .prog_we_i,
      .prog_din_i,
      .prog_dout_o,
      .prog_we_o
  );

  task automatic drive_boundary_zero;
    west_data0_i  = '0;
    west_data1_i  = '0;
    west_pred_i   = '0;
    north_data0_i = '0;
    north_data1_i = '0;
    north_pred_i  = '0;
  endtask

  task automatic reset_all;
    reset_i     = 1'b1;
    en_i        = 1'b0;
    prog_rst_i  = 1'b1;
    prog_done_i = 1'b0;
    prog_we_i   = 1'b0;
    prog_din_i  = 1'b0;
    drive_boundary_zero();

    repeat (4) @(posedge prog_clk_i);
    @(negedge prog_clk_i);
    prog_rst_i = 1'b0;
    repeat (4) @(posedge prog_clk_i);
    repeat (4) @(posedge clk_i);
    @(negedge clk_i);
    reset_i = 1'b0;
    repeat (2) @(posedge clk_i);
  endtask

  task automatic reset_compute;
    @(negedge clk_i);
    reset_i = 1'b1;
    en_i = 1'b0;
    drive_boundary_zero();
    repeat (4) @(posedge clk_i);
    @(negedge clk_i);
    reset_i = 1'b0;
    repeat (2) @(posedge clk_i);
  endtask

  task automatic program_bitstream;
    int fd;
    int byte_value;
    int extra_byte;
    int shifted_bits;
    int tail_cycles;
    int first_prog_we_o_high_bit;
    logic [7:0] byte_bits;
    logic saw_prog_we_o_high;

    shifted_bits = 0;
    tail_cycles = 0;
    first_prog_we_o_high_bit = -1;
    saw_prog_we_o_high = 1'b0;
    en_i = 1'b0;
    prog_done_i = 1'b0;
    prog_we_i = 1'b0;
    prog_din_i = 1'b0;
    drive_boundary_zero();
    repeat (4) @(posedge prog_clk_i);

    fd = $fopen(bitstream_path, "rb");
    if (fd == 0)
      $fatal(1, "could not open bitstream: %s", bitstream_path);

    for (int byte_index = 0; byte_index < BITSTREAM_BYTES; byte_index++) begin
      byte_value = $fgetc(fd);
      if (byte_value < 0)
        $fatal(1, "bitstream ended at byte %0d of %0d",
               byte_index, BITSTREAM_BYTES);
      byte_bits = byte_value[7:0];
      if ((byte_index == BITSTREAM_BYTES - 1) &&
          (VALID_BITS_LAST_BYTE != 0) &&
          ((byte_bits >> VALID_BITS_LAST_BYTE) != 0))
        $fatal(1, "unused high bits of final bitstream byte are nonzero");

      for (int bit_index = 0; bit_index < 8; bit_index++) begin
        if (shifted_bits < BITSTREAM_BITS) begin
          @(negedge prog_clk_i);
          prog_we_i = 1'b1;
          prog_din_i = byte_bits[bit_index];
          @(posedge prog_clk_i);
          #1;
          if ($isunknown(prog_we_o))
            $fatal(1, "prog_we_o is X/Z while loading bit %0d", shifted_bits);
          if (prog_we_o === 1'b1) begin
            if (first_prog_we_o_high_bit < 0)
              first_prog_we_o_high_bit = shifted_bits + 1;
            saw_prog_we_o_high = 1'b1;
          end else if (first_prog_we_o_high_bit >= 0) begin
            $fatal(1, "prog_we_o deasserted while prog_we_i remained high");
          end
          shifted_bits++;
        end
      end
    end

    extra_byte = $fgetc(fd);
    if (extra_byte >= 0)
      $fatal(1, "bitstream contains more than %0d bytes", BITSTREAM_BYTES);
    $fclose(fd);

    @(negedge prog_clk_i);
    prog_we_i = 1'b0;
    prog_din_i = 1'b0;
    @(posedge prog_clk_i);
    #1;
    if ($isunknown(prog_we_o))
      $fatal(1, "prog_we_o is X/Z while draining scan tail");
    while (prog_we_o !== 1'b0) begin
      saw_prog_we_o_high = 1'b1;
      tail_cycles++;
      if (tail_cycles > TAIL_TIMEOUT_CYCLES)
        $fatal(1, "scan tail failed to drain; prog_we_o=%b", prog_we_o);
      @(posedge prog_clk_i);
      #1;
      if ($isunknown(prog_we_o))
        $fatal(1, "prog_we_o is X/Z while draining scan tail");
    end

    if (shifted_bits != BITSTREAM_BITS)
      $fatal(1, "shifted %0d bits, expected %0d", shifted_bits,
             BITSTREAM_BITS);
    if ($isunknown(prog_dout_o) || $isunknown(prog_we_o))
      $fatal(1, "scan outputs contain X/Z after configuration");
    if (!saw_prog_we_o_high)
      $fatal(1, "scan-tail write enable never asserted");
    if (first_prog_we_o_high_bit != EXPECTED_FIRST_PROG_WE_O_HIGH_BIT)
      $fatal(1, "prog_we_o first asserted at bit %0d, expected bit %0d",
             first_prog_we_o_high_bit, EXPECTED_FIRST_PROG_WE_O_HIGH_BIT);
    if (tail_cycles != EXPECTED_TAIL_CYCLES)
      $fatal(1, "scan tail drained in %0d cycles, expected %0d",
             tail_cycles, EXPECTED_TAIL_CYCLES);

    repeat (4) begin
      @(posedge prog_clk_i);
      #1;
      if (prog_we_o !== 1'b0)
        $fatal(1, "prog_we_o did not remain low after scan-tail drain");
    end

    @(negedge prog_clk_i);
    prog_done_i = 1'b1;
    repeat (6) @(posedge prog_clk_i);
    #1;

    if ({n_input_active_o, w_input_active_o,
         s_output_active_o, e_output_active_o} !== 16'hffff)
      $fatal(1, "unexpected activity masks n=%h w=%h s=%h e=%h",
             n_input_active_o, w_input_active_o,
             s_output_active_o, e_output_active_o);
  endtask

  task automatic fill_stream;
    logic [31:0] lfsr;
    lfsr = 32'hf00d_cafe;
    for (int index = 0; index < STREAM_LENGTH; index++) begin
      case (index)
        0: stream[index] = 8'h00;
        1: stream[index] = 8'h7f;
        2: stream[index] = 8'h80;
        3: stream[index] = 8'hff;
        default: begin
          lfsr = {lfsr[30:0], lfsr[31] ^ lfsr[21] ^ lfsr[1] ^ lfsr[0]};
          stream[index] = lfsr[7:0] ^ index[7:0];
        end
      endcase
    end
  endtask

  task automatic check_output(input string mode, input int enabled_cycle);
    logic [7:0] expected;
    expected = stream[enabled_cycle - CHAIN_LATENCY] + 8'd10;
    if ($isunknown(east_data0_o[7:0]))
      $fatal(1, "%s cycle %0d produced X/Z", mode, enabled_cycle);
    if (east_data0_o[7:0] !== expected)
      $fatal(1, "%s cycle %0d got 0x%02h, expected 0x%02h",
             mode, enabled_cycle, east_data0_o[7:0], expected);
  endtask

  function automatic logic [135:0] packed_outputs;
    packed_outputs = {
      east_data0_o, east_data1_o, east_pred_o,
      south_data0_o, south_data1_o, south_pred_o
    };
  endfunction

  task automatic run_continuous;
    reset_compute();
    @(negedge clk_i);
    en_i = 1'b1;
    for (int cycle = 0; cycle < STREAM_LENGTH + CHAIN_LATENCY; cycle++) begin
      west_data0_i[7:0] =
          (cycle < STREAM_LENGTH) ? stream[cycle] : 8'h00;
      @(posedge clk_i);
      #1;
      if (cycle >= CHAIN_LATENCY)
        check_output("continuous", cycle);
      @(negedge clk_i);
    end
    en_i = 1'b0;
    drive_boundary_zero();
  endtask

  task automatic run_stalled;
    logic [135:0] output_snapshot;
    reset_compute();
    @(negedge clk_i);
    en_i = 1'b0;
    for (int cycle = 0; cycle < STREAM_LENGTH + CHAIN_LATENCY; cycle++) begin
      for (int stall = 0; stall < (cycle % 4); stall++) begin
        output_snapshot = packed_outputs();
        en_i = 1'b0;
        west_data0_i[7:0] = 8'ha5 ^ stall[7:0] ^ cycle[7:0];
        @(posedge clk_i);
        #1;
        if (packed_outputs() !== output_snapshot)
          $fatal(1, "outputs changed while en_i=0 at cycle %0d stall %0d",
                 cycle, stall);
        @(negedge clk_i);
      end

      west_data0_i[7:0] =
          (cycle < STREAM_LENGTH) ? stream[cycle] : 8'h00;
      en_i = 1'b1;
      @(posedge clk_i);
      #1;
      if (cycle >= CHAIN_LATENCY)
        check_output("stalled", cycle);
      @(negedge clk_i);
      en_i = 1'b0;
    end
    drive_boundary_zero();
  endtask

  initial begin
    if (!$value$plusargs("BITSTREAM=%s", bitstream_path))
      $fatal(1, "BITSTREAM plusarg is required");

    fill_stream();
    reset_all();
    program_bitstream();
    run_continuous();
    run_stalled();

    $display("PASS: RTA V4 bundle add-chain adapter regression");
    $finish;
  end

  initial begin
    #1_000_000;
    $fatal(1, "RTA V4 bundle regression timed out");
  end

endmodule
