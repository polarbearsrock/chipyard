/* s2chitni & Claude (AI-generated) */
/*
 * K3 mem_axpy (y[i] = a * x[i] + b) on a DORA static HyCUBE fabric in a
 * Chipyard SoC: DORA Chisel pilot step 5, acceptance criterion A7.
 *
 * The fabric is DoraStaticHyCubeRocketConfig's (DORA_FABRIC, rendered by
 * `make -C generators/chipyard/src/test/resources/dora gen`, 4x4 PEs, 4
 * contexts), and every value here comes from the header DORA wrote with it,
 * <DORA_OUT>/sw/dora_hycube_array.h: the register map, the identity words,
 * K3's configuration image in shift order, its parameters, every memory
 * port's scratchpad before and after the run, every fabric memory write with
 * its en_i cycle, and the short run's length. The expected values are DORA's
 * reference model of K3 (examples/architectures/static_hycube/soc.py), which
 * DORA's pilot gate proves equal to K3 run standalone on the SV and on the
 * Chisel RTL (tests/examples/test_static_hycube_soc.py). This program does
 * not repeat that proof: a PASS means the SoC run matches the model of the
 * DORA commit that wrote the header.
 *
 * The program checks the header's consistency, the identity registers and the
 * shell's reset state, fills every port's scratchpad (x is at X_BASE of the
 * load port only; the other ports hold a fill pattern there, so y is right
 * only if the fabric loads from the load port), reads them back, programs the
 * image, releases the fabric's reset, runs RUN_CYCLES in one burst, then
 * compares every word of every scratchpad, the number of fabric memory writes
 * and the last-write cycle with the header. Two probes of the shell's
 * refusals (a run while in reset, an out-of-range scratchpad access) run
 * before the kernel.
 *
 * K3 stores every y[i] twice with the same value, so the full run cannot show
 * a wrong first store (a scratchpad read one cycle late makes it a *
 * x[i - 1] + b). A second, short run therefore follows: reset, the written
 * words restored, the image programmed again, then only SHORT_RUN_CYCLES
 * en_i cycles, which end after y[1]'s first store; every scratchpad must hold
 * the initial words plus the header's writes of those cycles.
 *
 * It ends with a line "DORA K3 mem_axpy: PASS" or "DORA K3 mem_axpy: FAIL
 * (...)" and returns 0 only on PASS.
 */

#include <stdint.h>
#include <stdio.h>
#include <string.h>

#include "dora_hycube_array.h"
#include "dora-runtime.h"

#ifndef DORA_HYCUBE_ARRAY_K3_RUN_CYCLES
#error "dora_hycube_array.h has no K3 kernel (K3 needs legacy_edge_io with at least 4x3 PEs; soc.json's k3.skipped says why)"
#endif
#ifndef DORA_HYCUBE_ARRAY_K3_SHORT_RUN_CYCLES
#error "dora_hycube_array.h has no K3 short run; regenerate it with this DORA (static_hycube build --soc)"
#endif

/* Mismatching words printed per scratchpad. */
#define K3_REPORT_LIMIT 8u
/* A word the out-of-range probe tries to write. */
#define K3_PROBE_WORD UINT32_C(0xbad0bad0)

_Static_assert(DORA_HYCUBE_ARRAY_ABI_VERSION == DORA_SHELL_ABI_VERSION,
    "the header's fabric and generic ABI versions differ");
_Static_assert(DORA_HYCUBE_ARRAY_MEM_PORTS >= 1u,
    "K3 needs memory ports");
_Static_assert(DORA_HYCUBE_ARRAY_K3_LOAD_PORT < DORA_HYCUBE_ARRAY_MEM_PORTS &&
    DORA_HYCUBE_ARRAY_K3_STORE_PORT < DORA_HYCUBE_ARRAY_MEM_PORTS,
    "K3's memory ports are not the fabric's");
