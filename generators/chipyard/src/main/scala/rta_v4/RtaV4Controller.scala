package chipyard.rta_v4

import chisel3._
import chisel3.util._

case class RtaV4ControllerParams(
  scanBits: Int,
  programResetCycles: Int = 2,
  programResetReleaseCycles: Int = 4,
  scanTailTimeoutCycles: Int = 128,
  programDoneSettleCycles: Int = 8
) {
  require(scanBits > 0)
  require(programResetCycles >= 2)
  require(programResetReleaseCycles >= 2)
  require(scanTailTimeoutCycles > 0)
  require(programDoneSettleCycles > 0)
}

object RtaV4Controller {
  val StateIdle   = 0
  val StateReset  = 1
  val StateLoad   = 2
  val StateDrain  = 3
  val StateCommit = 4
  val StateReady  = 5
  val StateError  = 6
  val StateRelease = 7

  val ConfigErrorInvalidCommand = 1 << 0
  val ConfigErrorUnexpectedData = 1 << 1
  val ConfigErrorBadPadding     = 1 << 2
  val ConfigErrorTailCount      = 1 << 3
  val ConfigErrorTailTimeout    = 1 << 4

  val ComputeErrorInvalidCommand   = 1 << 0
  val ComputeErrorStepWhileRunning = 1 << 1
  val ComputeErrorCaptureWhileRun  = 1 << 2
  val ComputeErrorInputWhileRun    = 1 << 3
  val ComputeErrorConflictingBits  = 1 << 4
  val ComputeErrorPulseWhileReset  = 1 << 5
}

/** Hardware policy between the software register bank and the raw RTA port.
  *
  * Configuration data arrives as 32-bit words and leaves LSB first as a
  * one-bit scan stream. This module owns programming reset, tail draining,
  * programming completion, compute gating, and atomic output snapshots. It is
  * deliberately independent of TileLink and the SystemVerilog implementation
  * so its protocol can be unit tested quickly.
  */
class RtaV4Controller(params: RtaV4ControllerParams) extends Module {
  val io = IO(new Bundle {
    val configCommand = Flipped(Decoupled(UInt(32.W)))
    val configData = Flipped(Decoupled(UInt(32.W)))
    val configErrorClear = Flipped(Decoupled(UInt(8.W)))

    val computeCommand = Flipped(Decoupled(UInt(32.W)))
    val computeErrorClear = Flipped(Decoupled(UInt(8.W)))
    val inputWrite = Input(Bool())

    val progReset = Output(Bool())
    val progDone = Output(Bool())
    val progWriteEnable = Output(Bool())
    val progDataOut = Output(Bool())
    val progWriteEnableIn = Input(Bool())
    val progDataIn = Input(Bool())

    val computeReset = Output(Bool())
    val computeEnable = Output(Bool())
    val inputWritable = Output(Bool())

    val eastData0 = Input(UInt(32.W))
    val eastData1 = Input(UInt(32.W))
    val eastPredicate = Input(UInt(4.W))
    val southData0 = Input(UInt(32.W))
    val southData1 = Input(UInt(32.W))
    val southPredicate = Input(UInt(4.W))
    val activity = Input(UInt(16.W))

    val snapshotEastData0 = Output(UInt(32.W))
    val snapshotEastData1 = Output(UInt(32.W))
    val snapshotEastPredicate = Output(UInt(4.W))
    val snapshotSouthData0 = Output(UInt(32.W))
    val snapshotSouthData1 = Output(UInt(32.W))
    val snapshotSouthPredicate = Output(UInt(4.W))
    val snapshotActivity = Output(UInt(16.W))
    val snapshotValid = Output(Bool())
    val snapshotSequence = Output(UInt(32.W))

    val configState = Output(UInt(3.W))
    val configDataReady = Output(Bool())
    val configBusy = Output(Bool())
    val configured = Output(Bool())
    val configErrors = Output(UInt(8.W))
    val scanBitsShifted = Output(UInt(32.W))
    val scanBitsAtTail = Output(UInt(32.W))
    val scanTailSeen = Output(Bool())

    val softwareComputeReset = Output(Bool())
    val runEnable = Output(Bool())
    val computeErrors = Output(UInt(8.W))
  })

  import RtaV4Controller._

  // Append RELEASE so the public values of the original states remain stable.
  val sIdle :: sReset :: sLoad :: sDrain :: sCommit :: sReady :: sError :: sRelease :: Nil =
    Enum(8)
  val state = RegInit(sIdle)

