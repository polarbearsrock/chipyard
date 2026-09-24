/* s2chitni & Claude (AI-generated) */
/*
 * A host-side model of DORA's register shell (shell ABI version 1) for
 * testing tests/dora-static-hycube.c and tests/dora-runtime.c before, or
 * without, a Chipyard SoC. `make -C generators/chipyard/src/test/resources/dora
 * test-software` builds the two with -DDORA_RUNTIME_MMIO_HOOKS and this file
 * (dora_soc.py mock-test) and runs them once faithfully (the program must
 * print PASS) and once per fault (it must print FAIL).
 *
 * The model follows the ABI in the header (DORA docs/chisel_pilot.md, "SoC
 * shell ABI"): identity registers, the scan programmer (no BUSY time: a write
 * completes at once), compute control and counters, sticky rw1c errors, and
 * one scratchpad per memory port behind SPM_ADDR/SPM_WDATA/SPM_RDATA. The
 * fabric is K3 only: a run applies the header's reference writes
 * (dora_hycube_array_k3_writes) in their en_i cycles, counted from the last
 * CTRL.RESET, but only when the image shifted in equals the header's K3 image
 * and prog_done_i is high, and each y store recomputes a * x + b from the x
 * the model's load port holds. So the program passes only if it loads x,
 * programs the right image, releases the reset and runs the right number of
 * cycles. An access the ABI does not define (an unmapped offset, a
 * read of a write-only register, a write of a read-only one, a misaligned
 * address) stops the model with exit status 3, as it is a program bug.
 *
 * DORA_MOCK_FAULT names one injected fault (see faults[] below).
 */

#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "dora_hycube_array.h"

#define PORTS DORA_HYCUBE_ARRAY_MEM_PORTS
#define WORDS DORA_HYCUBE_ARRAY_SPM_WORDS
#define SCAN_WORDS DORA_HYCUBE_ARRAY_SCAN_WORDS
#define SCAN_BITS DORA_HYCUBE_ARRAY_SCAN_BITS

/* The header's writes table: {en_i cycle, port, address, data} rows. */
#define K3_WRITES DORA_HYCUBE_ARRAY_K3_MEM_WRITES
#define K3_CYCLE(index) (dora_hycube_array_k3_writes[index][0])
#define K3_PORT(index) (dora_hycube_array_k3_writes[index][1])
#define K3_ADDRESS(index) (dora_hycube_array_k3_writes[index][2])
#define K3_DATA(index) (dora_hycube_array_k3_writes[index][3])

uint32_t dora_mmio_read32(uintptr_t address);
void dora_mmio_write32(uintptr_t address, uint32_t value);

static const char *const faults[] = {
  "id",            /* ID reads another value */
  "digest",        /* HW_DIGEST[3] has one bit flipped */
  "layout",        /* LAYOUT_HASH[7] has one bit flipped */
  "spm-words",     /* SPM_WORDS reads half the depth */
  "reset-state",   /* CTRL comes out of the SoC reset as 0 */
  "run-in-reset",  /* RUN_CYCLES while CTRL.RESET=1 is not refused */
  "alias",         /* an out-of-range host write lands at addr % words */
  "range-read",    /* an out-of-range host read returns a word, not 0 */
  "no-advance",    /* SPM_RDATA does not advance SPM_ADDR */
  "scan-bit",      /* one image bit is flipped on its way in */
  "short-shift",   /* the last SCAN_DATA word shifts one bit too few */
  "done-stuck",    /* FINISH never raises DONE */
  "stuck-running", /* STATUS.RUNNING never clears */
  "extra-cycle",   /* a run lasts one cycle longer */
  "spm-bit",       /* one untouched word of port 2 changes during the run */
  "drop-write",    /* the last fabric write is lost (y is still right) */
  "late-write",    /* LAST_WRITE_CYCLE is one too high */
  "fabric-range",  /* the run sets ERROR.FABRIC_RANGE */
  "y-value",       /* the fabric stores a * x + b + 1 for y[5] */
  "first-store",   /* a registered scratchpad read: each y[i]'s first store
                    * uses x[i - 1] (the full run's results do not change) */
  "load-port",     /* the fabric loads x from the port after the load port */
};