_Static_assert(DORA_HYCUBE_ARRAY_K3_X_BASE + DORA_HYCUBE_ARRAY_K3_N <=
    DORA_HYCUBE_ARRAY_SPM_WORDS &&
    DORA_HYCUBE_ARRAY_K3_Y_BASE + DORA_HYCUBE_ARRAY_K3_N <=
    DORA_HYCUBE_ARRAY_SPM_WORDS, "x or y does not fit the scratchpad");
_Static_assert(DORA_RUNTIME_COUNT_OF(dora_hycube_array_k3_x) ==
    DORA_HYCUBE_ARRAY_K3_N, "k3_x does not hold N elements");
_Static_assert(DORA_RUNTIME_COUNT_OF(dora_hycube_array_k3_image) ==
    DORA_HYCUBE_ARRAY_SCAN_WORDS, "the K3 image is not SCAN_WORDS long");
_Static_assert(DORA_HYCUBE_ARRAY_K3_LAST_WRITE_CYCLE <
    DORA_HYCUBE_ARRAY_K3_RUN_CYCLES, "the last write is after the run");
_Static_assert(DORA_RUNTIME_COUNT_OF(dora_hycube_array_k3_writes) ==
    DORA_HYCUBE_ARRAY_K3_MEM_WRITES, "the writes table is not MEM_WRITES long");
_Static_assert(DORA_HYCUBE_ARRAY_K3_SHORT_RUN_CYCLES > 0u &&
    DORA_HYCUBE_ARRAY_K3_SHORT_RUN_CYCLES < DORA_HYCUBE_ARRAY_K3_RUN_CYCLES,
    "the short run is not shorter than the run");

static const struct dora_fabric fabric =
    DORA_FABRIC_DESCRIPTOR(HYCUBE_ARRAY, hycube_array);

/* One port's expected scratchpad after the short run. */
static uint32_t short_expected[DORA_HYCUBE_ARRAY_SPM_WORDS];

/* Row fields of dora_hycube_array_k3_writes. */
enum { W_CYCLE, W_PORT, W_ADDRESS, W_DATA };
#define K3_WRITES DORA_HYCUBE_ARRAY_K3_MEM_WRITES
#define K3_WRITE(index, what) (dora_hycube_array_k3_writes[index][what])

static int fail(const char *reason)
{
  printf("DORA K3 mem_axpy: FAIL (%s)\n", reason);
  return 1;
}

/* Whether the header's writes table writes (port, address) in a cycle at or
 * after `from`. */
static int written_from(uint32_t port, uint32_t address, uint32_t from)
{
  for (uint32_t index = 0; index < K3_WRITES; ++index)
    if (K3_WRITE(index, W_PORT) == port &&
        K3_WRITE(index, W_ADDRESS) == address && K3_WRITE(index, W_CYCLE) >= from)
      return 1;
  return 0;
}

/* port's initial scratchpad with the writes of en_i cycles before `cycles`
 * applied, into short_expected. */
static void apply_writes(uint32_t port, uint32_t cycles)
{
  memcpy(short_expected, dora_hycube_array_k3_initial[port],
      sizeof(short_expected));
  for (uint32_t index = 0; index < K3_WRITES; ++index)
    if (K3_WRITE(index, W_PORT) == port && K3_WRITE(index, W_CYCLE) < cycles)
      short_expected[K3_WRITE(index, W_ADDRESS)] = K3_WRITE(index, W_DATA);
}

/* The header is self-consistent, and its oracle can see what it claims:
 * - x[] is at X_BASE of the load port's initial scratchpad, where K3 loads
 *   it from, and no other port holds any x[i] there (a fabric loading from
 *   another port would compute other y);
 * - the writes table is in cycle order, inside the scratchpads, ends in
 *   LAST_WRITE_CYCLE, and turns every initial scratchpad into the expected
 *   one;
 * - the short run's writes and last write are the table's first cycles, and
 *   the short run shows a store the full run overwrites (a first store). */
