package chipyard.rta_v4

import chisel3._
import chisel3.util.DecoupledIO
import chiseltest._
import org.scalatest.flatspec.AnyFlatSpec
import org.scalatest.matchers.should.Matchers

import scala.collection.mutable

class RtaV4ControllerSpec extends AnyFlatSpec
    with ChiselScalatestTester
    with Matchers {

  behavior of "RtaV4Controller"

  private val testParams = RtaV4ControllerParams(
    scanBits = 36,
    programResetCycles = 2,
    programResetReleaseCycles = 4,
    scanTailTimeoutCycles = 128,
    programDoneSettleCycles = 3)

  private def initialize(dut: RtaV4Controller): Unit = {
    dut.io.configCommand.valid.poke(false.B)
    dut.io.configCommand.bits.poke(0.U)
    dut.io.configData.valid.poke(false.B)
    dut.io.configData.bits.poke(0.U)
    dut.io.configErrorClear.valid.poke(false.B)
    dut.io.configErrorClear.bits.poke(0.U)
    dut.io.computeCommand.valid.poke(false.B)
    dut.io.computeCommand.bits.poke(0.U)
    dut.io.computeErrorClear.valid.poke(false.B)
    dut.io.computeErrorClear.bits.poke(0.U)
    dut.io.inputWrite.poke(false.B)
    dut.io.progWriteEnableIn.poke(false.B)
    dut.io.progDataIn.poke(false.B)
    dut.io.eastData0.poke(0.U)
    dut.io.eastData1.poke(0.U)
    dut.io.eastPredicate.poke(0.U)
    dut.io.southData0.poke(0.U)
    dut.io.southData1.poke(0.U)
    dut.io.southPredicate.poke(0.U)
    dut.io.activity.poke(0.U)
    dut.clock.step(2)
  }

  it should "serialize words LSB-first and safely gate compute and snapshots" in {
    test(new RtaV4Controller(testParams)) { dut =>
      initialize(dut)

      val serialized = mutable.ArrayBuffer.empty[Int]
      // The frozen array has 66 scan delimiters. Model that exact valid delay
      // so this test also covers the real 65-high-cycle drain behavior.
      val validDelay = mutable.Queue.fill(66)(false)

      def tick(): Unit = {
        val delayedValid = validDelay.dequeue()
        dut.io.progWriteEnableIn.poke(delayedValid.B)
        dut.io.progDataIn.poke(false.B)
        if (delayedValid) {
          dut.io.progDone.expect(false.B)
        }

        val inputValid = dut.io.progWriteEnable.peekBoolean()
        if (inputValid) {
          serialized += (if (dut.io.progDataOut.peekBoolean()) 1 else 0)
        }
        validDelay.enqueue(inputValid)
        dut.clock.step()
      }

      def writeConfigCommand(value: BigInt): Unit = {
        dut.io.configCommand.bits.poke(value.U)
        dut.io.configCommand.valid.poke(true.B)
        tick()
        dut.io.configCommand.valid.poke(false.B)
      }

      def writeConfigData(value: BigInt): Unit = {
        dut.io.configData.bits.poke(value.U)
        dut.io.configData.valid.poke(true.B)
        tick()
        dut.io.configData.valid.poke(false.B)
      }

      def writeComputeCommand(value: BigInt): Unit = {
        dut.io.computeCommand.bits.poke(value.U)
        dut.io.computeCommand.valid.poke(true.B)
        tick()
        dut.io.computeCommand.valid.poke(false.B)
      }

      dut.io.configState.expect(RtaV4Controller.StateIdle.U)
      dut.io.progReset.expect(true.B)
      dut.io.computeReset.expect(true.B)

      writeConfigCommand(1)
      dut.io.configState.expect(RtaV4Controller.StateReset.U)
      for (_ <- 0 until testParams.programResetCycles) {
        dut.io.progReset.expect(true.B)
        tick()
      }
      dut.io.configState.expect(RtaV4Controller.StateRelease.U)
      for (_ <- 0 until testParams.programResetReleaseCycles) {
        dut.io.progReset.expect(false.B)
        dut.io.configDataReady.expect(false.B)
        tick()
      }
      dut.io.configState.expect(RtaV4Controller.StateLoad.U)
      dut.io.configDataReady.expect(true.B)

      val firstWord = BigInt("89abcdef", 16)
      val finalWord = BigInt(5)
      writeConfigData(firstWord)
      while (!dut.io.configDataReady.peekBoolean()) {
        tick()
      }
      writeConfigData(finalWord)

      var completionCycles = 0
      while (!dut.io.configured.peekBoolean() && completionCycles < 160) {
        tick()
        completionCycles += 1
      }
      dut.io.configured.expect(true.B)
      dut.io.progDone.expect(true.B)
      dut.io.configErrors.expect(0.U)
      dut.io.scanBitsShifted.expect(36.U)
      dut.io.scanBitsAtTail.expect(36.U)

      val expected =
        (0 until 32).map(index => ((firstWord >> index) & 1).toInt) ++
        (0 until 4).map(index => ((finalWord >> index) & 1).toInt)
      serialized.toSeq shouldBe expected

      // Configuration completes with compute held in software reset.
      dut.io.computeReset.expect(true.B)

      // A pulse command cannot also serve as the reset-release transaction.
      writeComputeCommand(4)
      dut.io.softwareComputeReset.expect(true.B)
      dut.io.computeEnable.expect(false.B)
      (dut.io.computeErrors.peek().litValue &
        RtaV4Controller.ComputeErrorPulseWhileReset) should not be 0

      dut.io.computeErrorClear.bits.poke("hff".U)
      dut.io.computeErrorClear.valid.poke(true.B)
      tick()
      dut.io.computeErrorClear.valid.poke(false.B)
      dut.io.computeErrors.expect(0.U)

      writeComputeCommand(0)
      dut.io.computeReset.expect(false.B)
      dut.io.computeEnable.expect(false.B)

      // Conflicting and reserved commands are rejected without side effects.
      writeComputeCommand(12)
      dut.io.snapshotValid.expect(false.B)
      dut.io.computeEnable.expect(false.B)
      (dut.io.computeErrors.peek().litValue &
        RtaV4Controller.ComputeErrorConflictingBits) should not be 0
      dut.io.computeErrorClear.bits.poke("hff".U)
      dut.io.computeErrorClear.valid.poke(true.B)
      tick()
      dut.io.computeErrorClear.valid.poke(false.B)

      writeComputeCommand(16)
      (dut.io.computeErrors.peek().litValue &
        RtaV4Controller.ComputeErrorInvalidCommand) should not be 0
      dut.io.computeErrorClear.bits.poke("hff".U)
      dut.io.computeErrorClear.valid.poke(true.B)
      tick()
      dut.io.computeErrorClear.valid.poke(false.B)

      // STEP is a combinational one-cycle pulse on the command transaction.
      dut.io.computeCommand.bits.poke(4.U)
      dut.io.computeCommand.valid.poke(true.B)
      dut.io.computeEnable.expect(true.B)
      tick()
      dut.io.computeCommand.valid.poke(false.B)
      dut.io.computeEnable.expect(false.B)

      dut.io.eastData0.poke("h44332211".U)
      dut.io.eastData1.poke("h88776655".U)
      dut.io.eastPredicate.poke("ha".U)
      dut.io.southData0.poke("hccbbaa99".U)
      dut.io.southData1.poke("h10203040".U)
      dut.io.southPredicate.poke("h5".U)
      dut.io.activity.poke("h8421".U)
      writeComputeCommand(8)

      dut.io.snapshotValid.expect(true.B)
      dut.io.snapshotSequence.expect(1.U)
      dut.io.snapshotEastData0.expect("h44332211".U)
      dut.io.snapshotEastData1.expect("h88776655".U)
      dut.io.snapshotEastPredicate.expect("ha".U)
      dut.io.snapshotSouthData0.expect("hccbbaa99".U)
      dut.io.snapshotSouthData1.expect("h10203040".U)
      dut.io.snapshotSouthPredicate.expect("h5".U)
      dut.io.snapshotActivity.expect("h8421".U)

      writeComputeCommand(2)
      dut.io.runEnable.expect(true.B)
      dut.io.computeEnable.expect(true.B)

      // Independent errors raised on one cycle must accumulate.
      dut.io.computeCommand.bits.poke(16.U)
      dut.io.computeCommand.valid.poke(true.B)
      dut.io.inputWrite.poke(true.B)
      tick()
      dut.io.computeCommand.valid.poke(false.B)
      dut.io.inputWrite.poke(false.B)
      (dut.io.computeErrors.peek().litValue &
        RtaV4Controller.ComputeErrorInputWhileRun) should not be 0
      (dut.io.computeErrors.peek().litValue &
        RtaV4Controller.ComputeErrorInvalidCommand) should not be 0

      writeComputeCommand(0)
      dut.io.runEnable.expect(false.B)
      dut.io.computeEnable.expect(false.B)
    }
  }

  it should "reject nonzero padding in the final configuration word" in {
    test(new RtaV4Controller(testParams)) { dut =>
      initialize(dut)

      def write(channel: DecoupledIO[UInt], value: BigInt): Unit = {
        channel.bits.poke(value.U)
        channel.valid.poke(true.B)
        dut.clock.step()
        channel.valid.poke(false.B)
      }

      write(dut.io.configCommand, 1)
      dut.clock.step(testParams.programResetCycles +
        testParams.programResetReleaseCycles)
      write(dut.io.configData, BigInt("01234567", 16))
      while (!dut.io.configDataReady.peekBoolean()) {
        dut.clock.step()
      }

      // A 36-bit image permits only bits [3:0] in its second word.
      write(dut.io.configData, BigInt("10", 16))
      dut.io.configState.expect(RtaV4Controller.StateError.U)
      dut.io.progReset.expect(true.B)
      dut.io.configured.expect(false.B)
      (dut.io.configErrors.peek().litValue &
        RtaV4Controller.ConfigErrorBadPadding) should not be 0
    }
  }

  it should "acknowledge and reject data written while the serializer is busy" in {
    test(new RtaV4Controller(testParams)) { dut =>
      initialize(dut)

      dut.io.configCommand.bits.poke(1.U)
      dut.io.configCommand.valid.poke(true.B)
      dut.clock.step()
      dut.io.configCommand.valid.poke(false.B)
      dut.clock.step(testParams.programResetCycles +
        testParams.programResetReleaseCycles)

      dut.io.configData.bits.poke("hfeedface".U)
      dut.io.configData.valid.poke(true.B)
      dut.clock.step()
      dut.io.configData.bits.poke("hdeadbeef".U)
      dut.clock.step()
      dut.io.configData.valid.poke(false.B)

      dut.io.configState.expect(RtaV4Controller.StateError.U)
      (dut.io.configErrors.peek().litValue &
        RtaV4Controller.ConfigErrorUnexpectedData) should not be 0
    }
  }
}