  val configErrors = RegInit(0.U(8.W))
  val computeErrors = RegInit(0.U(8.W))
  val scanBitsShifted = RegInit(0.U(32.W))
  val scanBitsAtTail = RegInit(0.U(32.W))
  val scanTailSeen = RegInit(false.B)

  val shiftWord = RegInit(0.U(32.W))
  val wordValid = RegInit(false.B)
  val wordBitsRemaining = RegInit(0.U(6.W))

  val resetCounterWidth = log2Ceil(params.programResetCycles max 2)
  val resetCounter = RegInit(0.U(resetCounterWidth.W))
  val releaseCounterWidth = log2Ceil(params.programResetReleaseCycles max 2)
  val releaseCounter = RegInit(0.U(releaseCounterWidth.W))
  val tailCounterWidth = log2Ceil(params.scanTailTimeoutCycles max 2)
  val tailCounter = RegInit(0.U(tailCounterWidth.W))
  val settleCounterWidth = log2Ceil(params.programDoneSettleCycles max 2)
  val settleCounter = RegInit(0.U(settleCounterWidth.W))

  val softwareComputeReset = RegInit(true.B)
  val runEnable = RegInit(false.B)
  // A warm reload reprograms the scan chain while the compute clock is
  // quiesced, but deliberately leaves the independent compute reset low so
  // stateful resources such as the RTA V4 RMU accumulators survive.
  val preserveComputeState = RegInit(false.B)
  val stepPulse = WireDefault(false.B)

  val snapshotEastData0 = RegInit(0.U(32.W))
  val snapshotEastData1 = RegInit(0.U(32.W))
  val snapshotEastPredicate = RegInit(0.U(4.W))
  val snapshotSouthData0 = RegInit(0.U(32.W))
  val snapshotSouthData1 = RegInit(0.U(32.W))
  val snapshotSouthPredicate = RegInit(0.U(4.W))
  val snapshotActivity = RegInit(0.U(16.W))
  val snapshotValid = RegInit(false.B)
  val snapshotSequence = RegInit(0.U(32.W))

  val configured = state === sReady
  val configBusy = state === sReset || state === sRelease || state === sLoad ||
    state === sDrain || state === sCommit
  val configDataReady = state === sLoad && !wordValid

  // Command/data writes always complete at the MMIO boundary. A write made
  // outside its advertised acceptance window becomes a sticky safe error
  // instead of hanging the bus indefinitely.
  io.configCommand.ready := true.B
  io.configData.ready := true.B
  io.configErrorClear.ready := true.B
  io.computeCommand.ready := true.B
  io.computeErrorClear.ready := true.B

  io.progReset := state === sIdle || state === sReset || state === sError
  io.progDone := state === sCommit || state === sReady
  io.progWriteEnable := state === sLoad && wordValid
  io.progDataOut := shiftWord(0)

  io.computeReset := softwareComputeReset ||
    (!configured && !preserveComputeState) || configErrors.orR
  io.computeEnable := configured && !io.computeReset && (runEnable || stepPulse)
  io.inputWritable := !runEnable

  io.snapshotEastData0 := snapshotEastData0
  io.snapshotEastData1 := snapshotEastData1
  io.snapshotEastPredicate := snapshotEastPredicate
  io.snapshotSouthData0 := snapshotSouthData0
  io.snapshotSouthData1 := snapshotSouthData1
  io.snapshotSouthPredicate := snapshotSouthPredicate
  io.snapshotActivity := snapshotActivity
  io.snapshotValid := snapshotValid
  io.snapshotSequence := snapshotSequence

  io.configState := state
  io.configDataReady := configDataReady
  io.configBusy := configBusy
  io.configured := configured
  io.configErrors := configErrors
  io.scanBitsShifted := scanBitsShifted
  io.scanBitsAtTail := scanBitsAtTail
  io.scanTailSeen := scanTailSeen
  io.softwareComputeReset := softwareComputeReset
  io.runEnable := runEnable
  io.computeErrors := computeErrors

  val configErrorSet = Wire(Vec(8, Bool()))
  val computeErrorSet = Wire(Vec(8, Bool()))
  configErrorSet.foreach(_ := false.B)
  computeErrorSet.foreach(_ := false.B)

  def setConfigError(mask: Int): Unit = {
    (0 until 8).filter(bit => (mask & (1 << bit)) != 0).foreach { bit =>
      configErrorSet(bit) := true.B
    }
  }

