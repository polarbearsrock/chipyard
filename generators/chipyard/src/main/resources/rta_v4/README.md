# RTA V4 Chipyard integration

This directory contains the authored platform boundary for the frozen DORA RTA
V4 artifact. The generated HDL snapshot is imported from a verified format-1
DORA Design Package; it and its package-based provenance lock live in
`../vsrc/rta_v4/`. Chipyard compiles only `RtaV4Bundle.sv` through a single
`HasBlackBoxResource` annotation, so the Scala side and `desiredName` are
unchanged by the package transition.

The first SoC integration is intentionally a control-plane bring-up vehicle:

- `RtaV4BlackBox` describes the packed SystemVerilog boundary.
- `RtaV4Controller` owns scan serialization, programming reset/completion,
  compute safety gates, and atomic output snapshots.
- `RtaV4TL` owns the software ABI and attaches to PBUS through a
  `SubsystemInjector`.
- `RtaV4RocketConfig` instantiates one Rocket core and the RTA V4 peripheral
  at `0x1005_0000`.

Compute and programming currently use the PBUS-derived clock. There is no DMA,
interrupt, independent CGRA clock, or ready/valid streaming interface in this
phase. The activity masks are informational configuration metadata, not
backpressure signals.

## MMIO ABI v1.1

All implemented payloads are at most 32 bits, and every register occupies its
own 8-byte slot. Software should use aligned 32-bit volatile accesses. The
upper half of an aligned 64-bit access is reserved and reads as zero.

| Offset | Name | Access | Meaning |
| ---: | --- | --- | --- |
| `0x000` | `DEVICE_ID` | RO | `0x52544134` (`RTA4`) |
| `0x008` | `ABI_VERSION` | RO | `0x00010001` |
| `0x010` | `CAPABILITIES` | RO | `0x12080404`; rows, columns, data width, planes, predicate width |
| `0x018` | `BITSTREAM_BITS` | RO | `3140` |
| `0x020..0x058` | `LAYOUT_HASH[0..7]` | RO | frozen 256-bit DORA layout hash |
| `0x060` | `SCRATCH` | RW | bus bring-up register |
| `0x080` | `CONFIG_COMMAND` | WO | bit 0 START, bit 1 ABORT; bit 2 makes START preserve compute state |
| `0x088` | `CONFIG_STATUS` | RO | state and scan status |
| `0x090` | `CONFIG_DATA` | WO | next 32 bits, LSB first |
| `0x098` | `CONFIG_BITS_IN` | RO | bits shifted into the scan chain |
| `0x0a0` | `CONFIG_BITS_OUT` | RO | valid bits observed at the tail |
| `0x0a8` | `CONFIG_ERROR` | RW1C | sticky configuration errors |
| `0x0c0` | `COMPUTE_CONTROL` | WO | RESET, RUN, STEP, CAPTURE |
| `0x0c8` | `COMPUTE_STATUS` | RO | compute gates and snapshot state |
| `0x0d0` | `SNAPSHOT_SEQUENCE` | RO | increments on each capture |
| `0x0d8` | `COMPUTE_ERROR` | RW1C | sticky compute-protocol errors |
| `0x100..0x118` | `WEST_INPUT[0..3]` | RW | packed input lanes |
| `0x120..0x138` | `NORTH_INPUT[0..3]` | RW | packed input lanes |
| `0x140..0x158` | `EAST_OUTPUT[0..3]` | RO | captured output lanes |
| `0x160..0x178` | `SOUTH_OUTPUT[0..3]` | RO | captured output lanes |
| `0x180` | `ACTIVITY` | RO | captured N/W/S/E masks |

Each lane uses bits `[7:0]` for data plane 0, `[15:8]` for data plane 1,
and bit `[16]` for the predicate. Activity packs N in `[3:0]`, W in `[7:4]`,
S in `[11:8]`, and E in `[15:12]`.

`CAPABILITIES` packs rows in `[7:0]`, columns in `[15:8]`, data width in
`[23:16]`, data planes in `[27:24]`, and predicate width in `[31:28]`.
Layout-hash word 0 contains the first eight displayed hexadecimal digits of
the DORA hash, followed in display order by words 1 through 7.

`CONFIG_STATUS` packs state in `[2:0]`, data-ready in bit 3, busy in bit 4,
configured in bit 5, any-error in bit 6, raw `prog_we_o` in bit 7, raw
`prog_dout_o` in bit 8, and tail-seen in bit 9. Any-error remains asserted in
the terminal error state even if the RW1C cause bits are cleared. Configuration
states are idle 0, reset 1, load 2, drain 3, commit 4, ready 5, error 6, and
reset-release quiet 7.

`COMPUTE_CONTROL` uses RESET bit 0 and RUN bit 1 as levels. STEP bit 2 and
CAPTURE bit 3 are write pulses. A write of zero releases reset and stops RUN.
STEP is accepted only while configured, out of reset, and stopped. CAPTURE
atomically samples every output lane and activity mask while stopped.