static struct {
  int ready;
  const char *fault;
  uint32_t ctrl;
  int session;
  int done;
  uint32_t shifted;
  uint32_t image[SCAN_WORDS];
  int programmed;
  int stuck;
  uint32_t en_cycles;
  uint32_t mem_writes;
  uint32_t last_write;
  uint32_t error;
  uint32_t spm_addr[PORTS];
  uint32_t spm[PORTS][WORDS];
  unsigned long reads;
  unsigned long writes;
} m;

static int fault(const char *name)
{
  return strcmp(m.fault, name) == 0;
}

static void report(void)
{
  fprintf(stderr, "mock-shell: fault '%s', %lu register reads, %lu register "
      "writes\n", m.fault, m.reads, m.writes);
}

static void init(void)
{
  const char *name = getenv("DORA_MOCK_FAULT");

  if (m.ready)
    return;
  m.ready = 1;
  m.fault = name ? name : "";
  if (m.fault[0]) {
    size_t index = 0;
    while (index < sizeof(faults) / sizeof(faults[0]) &&
        strcmp(faults[index], m.fault) != 0)
      ++index;
    if (index == sizeof(faults) / sizeof(faults[0])) {
      fprintf(stderr, "mock-shell: unknown DORA_MOCK_FAULT '%s'\n", m.fault);
      exit(2);
    }
  }
  m.ctrl = fault("reset-state") ? 0u : DORA_REG_CTRL_RESET;
  for (uint32_t port = 0; port < PORTS; ++port) {
    m.spm_addr[port] = DORA_REG_SPM_ADDR_RESET;
    /* Uninitialised memory: whatever it holds is not the fill pattern. */
    for (uint32_t word = 0; word < WORDS; ++word)
      m.spm[port][word] = UINT32_C(0x5a5a0000) ^ (port << 12) ^ (word * 7u);
  }
  atexit(report);
}

static void bug(const char *what, uintptr_t address)
{
  fprintf(stderr, "mock-shell: program bug: %s at 0x%lx\n", what,
      (unsigned long)address);
  exit(3);
}

static void clear_counters(void)
{
  m.en_cycles = 0;
  m.mem_writes = 0;
  m.last_write = 0;
}

/* Whether a later write of the table stores to the same port and address. */
static int rewritten_later(size_t index)
{
  for (size_t later = index + 1; later < K3_WRITES; ++later)
    if (K3_PORT(later) == K3_PORT(index) && K3_ADDRESS(later) == K3_ADDRESS(index))
      return 1;
  return 0;
}

/* One en_i-high cycle: the reference writes of en_i cycle m.en_cycles. */
static void fabric_cycle(void)
{
  for (size_t index = 0; index < K3_WRITES; ++index) {
    uint32_t port = K3_PORT(index);
    uint32_t address = K3_ADDRESS(index);
    uint32_t data = K3_DATA(index);
    if (K3_CYCLE(index) != m.en_cycles)
      continue;
    if (fault("drop-write") && index == K3_WRITES - 1)
      continue;
    ++m.mem_writes;
    m.last_write = m.en_cycles + (fault("late-write") ? 1u : 0u);
    if (address >= WORDS) {
      m.error |= DORA_ERROR_FABRIC_RANGE;
      continue;
    }
    if (port == DORA_HYCUBE_ARRAY_K3_STORE_PORT &&
        address >= DORA_HYCUBE_ARRAY_K3_Y_BASE &&
        address < DORA_HYCUBE_ARRAY_K3_Y_BASE + DORA_HYCUBE_ARRAY_K3_N) {
      uint32_t element = address - DORA_HYCUBE_ARRAY_K3_Y_BASE;
      uint32_t source = DORA_HYCUBE_ARRAY_K3_LOAD_PORT;
      uint32_t x_address = DORA_HYCUBE_ARRAY_K3_X_BASE + element;
      if (fault("load-port"))
        source = (source + 1u) % PORTS;
      if (fault("first-store") && rewritten_later(index))
        x_address -= 1u; /* the word loaded a cycle earlier */
      data = DORA_HYCUBE_ARRAY_K3_A * m.spm[source][x_address] +
          DORA_HYCUBE_ARRAY_K3_B;
      if (fault("y-value") && element == 5)
        data += 1u;
    }
    m.spm[port][address] = data;
  }
  ++m.en_cycles;
}