static int check_header(void)
{
  uint32_t short_writes = 0;
  uint32_t short_last = 0;
  int overwritten = 0;

  for (uint32_t index = 0; index < DORA_HYCUBE_ARRAY_K3_N; ++index) {
    uint32_t address = DORA_HYCUBE_ARRAY_K3_X_BASE + index;
    for (uint32_t port = 0; port < DORA_HYCUBE_ARRAY_MEM_PORTS; ++port) {
      int held = dora_hycube_array_k3_initial[port][address] ==
          dora_hycube_array_k3_x[index];
      if (held != (port == DORA_HYCUBE_ARRAY_K3_LOAD_PORT)) {
        printf("dora: header: port %u's initial scratchpad %s x[%u] at word "
            "0x%x\n", (unsigned)port, held ? "also holds" : "does not hold",
            (unsigned)index, (unsigned)address);
        return 1;
      }
    }
  }
  for (uint32_t index = 0; index < K3_WRITES; ++index) {
    uint32_t cycle = K3_WRITE(index, W_CYCLE);
    if ((index > 0 && cycle < K3_WRITE(index - 1, W_CYCLE)) ||
        K3_WRITE(index, W_PORT) >= DORA_HYCUBE_ARRAY_MEM_PORTS ||
        K3_WRITE(index, W_ADDRESS) >= DORA_HYCUBE_ARRAY_SPM_WORDS) {
      printf("dora: header: write %u is out of order or outside the "
          "scratchpads\n", (unsigned)index);
      return 1;
    }
    if (cycle < DORA_HYCUBE_ARRAY_K3_SHORT_RUN_CYCLES) {
      ++short_writes;
      short_last = cycle;
      if (written_from(K3_WRITE(index, W_PORT), K3_WRITE(index, W_ADDRESS),
              DORA_HYCUBE_ARRAY_K3_SHORT_RUN_CYCLES))
        overwritten = 1;
    }
  }
  if (K3_WRITE(K3_WRITES - 1, W_CYCLE) != DORA_HYCUBE_ARRAY_K3_LAST_WRITE_CYCLE) {
    printf("dora: header: the last write is not in LAST_WRITE_CYCLE\n");
    return 1;
  }
  for (uint32_t port = 0; port < DORA_HYCUBE_ARRAY_MEM_PORTS; ++port) {
    apply_writes(port, DORA_HYCUBE_ARRAY_K3_RUN_CYCLES);
    if (memcmp(short_expected, dora_hycube_array_k3_expected[port],
            sizeof(short_expected)) != 0) {
      printf("dora: header: port %u's initial scratchpad plus the writes is "
          "not its expected one\n", (unsigned)port);
      return 1;
    }
  }
  if (short_writes != DORA_HYCUBE_ARRAY_K3_SHORT_MEM_WRITES ||
      short_last != DORA_HYCUBE_ARRAY_K3_SHORT_LAST_WRITE_CYCLE || !overwritten) {
    printf("dora: header: the short run (%u cycles) has %u writes, the last in "
        "cycle %u%s\n", (unsigned)DORA_HYCUBE_ARRAY_K3_SHORT_RUN_CYCLES,
        (unsigned)short_writes, (unsigned)short_last,
        overwritten ? "" : ", and shows no store the full run overwrites");
    return 1;
  }
  return 0;
}

/* RUN_CYCLES while CTRL.RESET is 1 is refused with ERROR.RUN: nothing
 * runs, and STATUS shows RESET and ERROR. */
static int probe_run_in_reset(void)
{
  uint32_t errors;
  uint32_t status;

  dora_write(&fabric, DORA_REG_RUN_CYCLES, 1);
  errors = dora_errors(&fabric);
  status = dora_read(&fabric, DORA_REG_STATUS);
  if (errors != DORA_ERROR_RUN ||
      status != (DORA_STATUS_RESET | DORA_STATUS_ERROR)) {
    printf("dora: STATUS 0x%08x after RUN_CYCLES in reset (expected RESET "
        "and ERROR)\n", (unsigned)status);
    dora_print_errors("RUN_CYCLES while in reset (expected RUN only)", errors);
    return 1;
  }
  dora_clear_errors(&fabric, DORA_ERROR_RUN);
  if (dora_errors(&fabric) != 0 ||
      (dora_read(&fabric, DORA_REG_STATUS) & DORA_STATUS_ERROR)) {
    dora_print_errors("after clearing ERROR.RUN", dora_errors(&fabric));
    return 1;
  }
  return 0;
}

