package chipyard.rta_v4

import chisel3._
import chisel3.util._

import freechips.rocketchip.diplomacy._
import freechips.rocketchip.prci._
import freechips.rocketchip.regmapper.{RegField, RegFieldDesc, RegisterRouter, RegisterRouterParams}
import freechips.rocketchip.subsystem.PBUS
import freechips.rocketchip.tilelink._
import org.chipsalliance.cde.config.{Config, Field, Parameters}
import testchipip.soc.{SubsystemInjector, SubsystemInjectorKey}

/** Parameters for the frozen RTA V4 reference peripheral.
  *
  * This shell intentionally uses the peripheral-bus clock for both the
  * compute and programming domains. A future high-throughput integration can
  * split those domains behind explicit clock crossings without changing the
  * frozen SystemVerilog boundary adapter.
  */
case class RtaV4Params(address: BigInt = 0x10050000L) {
  require((address & 0xfff) == 0, "RTA V4 address must be 4 KiB aligned")
}

case object RtaV4Key extends Field[Option[RtaV4Params]](None)

object RtaV4Artifact {
  val ScanBits = 3140
  val Rows = 4
  val Columns = 4
  val DataWidth = 8
  val DataPlanes = 2
  val PredicateWidth = 1
  val LayoutHashWords: Seq[BigInt] = Seq(
    "36c02b05", "3e368648", "4ccd7b84", "33bd5fac",
    "fc295734", "667b01ac", "7a4ba926", "8a0b9e7a").map(BigInt(_, 16))
}

object RtaV4Registers {
  val DeviceId       = 0x000
  val AbiVersion     = 0x008
  val Capabilities   = 0x010
  val BitstreamBits  = 0x018
  val LayoutHashBase = 0x020
  val Scratch        = 0x060

  val ConfigCommand  = 0x080
  val ConfigStatus   = 0x088
  val ConfigData     = 0x090
  val ConfigBitsIn   = 0x098
  val ConfigBitsOut  = 0x0a0
  val ConfigError    = 0x0a8

  val ComputeControl = 0x0c0
  val ComputeStatus  = 0x0c8
  val SnapshotSeq    = 0x0d0
  val ComputeError   = 0x0d8

  val WestInputBase  = 0x100
  val NorthInputBase = 0x120
  val EastOutputBase = 0x140
  val SouthOutputBase = 0x160
  val Activity       = 0x180

  val IdValue: BigInt = 0x52544134L // ASCII "RTA4"
  val AbiVersionValue: BigInt = 0x00010001L
  val CapabilitiesValue: BigInt =
    (RtaV4Artifact.Rows) |
    (RtaV4Artifact.Columns << 8) |
    (RtaV4Artifact.DataWidth << 16) |
    (RtaV4Artifact.DataPlanes << 24) |
    (RtaV4Artifact.PredicateWidth << 28)
}

/** Chisel description of the packed, platform-neutral SystemVerilog port. */
class RtaV4BlackBoxIO extends Bundle {
  val clk_i = Input(Clock())
  val reset_i = Input(Bool())
  val en_i = Input(Bool())

  val west_data0_i = Input(UInt(32.W))
  val west_data1_i = Input(UInt(32.W))
  val west_pred_i = Input(UInt(4.W))
  val north_data0_i = Input(UInt(32.W))
  val north_data1_i = Input(UInt(32.W))
  val north_pred_i = Input(UInt(4.W))

  val east_data0_o = Output(UInt(32.W))
  val east_data1_o = Output(UInt(32.W))
  val east_pred_o = Output(UInt(4.W))
  val south_data0_o = Output(UInt(32.W))
  val south_data1_o = Output(UInt(32.W))
  val south_pred_o = Output(UInt(4.W))

  val n_input_active_o = Output(UInt(4.W))
  val w_input_active_o = Output(UInt(4.W))
  val s_output_active_o = Output(UInt(4.W))
  val e_output_active_o = Output(UInt(4.W))

  val prog_clk_i = Input(Clock())
  val prog_rst_i = Input(Bool())
  val prog_done_i = Input(Bool())
  val prog_we_i = Input(Bool())
  val prog_din_i = Input(Bool())
  val prog_dout_o = Output(Bool())
  val prog_we_o = Output(Bool())
}

/** Resource-backed wrapper for the generated SystemVerilog artifact.
  *
  * `RtaV4Bundle.sv` is one self-contained compilation unit. Adding only this
  * resource avoids duplicate BaseJump or generated-module definitions.
  */
class RtaV4BlackBox extends BlackBox with HasBlackBoxResource {
  override def desiredName: String = "rta_v4_chipyard_adapter"

  val io = IO(new RtaV4BlackBoxIO)

  addResource("/vsrc/rta_v4/RtaV4Bundle.sv")
}

/** Bring-up-oriented TileLink register shell for RTA V4.
  *
  * Configuration is serialized in hardware from 32-bit software writes. The
  * runtime datapath remains a deliberately low-throughput MMIO bring-up path;
  * it is not presented as a ready/valid stream or a DMA interface.
  */