static void run(uint32_t cycles)
{
  if (cycles == 0)
    return;
  if (m.stuck || (m.ctrl & DORA_CTRL_RESET && !fault("run-in-reset"))) {
    m.error |= DORA_ERROR_RUN;
    return;
  }
  if (m.ctrl & DORA_CTRL_RESET)
    return; /* the fault: accepted, but the fabric is held in reset */
  if (fault("extra-cycle"))
    ++cycles;
  for (uint32_t cycle = 0; cycle < cycles; ++cycle) {
    if (m.programmed && m.done)
      fabric_cycle();
    else
      ++m.en_cycles;
  }
  if (fault("spm-bit"))
    m.spm[2 % PORTS][0x155 % WORDS] ^= UINT32_C(0x10);
  if (fault("fabric-range"))
    m.error |= DORA_ERROR_FABRIC_RANGE;
  if (fault("stuck-running"))
    m.stuck = 1;
}

static void scan_ctrl(uint32_t value)
{
  uint32_t both = DORA_SCAN_CTRL_PROG_RST | DORA_SCAN_CTRL_FINISH;

  if ((value & both) == both) {
    m.error |= DORA_ERROR_SCAN_CMD;
  } else if (value & DORA_SCAN_CTRL_PROG_RST) {
    m.done = 0;
    m.programmed = 0;
    m.shifted = 0;
    m.session = 1;
    memset(m.image, 0, sizeof(m.image));
  } else if (value & DORA_SCAN_CTRL_FINISH) {
    if (!m.session) {
      m.error |= DORA_ERROR_SCAN_CMD;
    } else if (m.shifted < SCAN_BITS) {
      m.error |= DORA_ERROR_SCAN_SHORT;
    } else {
      m.session = 0;
      m.done = !fault("done-stuck");
      m.programmed = memcmp(m.image, dora_hycube_array_k3_image,
          sizeof(m.image)) == 0;
    }
  }
}

static void scan_data(uint32_t value)
{
  uint32_t count;
  uint32_t index;

  if (!m.session || m.shifted >= SCAN_BITS) {
    m.error |= DORA_ERROR_SCAN_DATA;
    return;
  }
  count = SCAN_BITS - m.shifted < 32u ? SCAN_BITS - m.shifted : 32u;
  index = m.shifted / 32u;
  if (fault("short-shift") && index == SCAN_WORDS - 1)
    count -= 1u;
  if (count < 32u)
    value &= (UINT32_C(1) << count) - 1u;
  if (fault("scan-bit") && index == 17)
    value ^= UINT32_C(1) << 5;
  m.image[index] = value;
  m.shifted += count;
}

static int array_index(uint32_t offset, uint32_t first, uint32_t stride,
    uint32_t count, uint32_t *index)
{
  if (offset < first || (offset - first) % stride != 0 ||
      (offset - first) / stride >= count)
    return 0;
  *index = (offset - first) / stride;
  return 1;
}

static uint32_t spm_read(uint32_t port)
{
  uint32_t address = m.spm_addr[port];
  uint32_t value = 0;

  if (m.stuck) {
    m.error |= DORA_ERROR_HOST_BUSY;
    return 0;
  }
  if (address >= WORDS) {
    m.error |= DORA_ERROR_HOST_RANGE;
    if (fault("range-read"))
      value = m.spm[port][address % WORDS];
  } else {
    value = m.spm[port][address];
  }
  if (!fault("no-advance"))
    m.spm_addr[port] = address + 1u;
  return value;
}

static void spm_write(uint32_t port, uint32_t value)
{
  uint32_t address = m.spm_addr[port];

  if (m.stuck) {
    m.error |= DORA_ERROR_HOST_BUSY;
    return;
  }
  if (address >= WORDS) {
    m.error |= DORA_ERROR_HOST_RANGE;
    if (fault("alias"))
      m.spm[port][address % WORDS] = value;
  } else {
    m.spm[port][address] = value;
  }
  m.spm_addr[port] = address + 1u;
}