  def setComputeError(mask: Int): Unit = {
    (0 until 8).filter(bit => (mask & (1 << bit)) != 0).foreach { bit =>
      computeErrorSet(bit) := true.B
    }
  }

  def enterSafeIdle(): Unit = {
    state := sIdle
    scanBitsShifted := 0.U
    scanBitsAtTail := 0.U
    scanTailSeen := false.B
    wordValid := false.B
    wordBitsRemaining := 0.U
    resetCounter := 0.U
    releaseCounter := 0.U
    tailCounter := 0.U
    settleCounter := 0.U
    softwareComputeReset := true.B
    runEnable := false.B
    preserveComputeState := false.B
    snapshotValid := false.B
  }

  def failConfiguration(mask: Int): Unit = {
    setConfigError(mask)
    state := sError
    wordValid := false.B
    softwareComputeReset := true.B
    runEnable := false.B
    preserveComputeState := false.B
    snapshotValid := false.B
  }

  def beginConfiguration(preserveState: Bool): Unit = {
    state := sReset
    configErrors := 0.U
    computeErrors := 0.U
    scanBitsShifted := 0.U
    scanBitsAtTail := 0.U
    scanTailSeen := false.B
    shiftWord := 0.U
    wordValid := false.B
    wordBitsRemaining := 0.U
    resetCounter := 0.U
    releaseCounter := 0.U
    tailCounter := 0.U
    settleCounter := 0.U
    softwareComputeReset := !preserveState
    runEnable := false.B
    preserveComputeState := preserveState
    snapshotValid := false.B
  }

  when (io.configErrorClear.fire) {
    configErrors := configErrors & ~io.configErrorClear.bits
  }
  when (io.computeErrorClear.fire) {
    computeErrors := computeErrors & ~io.computeErrorClear.bits
  }

  when (io.configCommand.fire) {
    val startRequested = io.configCommand.bits(0)
    val abortRequested = io.configCommand.bits(1)
    val preserveRequested = io.configCommand.bits(2)
    val invalidCommand = io.configCommand.bits(31, 3).orR ||
      (startRequested && abortRequested) ||
      (abortRequested && preserveRequested) ||
      (preserveRequested && !startRequested)

    when (invalidCommand) {
      failConfiguration(ConfigErrorInvalidCommand)
    } .elsewhen (abortRequested) {
      enterSafeIdle()
    } .elsewhen (startRequested) {
      when (preserveRequested) {
        // State-preserving START is intentionally narrow: software must first
        // stop RUN and release compute reset in a valid READY configuration.
        // The compute clock remains gated throughout programming.
        when (state === sReady && !softwareComputeReset && !runEnable) {
          beginConfiguration(true.B)
        } .otherwise {
          failConfiguration(ConfigErrorInvalidCommand)
        }
      } .otherwise {
        when (state === sIdle || state === sReady || state === sError) {
          beginConfiguration(false.B)
        } .otherwise {
          failConfiguration(ConfigErrorInvalidCommand)
        }
      }
    }
  }