/* A host access at SPM_ADDR = SPM_WORDS sets ERROR.HOST_RANGE: the write is
 * dropped (the readback of every scratchpad afterwards shows no aliasing),
 * the read returns 0, and SPM_ADDR still advances. */
static int probe_host_range(void)
{
  const uint32_t port = DORA_HYCUBE_ARRAY_K3_LOAD_PORT;
  uint32_t value;
  uint32_t address;
  uint32_t errors;

  dora_write(&fabric, DORA_REG_SPM_ADDR(port), DORA_HYCUBE_ARRAY_SPM_WORDS);
  dora_write(&fabric, DORA_REG_SPM_WDATA(port), K3_PROBE_WORD);
  value = dora_read(&fabric, DORA_REG_SPM_RDATA(port));
  address = dora_read(&fabric, DORA_REG_SPM_ADDR(port));
  errors = dora_errors(&fabric);
  if (value != 0 || address != DORA_HYCUBE_ARRAY_SPM_WORDS + 2u ||
      errors != DORA_ERROR_HOST_RANGE) {
    printf("dora: out-of-range access on port %u read 0x%08x (expected 0), "
        "left SPM_ADDR 0x%x (expected 0x%x)\n", (unsigned)port,
        (unsigned)value, (unsigned)address,
        (unsigned)(DORA_HYCUBE_ARRAY_SPM_WORDS + 2u));
    dora_print_errors("out-of-range access (expected HOST_RANGE only)", errors);
    return 1;
  }
  dora_clear_errors(&fabric, DORA_ERROR_HOST_RANGE);
  if (dora_errors(&fabric) != 0) {
    dora_print_errors("after clearing ERROR.HOST_RANGE", dora_errors(&fabric));
    return 1;
  }
  return 0;
}

static int check_counter(uint32_t offset, const char *name, uint32_t expected)
{
  uint32_t actual = dora_read(&fabric, offset);
  if (actual != expected) {
    printf("dora: %s is %u, expected %u\n", name, (unsigned)actual,
        (unsigned)expected);
    return 1;
  }
  return 0;
}

/* EN_CYCLES, MEM_WRITES and LAST_WRITE_CYCLE against a run's expected ones. */
static int check_counters(const char *run, uint32_t cycles, uint32_t writes,
    uint32_t last)
{
  int status = 0;

  printf("dora: %s: EN_CYCLES %u, MEM_WRITES %u, LAST_WRITE_CYCLE %u\n", run,
      (unsigned)dora_read(&fabric, DORA_REG_EN_CYCLES),
      (unsigned)dora_read(&fabric, DORA_REG_MEM_WRITES),
      (unsigned)dora_read(&fabric, DORA_REG_LAST_WRITE_CYCLE));
  status |= check_counter(DORA_REG_EN_CYCLES, "EN_CYCLES", cycles);
  status |= check_counter(DORA_REG_MEM_WRITES, "MEM_WRITES", writes);
  status |= check_counter(DORA_REG_LAST_WRITE_CYCLE, "LAST_WRITE_CYCLE", last);
  return status;
}

/* The short run (see the file comment). The full run has just been checked,
 * so only the words it wrote differ from the initial scratchpads. Returns 0,
 * or 1 after printing the FAIL line. */