uint32_t dora_mmio_read32(uintptr_t address)
{
  uint32_t offset;
  uint32_t index;

  init();
  ++m.reads;
  if (address < DORA_HYCUBE_ARRAY_BASE ||
      address >= DORA_HYCUBE_ARRAY_BASE + DORA_SHELL_SIZE || address % 4u)
    bug("read outside the shell or misaligned", address);
  offset = (uint32_t)(address - DORA_HYCUBE_ARRAY_BASE);

  switch (offset) {
  case DORA_REG_ID:
    return DORA_HYCUBE_ARRAY_ID ^ (fault("id") ? 1u : 0u);
  case DORA_REG_ABI_VERSION:
    return DORA_HYCUBE_ARRAY_ABI_VERSION;
  case DORA_REG_SCAN_BITS:
    return SCAN_BITS;
  case DORA_REG_CHAIN_WIDTH:
    return DORA_HYCUBE_ARRAY_CHAIN_WIDTH;
  case DORA_REG_MEM_PORTS:
    return PORTS;
  case DORA_REG_SPM_WORDS:
    return fault("spm-words") ? WORDS / 2u : WORDS;
  case DORA_REG_SCAN_STATUS:
    return (m.session ? DORA_SCAN_STATUS_LOADING : 0u) |
        (m.done ? DORA_SCAN_STATUS_DONE : 0u);
  case DORA_REG_SCAN_SHIFTED:
    return m.shifted;
  case DORA_REG_CTRL:
    return m.ctrl;
  case DORA_REG_STATUS:
    return (m.stuck ? DORA_STATUS_RUNNING : 0u) |
        ((m.ctrl & DORA_CTRL_RESET) ? DORA_STATUS_RESET : 0u) |
        (m.error ? DORA_STATUS_ERROR : 0u);
  case DORA_REG_EN_CYCLES:
    return m.en_cycles;
  case DORA_REG_MEM_WRITES:
    return m.mem_writes;
  case DORA_REG_LAST_WRITE_CYCLE:
    return m.last_write;
  case DORA_REG_ERROR:
    return m.error;
  case DORA_REG_SCAN_CTRL:
  case DORA_REG_SCAN_DATA:
  case DORA_REG_RUN_CYCLES:
    bug("read of a write-only register", address);
    return 0;
  default:
    break;
  }
  if (array_index(offset, DORA_REG_HW_DIGEST(0), DORA_REG_HW_DIGEST_STRIDE,
          8, &index))
    return dora_hycube_array_hw_digest[index] ^
        (fault("digest") && index == 3 ? 1u : 0u);
  if (array_index(offset, DORA_REG_LAYOUT_HASH(0),
          DORA_REG_LAYOUT_HASH_STRIDE, 8, &index))
    return dora_hycube_array_layout_hash[index] ^
        (fault("layout") && index == 7 ? 0x100u : 0u);
  if (array_index(offset, DORA_REG_SPM_ADDR(0), DORA_REG_SPM_ADDR_STRIDE,
          PORTS, &index))
    return m.spm_addr[index];
  if (array_index(offset, DORA_REG_SPM_RDATA(0), DORA_REG_SPM_RDATA_STRIDE,
          PORTS, &index))
    return spm_read(index);
  if (array_index(offset, DORA_REG_SPM_WDATA(0), DORA_REG_SPM_WDATA_STRIDE,
          PORTS, &index))
    bug("read of a write-only register", address);
  bug("read of an unmapped offset", address);
  return 0;
}

void dora_mmio_write32(uintptr_t address, uint32_t value)
{
  uint32_t offset;
  uint32_t index;

  init();
  ++m.writes;
  if (address < DORA_HYCUBE_ARRAY_BASE ||
      address >= DORA_HYCUBE_ARRAY_BASE + DORA_SHELL_SIZE || address % 4u)
    bug("write outside the shell or misaligned", address);
  offset = (uint32_t)(address - DORA_HYCUBE_ARRAY_BASE);

  switch (offset) {
  case DORA_REG_SCAN_CTRL:
    scan_ctrl(value);
    return;
  case DORA_REG_SCAN_DATA:
    scan_data(value);
    return;
  case DORA_REG_CTRL:
    m.ctrl = value & DORA_CTRL_RESET_MASK;
    if (m.ctrl & DORA_CTRL_RESET)
      clear_counters();
    return;
  case DORA_REG_RUN_CYCLES:
    run(value);
    return;
  case DORA_REG_ERROR:
    m.error &= ~value;
    return;
  default:
    break;
  }
  if (array_index(offset, DORA_REG_SPM_ADDR(0), DORA_REG_SPM_ADDR_STRIDE,
          PORTS, &index)) {
    m.spm_addr[index] = value;
    return;
  }
  if (array_index(offset, DORA_REG_SPM_WDATA(0), DORA_REG_SPM_WDATA_STRIDE,
          PORTS, &index)) {
    spm_write(index, value);
    return;
  }
  bug("write of a read-only register or an unmapped offset", address);
}