class RtaV4TL(params: RtaV4Params, beatBytes: Int)(implicit p: Parameters)
    extends RegisterRouter(RegisterRouterParams(
      name = "rta-v4",
      compat = Seq("dora,rta-v4"),
      base = params.address,
      size = 4096,
      beatBytes = beatBytes,
      undefZero = true))
    with HasTLControlRegMap {

  override lazy val module = new Impl

  class Impl extends LazyModuleImp(this) {
    val controller = Module(new RtaV4Controller(RtaV4ControllerParams(
      scanBits = RtaV4Artifact.ScanBits)))
    val impl = Module(new RtaV4BlackBox)

    val configCommand = Wire(new DecoupledIO(UInt(32.W)))
    val configData = Wire(new DecoupledIO(UInt(32.W)))
    val configErrorClear = Wire(new DecoupledIO(UInt(8.W)))
    val computeCommand = Wire(new DecoupledIO(UInt(32.W)))
    val computeErrorClear = Wire(new DecoupledIO(UInt(8.W)))

    controller.io.configCommand <> configCommand
    controller.io.configData <> configData
    controller.io.configErrorClear <> configErrorClear
    controller.io.computeCommand <> computeCommand
    controller.io.computeErrorClear <> computeErrorClear

    val westInputs = Seq.fill(4)(RegInit(0.U(17.W)))
    val northInputs = Seq.fill(4)(RegInit(0.U(17.W)))
    val westWrites = Seq.fill(4)(Wire(new DecoupledIO(UInt(17.W))))
    val northWrites = Seq.fill(4)(Wire(new DecoupledIO(UInt(17.W))))
    val inputWrites = westWrites ++ northWrites

    inputWrites.zip(westInputs ++ northInputs).foreach { case (write, lane) =>
      write.ready := true.B
      when (write.fire && controller.io.inputWritable) {
        lane := write.bits
      }
    }
    controller.io.inputWrite := inputWrites.map(_.fire).reduce(_ || _)

    impl.io.clk_i := clock
    impl.io.reset_i := reset.asBool || controller.io.computeReset
    impl.io.en_i := controller.io.computeEnable
    impl.io.west_data0_i := Cat(westInputs.reverse.map(_(7, 0)))
    impl.io.west_data1_i := Cat(westInputs.reverse.map(_(15, 8)))
    impl.io.west_pred_i := Cat(westInputs.reverse.map(_(16)))
    impl.io.north_data0_i := Cat(northInputs.reverse.map(_(7, 0)))
    impl.io.north_data1_i := Cat(northInputs.reverse.map(_(15, 8)))
    impl.io.north_pred_i := Cat(northInputs.reverse.map(_(16)))

    // The reference integration intentionally uses the PBUS-derived clock for
    // both domains. A future split clock must add an explicit CDC boundary.
    impl.io.prog_clk_i := clock
    impl.io.prog_rst_i := reset.asBool || controller.io.progReset
    impl.io.prog_done_i := controller.io.progDone
    impl.io.prog_we_i := controller.io.progWriteEnable
    impl.io.prog_din_i := controller.io.progDataOut
    controller.io.progWriteEnableIn := impl.io.prog_we_o
    controller.io.progDataIn := impl.io.prog_dout_o

    val activity = Cat(
      impl.io.e_output_active_o,
      impl.io.s_output_active_o,
      impl.io.w_input_active_o,
      impl.io.n_input_active_o)
    controller.io.eastData0 := impl.io.east_data0_o
    controller.io.eastData1 := impl.io.east_data1_o
    controller.io.eastPredicate := impl.io.east_pred_o
    controller.io.southData0 := impl.io.south_data0_o
    controller.io.southData1 := impl.io.south_data1_o
    controller.io.southPredicate := impl.io.south_pred_o
    controller.io.activity := activity

    val configStatus = Cat(
      0.U(22.W),
      controller.io.scanTailSeen,
      impl.io.prog_dout_o,
      impl.io.prog_we_o,
      controller.io.configErrors.orR ||
        controller.io.configState === RtaV4Controller.StateError.U,
      controller.io.configured,
      controller.io.configBusy,
      controller.io.configDataReady,
      controller.io.configState)
    val computeStatus = Cat(
      0.U(24.W),
      controller.io.inputWritable,
      controller.io.computeErrors.orR,
      controller.io.snapshotValid,
      controller.io.runEnable,
      controller.io.softwareComputeReset,
      controller.io.computeEnable,
      controller.io.computeReset,
      controller.io.configured)
    val scratch = RegInit(0.U(32.W))

    def desc(name: String, description: String, volatile: Boolean = false) =
      RegFieldDesc(name, description, volatile = volatile)
    def packedLane(data0: UInt, data1: UInt, predicate: UInt, lane: Int) =
      Cat(predicate(lane), data1(8 * lane + 7, 8 * lane),
        data0(8 * lane + 7, 8 * lane))

    import RtaV4Registers._
    val identityMap = Seq(
      DeviceId -> Seq(RegField.r(32, IdValue.U(32.W),
        desc("device_id", "ASCII RTA4 device identifier"))),
      AbiVersion -> Seq(RegField.r(32, AbiVersionValue.U(32.W),
        desc("abi_version", "RTA V4 MMIO ABI major/minor version"))),
      Capabilities -> Seq(RegField.r(32, CapabilitiesValue.U(32.W),
        desc("capabilities", "Rows, columns, data width, planes, and predicate width"))),
      BitstreamBits -> Seq(RegField.r(32, RtaV4Artifact.ScanBits.U(32.W),
        desc("bitstream_bits", "Exact number of valid configuration bits")))) ++
      RtaV4Artifact.LayoutHashWords.zipWithIndex.map { case (word, index) =>
        (LayoutHashBase + 8 * index) -> Seq(RegField.r(32, word.U(32.W),
          desc(s"layout_hash_$index", "Frozen DORA layout hash word")))
      } ++ Seq(
      Scratch -> Seq(RegField(32, scratch,
        desc("scratch", "Read/write bus bring-up register", volatile = true))))

    val configMap = Seq(
      ConfigCommand -> Seq(RegField.w(32, configCommand,
        desc("config_command",
          "Write-one pulse: bit 0 START, bit 1 ABORT; bit 2 makes START preserve compute state"))),
      ConfigStatus -> Seq(RegField.r(32, configStatus,
        desc("config_status", "Configuration state and raw scan status", volatile = true))),
      ConfigData -> Seq(RegField.w(32, configData,
        desc("config_data", "Next 32 configuration bits, least-significant bit first"))),
      ConfigBitsIn -> Seq(RegField.r(32, controller.io.scanBitsShifted,
        desc("config_bits_in", "Bits accepted by the scan input", volatile = true))),
      ConfigBitsOut -> Seq(RegField.r(32, controller.io.scanBitsAtTail,
        desc("config_bits_out", "Valid bits observed at the scan tail", volatile = true))),
      ConfigError -> Seq(RegField(8, controller.io.configErrors, configErrorClear,
        desc("config_error", "Sticky configuration errors; write one to clear", volatile = true))))

    val computeMap = Seq(
      ComputeControl -> Seq(RegField.w(32, computeCommand,
        desc("compute_control", "RESET/RUN levels and STEP/CAPTURE pulses"))),
      ComputeStatus -> Seq(RegField.r(32, computeStatus,
        desc("compute_status", "Compute gating and snapshot status", volatile = true))),
      SnapshotSeq -> Seq(RegField.r(32, controller.io.snapshotSequence,
        desc("snapshot_sequence", "Atomic output snapshot sequence", volatile = true))),
      ComputeError -> Seq(RegField(8, controller.io.computeErrors, computeErrorClear,
        desc("compute_error", "Sticky compute-protocol errors; write one to clear", volatile = true))))

    val inputMap = westInputs.indices.flatMap { lane =>
      Seq(
        (WestInputBase + 8 * lane) -> Seq(RegField(
          17, westInputs(lane), westWrites(lane),
          desc(s"west_input_$lane", "Packed data0, data1, and predicate lane"))),
        (NorthInputBase + 8 * lane) -> Seq(RegField(
          17, northInputs(lane), northWrites(lane),
          desc(s"north_input_$lane", "Packed data0, data1, and predicate lane"))))
    }

    val outputMap = westInputs.indices.flatMap { lane =>
      Seq(
        (EastOutputBase + 8 * lane) -> Seq(RegField.r(17,
          packedLane(
            controller.io.snapshotEastData0,
            controller.io.snapshotEastData1,
            controller.io.snapshotEastPredicate,
            lane),
          desc(s"east_output_$lane", "Captured packed east output lane", volatile = true))),
        (SouthOutputBase + 8 * lane) -> Seq(RegField.r(17,
          packedLane(
            controller.io.snapshotSouthData0,
            controller.io.snapshotSouthData1,
            controller.io.snapshotSouthPredicate,
            lane),
          desc(s"south_output_$lane", "Captured packed south output lane", volatile = true))))
    } ++ Seq(
      Activity -> Seq(RegField.r(16, controller.io.snapshotActivity,
        desc("activity", "Captured N/W/S/E activity masks", volatile = true))))

    regmap((identityMap ++ configMap ++ computeMap ++ inputMap ++ outputMap): _*)
  }
}

case object RtaV4Injector extends SubsystemInjector((p, baseSubsystem) => {
  p(RtaV4Key).foreach { params =>
    implicit val q: Parameters = p
    val pbus = baseSubsystem.locateTLBusWrapper(PBUS)
    val domain = pbus.generateSynchronousDomain("RTA V4")
      .suggestName("rta_v4_domain")
    val peripheral = domain {
      LazyModule(new RtaV4TL(params, pbus.beatBytes)(p))
    }
    pbus.coupleTo("rta_v4") {
      peripheral.controlXing(NoCrossing) :=
        TLFragmenter(pbus.beatBytes, pbus.blockBytes) := _
    }
  }
})

class WithRtaV4(address: BigInt = 0x10050000L)
    extends Config((site, here, up) => {
      case RtaV4Key => Some(RtaV4Params(address = address))
      case SubsystemInjectorKey =>
        up(SubsystemInjectorKey) + RtaV4Injector
    })