`CONFIG_ERROR` uses bit 0 for an invalid command, bit 1 for unexpected data,
bit 2 for nonzero final-word padding, bit 3 for a tail-count violation, and
bit 4 for a tail timeout. `COMPUTE_ERROR` uses bit 0 for an invalid command,
bit 1 for STEP while running, bit 2 for CAPTURE while running, bit 3 for an
input write while running, bit 4 for conflicting command bits, and bit 5 for
a STEP or CAPTURE pulse while software reset is asserted. Invalid or
conflicting `COMPUTE_CONTROL` commands are acknowledged, made sticky, and
otherwise have no side effects. Invalid configuration commands fail closed:
they enter ERROR, assert compute reset, stop RUN, and invalidate the output
snapshot. Both error registers are write-one-to-clear; START or ABORT is
required to leave the terminal configuration-error state.

A normal START (`0x1`) is a cold configuration and asserts compute reset. A
state-preserving START (`0x5`, START plus bit 2) is accepted only from READY
after software has released compute reset and stopped RUN. It gates compute
enable while programming but does not assert the independent compute reset,
so sequential datapath state such as the RMU accumulators survives. It still
invalidates the previous output snapshot. ABORT, an illegal command, or any
configuration failure returns to the reset-safe behavior.

## Programming sequence

1. Validate the ID, ABI version, scan length, and layout hash.
2. Write START to `CONFIG_COMMAND`.
3. Poll data-ready, then write 99 words to `CONFIG_DATA`. Bytes are ascending
   and bits within each word are consumed least-significant bit first. Only
   bits `[3:0]` of the final word are valid; nonzero padding is an error.
4. Poll configured or error. Hardware asserts programming reset for two
   cycles, allows four quiet cycles for the array's registered reset tree to
   release, shifts exactly 3,140 bits, explicitly observes the scan-tail valid
   signal low, asserts `prog_done_i`, and waits for it to settle.
5. Write inputs while stopped, write zero to `COMPUTE_CONTROL` to release
   compute reset, then use STEP for deterministic bring-up or RUN for a fixed
   MMIO input vector. The frozen add-chain needs 14 STEP writes for a sample
   launched from reset (its streaming launch/observe index delta is 13). Stop
   before CAPTURE and read only the captured outputs.

The bare-metal `rta-v4` test in the repository `tests/` directory performs
this sequence with the frozen add-chain image. The `rta-v4-systolic` test uses
the DORA `array_systolic` oracle's clear, compute, and four drain images. It
first checks DORA's fixed 4x4 signed-INT4 dot4 GEMM oracle, then runs eight
deterministic pseudo-random matrices covering `K=1..8`. The Rocket core builds
an independent signed-INT4 reference result for every random case and compares
all 16 hardware outputs. State-preserving START between phases keeps the 16
RMU accumulators alive; state-preserving clear reloads between cases also prove
that one matrix cannot leak accumulator state into the next.

## End-to-end SoC regression

Run the complete Rocket/TileLink/RTA V4 regression from an initialized
Chipyard shell:

```sh
source env.sh
make -C generators/chipyard/src/test/resources/rta_v4 soc-smoke
make -C generators/chipyard/src/test/resources/rta_v4 soc-systolic-smoke
```

Each opt-in target builds its corresponding source (`tests/rta-v4.c` or
`tests/rta-v4-systolic.c`) under `TMPDIR`, builds or reuses the
`RtaV4RocketConfig` Verilator simulator, preloads the ELF into simulated DRAM,
and boots it on the Rocket core. Direct DRAM preload avoids a slow serial
transfer; it does not bypass CPU execution or the TileLink/MMIO path. A passing
add-chain run prints `RTA V4 add-chain result 0xb1 is correct` and exits with
status zero. The systolic run prints
`RTA V4 systolic fixed oracle and 8 randomized signed-INT4 matrices are
correct`. Run both with `soc-smoke-all`.
Simulation output is retained under
`sims/verilator/output/chipyard.harness.TestHarness.RtaV4RocketConfig/`.

## DORA/Chipyard ownership boundary

DORA owns the generic RTL package: the complete compile closure, bundle,
licenses, integrity chain, top-module name, and producer provenance. The
format-1 package intentionally contains no port geometry, scan/configuration
semantics, compiler workspace, adapter, or workloads. Chipyard owns the packed
adapter, `compiler_arch.json` interpretation, TileLink and register ABI,
interrupts, clock crossings, workload images, and future DMA/streaming
infrastructure.

The importer pins `sha256(dora-package.json)` and records the package bundle
digest separately. This lets a future CHIA loop select an exact design package
while comparing RTL digests to decide whether a provenance-only DORA commit
requires SoC revalidation. A later stable integration descriptor can make port
and configuration semantics machine-readable without making the generic RTL
package Chipyard-specific. The state-preserving multi-image systolic regression
is the current executable contract for those semantics.