static int short_run(void)
{
  const uint32_t cycles = DORA_HYCUBE_ARRAY_K3_SHORT_RUN_CYCLES;
  uint32_t mismatches;
  uint32_t total = 0;
  int scratchpads = 0;
  int counters;

  if (dora_set_reset(&fabric, 1))
    return fail("resetting the fabric for the short run");
  for (uint32_t index = 0; index < K3_WRITES; ++index) {
    uint32_t port = K3_WRITE(index, W_PORT);
    uint32_t address = K3_WRITE(index, W_ADDRESS);
    if (dora_spm_write(&fabric, port, address,
            &dora_hycube_array_k3_initial[port][address], 1))
      return fail("restoring the scratchpads for the short run");
  }
  if (dora_program(&fabric, dora_hycube_array_k3_image,
          DORA_HYCUBE_ARRAY_SCAN_WORDS))
    return fail("programming the image for the short run");
  if (dora_set_reset(&fabric, 0))
    return fail("releasing the fabric's reset for the short run");
  if (dora_run(&fabric, cycles))
    return fail("the short run");
  counters = check_counters("short run", cycles,
      DORA_HYCUBE_ARRAY_K3_SHORT_MEM_WRITES,
      DORA_HYCUBE_ARRAY_K3_SHORT_LAST_WRITE_CYCLE);
  for (uint32_t port = 0; port < DORA_HYCUBE_ARRAY_MEM_PORTS; ++port) {
    apply_writes(port, cycles);
    if (dora_spm_verify(&fabric, port, short_expected,
            DORA_HYCUBE_ARRAY_SPM_WORDS, K3_REPORT_LIMIT, &mismatches))
      scratchpads = 1;
    total += mismatches;
  }
  printf("dora: short run of %u cycles: %u of %u scratchpad words differ from "
      "the initial ones plus the header's writes of those cycles\n",
      (unsigned)cycles, (unsigned)total,
      (unsigned)(DORA_HYCUBE_ARRAY_MEM_PORTS * DORA_HYCUBE_ARRAY_SPM_WORDS));
  if (scratchpads)
    return fail("the short run's scratchpads differ from the reference model");
  if (counters)
    return fail("the short run's EN_CYCLES, MEM_WRITES or LAST_WRITE_CYCLE "
        "differs from the reference model");
  if (dora_errors(&fabric)) {
    dora_print_errors("after the short run", dora_errors(&fabric));
    return fail("the shell reports an error");
  }
  return 0;
}