  when (!io.configCommand.fire) {
    when (state === sReset) {
      when (resetCounter === (params.programResetCycles - 1).U) {
        resetCounter := 0.U
        releaseCounter := 0.U
        state := sRelease
      } .otherwise {
        resetCounter := resetCounter + 1.U
      }
    }

    // The frozen array distributes prog_rst_i through two clocked buffers.
    // Four quiet cycles match the DORA oracle and keep bit zero from being
    // sampled while the internal scan head is still in reset.
    when (state === sRelease) {
      when (releaseCounter ===
          (params.programResetReleaseCycles - 1).U) {
        releaseCounter := 0.U
        state := sLoad
      } .otherwise {
        releaseCounter := releaseCounter + 1.U
      }
    }

    when (io.configData.fire) {
      when (configDataReady) {
        val remaining = params.scanBits.U(32.W) - scanBitsShifted
        shiftWord := io.configData.bits
        wordBitsRemaining := Mux(remaining >= 32.U, 32.U, remaining)(5, 0)
        wordValid := true.B

        if ((params.scanBits % 32) != 0) {
          val finalWordStart = params.scanBits - (params.scanBits % 32)
          when (scanBitsShifted === finalWordStart.U &&
              io.configData.bits(31, params.scanBits % 32).orR) {
            failConfiguration(ConfigErrorBadPadding)
          }
        }
      } .otherwise {
        failConfiguration(ConfigErrorUnexpectedData)
      }
    }

    when (state === sLoad && wordValid) {
      shiftWord := shiftWord >> 1
      scanBitsShifted := scanBitsShifted + 1.U
      wordBitsRemaining := wordBitsRemaining - 1.U
      when (wordBitsRemaining === 1.U) {
        wordValid := false.B
        when (scanBitsShifted === (params.scanBits - 1).U) {
          tailCounter := 0.U
          state := sDrain
        }
      }
    }

    when ((state === sLoad || state === sDrain) && io.progWriteEnableIn) {
      scanTailSeen := true.B
      when (scanBitsAtTail < params.scanBits.U) {
        scanBitsAtTail := scanBitsAtTail + 1.U
      } .otherwise {
        failConfiguration(ConfigErrorTailCount)
      }
    }

    when (state === sDrain) {
      // Do not assert prog_done_i until a separate cycle has observed the
      // tail-valid signal low after all expected tokens.
      when (!io.progWriteEnableIn &&
          scanBitsAtTail === params.scanBits.U) {
        settleCounter := 0.U
        state := sCommit
      } .elsewhen (tailCounter === (params.scanTailTimeoutCycles - 1).U) {
        failConfiguration(ConfigErrorTailTimeout)
      } .otherwise {
        tailCounter := tailCounter + 1.U
      }
    }

    when (state === sCommit) {
      when (io.progWriteEnableIn) {
        failConfiguration(ConfigErrorTailCount)
      } .elsewhen (settleCounter ===
          (params.programDoneSettleCycles - 1).U) {
        settleCounter := 0.U
        state := sReady
        preserveComputeState := false.B
      } .otherwise {
        settleCounter := settleCounter + 1.U
      }
    }

    when (state === sReady && io.progWriteEnableIn) {
      failConfiguration(ConfigErrorTailCount)
    }

    when (io.computeCommand.fire) {
      val requestedReset = io.computeCommand.bits(0)
      val requestedRun = io.computeCommand.bits(1)
      val requestedStep = io.computeCommand.bits(2)
      val requestedCapture = io.computeCommand.bits(3)
      val reservedBits = io.computeCommand.bits(31, 4).orR
      val conflictingBits =
        (requestedReset && (requestedRun || requestedStep || requestedCapture)) ||
        (requestedRun && (requestedStep || requestedCapture)) ||
        (requestedStep && requestedCapture)

      when (!configured) {
        softwareComputeReset := true.B
        runEnable := false.B
        when (io.computeCommand.bits =/= 1.U) {
          setComputeError(ComputeErrorInvalidCommand)
        }
      } .elsewhen (reservedBits) {
        setComputeError(ComputeErrorInvalidCommand)
      } .elsewhen (conflictingBits) {
        setComputeError(ComputeErrorConflictingBits)
      } .elsewhen ((requestedStep || requestedCapture) &&
          softwareComputeReset) {
        setComputeError(ComputeErrorPulseWhileReset)
      } .elsewhen (requestedStep && runEnable) {
        setComputeError(ComputeErrorStepWhileRunning)
      } .elsewhen (requestedCapture && runEnable) {
        setComputeError(ComputeErrorCaptureWhileRun)
      } .otherwise {
        softwareComputeReset := requestedReset
        when (requestedReset) {
          runEnable := false.B
        } .otherwise {
          runEnable := requestedRun
        }

        when (requestedStep) {
          stepPulse := true.B
        }

        when (requestedCapture) {
          snapshotEastData0 := io.eastData0
          snapshotEastData1 := io.eastData1
          snapshotEastPredicate := io.eastPredicate
          snapshotSouthData0 := io.southData0
          snapshotSouthData1 := io.southData1
          snapshotSouthPredicate := io.southPredicate
          snapshotActivity := io.activity
          snapshotValid := true.B
          snapshotSequence := snapshotSequence + 1.U
        }
      }
    }

    when (io.inputWrite && runEnable) {
      setComputeError(ComputeErrorInputWhileRun)
    }
  }

  val clearedConfigErrors = Mux(io.configErrorClear.fire,
    configErrors & ~io.configErrorClear.bits, configErrors)
  val clearedComputeErrors = Mux(io.computeErrorClear.fire,
    computeErrors & ~io.computeErrorClear.bits, computeErrors)
  when (configErrorSet.asUInt.orR) {
    configErrors := clearedConfigErrors | configErrorSet.asUInt
  }
  when (computeErrorSet.asUInt.orR) {
    computeErrors := clearedComputeErrors | computeErrorSet.asUInt
  }
}