int main(void)
{
  uint32_t y[DORA_HYCUBE_ARRAY_K3_N];
  uint32_t mismatches;
  uint32_t total = 0;
  uint32_t errors;
  int counters;
  int scratchpads = 0;
  int sticky = 0;

  printf("DORA K3 mem_axpy on %s (%s) at 0x%lx: %u memory ports x %u words, "
      "%u-word image, %u en_i cycles\n", fabric.name,
      DORA_HYCUBE_ARRAY_TOP_MODULE, (unsigned long)fabric.base,
      (unsigned)fabric.mem_ports, (unsigned)fabric.spm_words,
      (unsigned)fabric.scan_words, (unsigned)DORA_HYCUBE_ARRAY_K3_RUN_CYCLES);

  if (check_header())
    return fail("the header is inconsistent");
  if (dora_check_identity(&fabric))
    return fail("identity registers");
  if (dora_check_reset_state(&fabric))
    return fail("shell state after reset");
  if (probe_run_in_reset())
    return fail("shell refusal of a run in reset");

  /* Every port's scratchpad: the fill pattern with K3's data (x only in the
   * load port at X_BASE, y and its guard words in the store port). */
  for (uint32_t port = 0; port < DORA_HYCUBE_ARRAY_MEM_PORTS; ++port)
    if (dora_spm_write(&fabric, port, 0, dora_hycube_array_k3_initial[port],
            DORA_HYCUBE_ARRAY_SPM_WORDS))
      return fail("loading the scratchpads");
  if (probe_host_range())
    return fail("shell refusal of an out-of-range scratchpad access");
  for (uint32_t port = 0; port < DORA_HYCUBE_ARRAY_MEM_PORTS; ++port)
    if (dora_spm_verify(&fabric, port, dora_hycube_array_k3_initial[port],
            DORA_HYCUBE_ARRAY_SPM_WORDS, K3_REPORT_LIMIT, &mismatches))
      return fail("reading the loaded scratchpads back");
  printf("dora: x[%u] loaded into port %u at word 0x%x (only there); all %u "
      "scratchpads loaded and read back\n", (unsigned)DORA_HYCUBE_ARRAY_K3_N,
      (unsigned)DORA_HYCUBE_ARRAY_K3_LOAD_PORT,
      (unsigned)DORA_HYCUBE_ARRAY_K3_X_BASE,
      (unsigned)DORA_HYCUBE_ARRAY_MEM_PORTS);

  if (dora_program(&fabric, dora_hycube_array_k3_image,
          DORA_HYCUBE_ARRAY_SCAN_WORDS))
    return fail("programming the image");
  printf("dora: programmed %u bits\n", (unsigned)fabric.scan_bits);

  /* Out of reset, then the whole kernel in one burst (a stall is not
   * transparent to the LSU's loads). */
  if (dora_set_reset(&fabric, 0))
    return fail("releasing the fabric's reset");
  if (dora_run(&fabric, DORA_HYCUBE_ARRAY_K3_RUN_CYCLES))
    return fail("the run");

  counters = check_counters("run", DORA_HYCUBE_ARRAY_K3_RUN_CYCLES,
      DORA_HYCUBE_ARRAY_K3_MEM_WRITES, DORA_HYCUBE_ARRAY_K3_LAST_WRITE_CYCLE);
  errors = dora_errors(&fabric);
  if (errors) {
    dora_print_errors("after the run", errors);
    sticky = 1;
  }

  if (dora_spm_read(&fabric, DORA_HYCUBE_ARRAY_K3_STORE_PORT,
          DORA_HYCUBE_ARRAY_K3_Y_BASE, y, DORA_HYCUBE_ARRAY_K3_N))
    return fail("reading y");
  printf("dora: y (port %u at word 0x%x):", (unsigned)DORA_HYCUBE_ARRAY_K3_STORE_PORT,
      (unsigned)DORA_HYCUBE_ARRAY_K3_Y_BASE);
  for (uint32_t index = 0; index < DORA_HYCUBE_ARRAY_K3_N; ++index)
    printf(" %08x", (unsigned)y[index]);
  printf("\n");

  /* Every word of every scratchpad: y and every untouched region. */
  for (uint32_t port = 0; port < DORA_HYCUBE_ARRAY_MEM_PORTS; ++port) {
    if (dora_spm_verify(&fabric, port, dora_hycube_array_k3_expected[port],
            DORA_HYCUBE_ARRAY_SPM_WORDS, K3_REPORT_LIMIT, &mismatches))
      scratchpads = 1;
    total += mismatches;
  }
  printf("dora: %u of %u scratchpad words differ from the header\n",
      (unsigned)total,
      (unsigned)(DORA_HYCUBE_ARRAY_MEM_PORTS * DORA_HYCUBE_ARRAY_SPM_WORDS));
  if (!sticky && dora_errors(&fabric)) {
    dora_print_errors("after the comparison", dora_errors(&fabric));
    sticky = 1;
  }

  if (scratchpads)
    return fail("the scratchpads differ from the reference model");
  if (counters)
    return fail("EN_CYCLES, MEM_WRITES or LAST_WRITE_CYCLE differs from the "
        "reference model");
  if (sticky)
    return fail("the shell reports an error");

  if (short_run())
    return 1;
  printf("DORA K3 mem_axpy: PASS (%u x %u scratchpad words, %u fabric memory "
      "writes, last write in en_i cycle %u; short run of %u cycles: %u writes, "
      "last in cycle %u; as DORA's reference model predicts, which DORA's gate "
      "proves against the standalone SV and Chisel runs)\n",
      (unsigned)DORA_HYCUBE_ARRAY_MEM_PORTS,
      (unsigned)DORA_HYCUBE_ARRAY_SPM_WORDS,
      (unsigned)DORA_HYCUBE_ARRAY_K3_MEM_WRITES,
      (unsigned)DORA_HYCUBE_ARRAY_K3_LAST_WRITE_CYCLE,
      (unsigned)DORA_HYCUBE_ARRAY_K3_SHORT_RUN_CYCLES,
      (unsigned)DORA_HYCUBE_ARRAY_K3_SHORT_MEM_WRITES,
      (unsigned)DORA_HYCUBE_ARRAY_K3_SHORT_LAST_WRITE_CYCLE);
  return 0;
}
