/* s2chitni & Claude (AI-generated) */
/*
 * Bare-metal runtime for a DORA fabric behind DORA's TileLink register shell;
 * see dora-runtime.h. Every register offset and field below is a symbol of
 * the DORA-generated header named by DORA_FABRIC_HEADER.
 */

#include <stddef.h>
#include <stdint.h>
#include <stdio.h>

#ifndef DORA_FABRIC_HEADER
#error "define DORA_FABRIC_HEADER as the DORA-generated header, e.g. -DDORA_FABRIC_HEADER=\"dora_hycube_array.h\""
#endif
#include DORA_FABRIC_HEADER
#include "dora-runtime.h"

#if !defined(DORA_SHELL_ABI_VERSION) || DORA_SHELL_ABI_VERSION != 1u
#error "dora-runtime implements DORA shell ABI version 1; regenerate the header or update the runtime"
#endif

/* Polls of a status register before a wait counts as a timeout. The longest
 * wait (FINISH: drain and settle) is under a hundred cycles, and 1e5 polls of
 * a few dozen bus cycles each stay well inside the simulator's
 * TIMEOUT_CYCLES, so a hung shell ends in a FAIL line, not a timeout. */
#ifndef DORA_POLL_LIMIT
#define DORA_POLL_LIMIT UINT32_C(100000)
#endif

#ifdef DORA_RUNTIME_MMIO_HOOKS
/* A host-side test supplies the bus (resources/dora/mock-shell.c). */
uint32_t dora_mmio_read32(uintptr_t address);
void dora_mmio_write32(uintptr_t address, uint32_t value);
#else
#include "mmio.h"

static uint32_t dora_mmio_read32(uintptr_t address)
{
  uint32_t value;
  __asm__ volatile ("fence iorw, iorw" ::: "memory");
  value = reg_read32(address);
  __asm__ volatile ("fence iorw, iorw" ::: "memory");
  return value;
}

static void dora_mmio_write32(uintptr_t address, uint32_t value)
{
  reg_write32(address, value);
  __asm__ volatile ("fence iorw, iorw" ::: "memory");
}
#endif

#define DORA_SCAN_ERRORS \
  (DORA_ERROR_SCAN_DATA | DORA_ERROR_SCAN_CMD | DORA_ERROR_SCAN_SHORT)
#define DORA_HOST_ERRORS (DORA_ERROR_HOST_BUSY | DORA_ERROR_HOST_RANGE)

uint32_t dora_read(const struct dora_fabric *fabric, uint32_t offset)
{
  return dora_mmio_read32(fabric->base + (uintptr_t)offset);
}

void dora_write(const struct dora_fabric *fabric, uint32_t offset,
    uint32_t value)
{
  dora_mmio_write32(fabric->base + (uintptr_t)offset, value);
}

uint32_t dora_errors(const struct dora_fabric *fabric)
{
  return dora_read(fabric, DORA_REG_ERROR);
}

void dora_clear_errors(const struct dora_fabric *fabric, uint32_t mask)
{
  dora_write(fabric, DORA_REG_ERROR, mask);
}

void dora_print_errors(const char *what, uint32_t errors)
{
  static const struct {
    uint32_t mask;
    const char *name;
  } names[] = {
    { DORA_ERROR_SCAN_DATA, "SCAN_DATA" },
    { DORA_ERROR_SCAN_CMD, "SCAN_CMD" },
    { DORA_ERROR_SCAN_SHORT, "SCAN_SHORT" },
    { DORA_ERROR_RUN, "RUN" },
    { DORA_ERROR_HOST_BUSY, "HOST_BUSY" },
    { DORA_ERROR_HOST_RANGE, "HOST_RANGE" },
    { DORA_ERROR_FABRIC_RANGE, "FABRIC_RANGE" },
  };
  uint32_t known = 0;

  printf("dora: %s: ERROR = 0x%08x", what, (unsigned)errors);
  for (size_t index = 0; index < sizeof(names) / sizeof(names[0]); ++index) {
    known |= names[index].mask;
    if (errors & names[index].mask)
      printf(" %s", names[index].name);
  }
  if (errors & ~known)
    printf(" (unknown bits 0x%08x)", (unsigned)(errors & ~known));
  printf("\n");
}

static void print_words(const char *label, const uint32_t *words,
    uint32_t count)
{
  printf("%s", label);
  for (uint32_t index = 0; index < count; ++index)
    printf("%08x", (unsigned)words[index]);
  printf("\n");
}

static int expect_register(const struct dora_fabric *fabric, uint32_t offset,
    const char *name, uint32_t expected)
{
  uint32_t actual = dora_read(fabric, offset);
  if (actual != expected) {
    printf("dora: %s %s reads 0x%08x, expected 0x%08x\n", fabric->name, name,
        (unsigned)actual, (unsigned)expected);
    return 1;
  }
  return 0;
}

static int read_digest(const struct dora_fabric *fabric, const char *name,
    uint32_t first, uint32_t stride, const uint32_t *expected, uint32_t count,
    uint32_t *actual)
{
  int status = 0;
  for (uint32_t index = 0; index < count; ++index) {
    actual[index] = dora_read(fabric, first + stride * index);
    if (actual[index] != expected[index]) {
      printf("dora: %s %s[%u] reads 0x%08x, expected 0x%08x\n", fabric->name,
          name, (unsigned)index, (unsigned)actual[index],
          (unsigned)expected[index]);
      status = 1;
    }
  }
  return status;
}

int dora_check_identity(const struct dora_fabric *fabric)
{
  uint32_t words[16];
  int status = 0;

  if (fabric->hw_digest_words > 16 || fabric->layout_hash_words > 16) {
    printf("dora: %s descriptor has too many digest words\n", fabric->name);
    return 1;
  }
  if (fabric->abi_version != DORA_SHELL_ABI_VERSION ||
      fabric->id != DORA_SHELL_ID) {
    printf("dora: %s descriptor is not for shell ABI version %u\n",
        fabric->name, (unsigned)DORA_SHELL_ABI_VERSION);
    return 1;
  }

  /* A wrong ID or ABI version makes every other register meaningless. */
  if (expect_register(fabric, DORA_REG_ID, "ID", fabric->id) ||
      expect_register(fabric, DORA_REG_ABI_VERSION, "ABI_VERSION",
          fabric->abi_version))
    return 1;

  status |= read_digest(fabric, "HW_DIGEST", DORA_REG_HW_DIGEST(0),
      DORA_REG_HW_DIGEST_STRIDE, fabric->hw_digest, fabric->hw_digest_words,
      words);
  print_words("dora: hardware digest sha256:", words, fabric->hw_digest_words);
  status |= read_digest(fabric, "LAYOUT_HASH", DORA_REG_LAYOUT_HASH(0),
      DORA_REG_LAYOUT_HASH_STRIDE, fabric->layout_hash,
      fabric->layout_hash_words, words);
  print_words("dora: layout hash ", words, fabric->layout_hash_words);

  status |= expect_register(fabric, DORA_REG_SCAN_BITS, "SCAN_BITS",
      fabric->scan_bits);
  status |= expect_register(fabric, DORA_REG_CHAIN_WIDTH, "CHAIN_WIDTH",
      fabric->chain_width);
  status |= expect_register(fabric, DORA_REG_MEM_PORTS, "MEM_PORTS",
      fabric->mem_ports);
  status |= expect_register(fabric, DORA_REG_SPM_WORDS, "SPM_WORDS",
      fabric->spm_words);
  if (status)
    printf("dora: %s at 0x%lx is not the fabric of this header\n",
        fabric->name, (unsigned long)fabric->base);
  return status;
}

int dora_check_reset_state(const struct dora_fabric *fabric)
{
  int status = 0;

  status |= expect_register(fabric, DORA_REG_CTRL, "CTRL",
      DORA_REG_CTRL_RESET);
  status |= expect_register(fabric, DORA_REG_STATUS, "STATUS",
      DORA_STATUS_RESET);
  status |= expect_register(fabric, DORA_REG_SCAN_STATUS, "SCAN_STATUS", 0);
  status |= expect_register(fabric, DORA_REG_SCAN_SHIFTED, "SCAN_SHIFTED", 0);
  status |= expect_register(fabric, DORA_REG_EN_CYCLES, "EN_CYCLES", 0);
  status |= expect_register(fabric, DORA_REG_MEM_WRITES, "MEM_WRITES", 0);
  status |= expect_register(fabric, DORA_REG_LAST_WRITE_CYCLE,
      "LAST_WRITE_CYCLE", 0);
  status |= expect_register(fabric, DORA_REG_ERROR, "ERROR", 0);
  for (uint32_t port = 0; port < fabric->mem_ports; ++port) {
    uint32_t address = dora_read(fabric, DORA_REG_SPM_ADDR(port));
    if (address != DORA_REG_SPM_ADDR_RESET) {
      printf("dora: %s SPM_ADDR[%u] reads 0x%08x, expected 0x%08x\n",
          fabric->name, (unsigned)port, (unsigned)address,
          (unsigned)DORA_REG_SPM_ADDR_RESET);
      status = 1;
    }
  }
  return status;
}

static int spm_range(const struct dora_fabric *fabric, const char *what,
    uint32_t port, uint32_t address, uint32_t count)
{
  if (port >= fabric->mem_ports || count > fabric->spm_words ||
      address > fabric->spm_words - count) {
    printf("dora: %s: port %u words [0x%x, 0x%x) are outside %u ports x %u "
        "words\n", what, (unsigned)port, (unsigned)address,
        (unsigned)(address + count), (unsigned)fabric->mem_ports,
        (unsigned)fabric->spm_words);
    return 1;
  }
  if (dora_read(fabric, DORA_REG_STATUS) & DORA_STATUS_RUNNING) {
    printf("dora: %s: the fabric is running\n", what);
    return 1;
  }
  return 0;
}

static int spm_finish(const struct dora_fabric *fabric, const char *what,
    uint32_t port, uint32_t end)
{
  uint32_t address = dora_read(fabric, DORA_REG_SPM_ADDR(port));
  uint32_t errors = dora_errors(fabric) & DORA_HOST_ERRORS;

  if (address != end) {
    printf("dora: %s: port %u SPM_ADDR is 0x%x, expected 0x%x\n", what,
        (unsigned)port, (unsigned)address, (unsigned)end);
    return 1;
  }
  if (errors) {
    dora_print_errors(what, errors);
    return 1;
  }
  return 0;
}

int dora_spm_write(const struct dora_fabric *fabric, uint32_t port,
    uint32_t address, const uint32_t *words, uint32_t count)
{
  if (spm_range(fabric, "scratchpad write", port, address, count))
    return 1;
  dora_write(fabric, DORA_REG_SPM_ADDR(port), address);
  for (uint32_t index = 0; index < count; ++index)
    dora_write(fabric, DORA_REG_SPM_WDATA(port), words[index]);
  return spm_finish(fabric, "scratchpad write", port, address + count);
}

int dora_spm_read(const struct dora_fabric *fabric, uint32_t port,
    uint32_t address, uint32_t *words, uint32_t count)
{
  if (spm_range(fabric, "scratchpad read", port, address, count))
    return 1;
  dora_write(fabric, DORA_REG_SPM_ADDR(port), address);
  for (uint32_t index = 0; index < count; ++index)
    words[index] = dora_read(fabric, DORA_REG_SPM_RDATA(port));
  return spm_finish(fabric, "scratchpad read", port, address + count);
}

int dora_spm_verify(const struct dora_fabric *fabric, uint32_t port,
    const uint32_t *expected, uint32_t count, uint32_t report_limit,
    uint32_t *mismatches)
{
  uint32_t wrong = 0;

  *mismatches = 0;
  if (spm_range(fabric, "scratchpad compare", port, 0, count))
    return 1;
  dora_write(fabric, DORA_REG_SPM_ADDR(port), 0);
  for (uint32_t index = 0; index < count; ++index) {
    uint32_t actual = dora_read(fabric, DORA_REG_SPM_RDATA(port));
    if (actual != expected[index]) {
      if (wrong < report_limit)
        printf("dora: port %u word 0x%03x is 0x%08x, expected 0x%08x\n",
            (unsigned)port, (unsigned)index, (unsigned)actual,
            (unsigned)expected[index]);
      ++wrong;
    }
  }
  *mismatches = wrong;
  if (spm_finish(fabric, "scratchpad compare", port, count))
    return 1;
  if (wrong) {
    printf("dora: port %u: %u of %u words differ\n", (unsigned)port,
        (unsigned)wrong, (unsigned)count);
    return 1;
  }
  return 0;
}

/* Poll SCAN_STATUS until (status & mask) == value. */
static int wait_scan(const struct dora_fabric *fabric, uint32_t mask,
    uint32_t value, const char *what, uint32_t *status)
{
  for (uint32_t poll = 0; poll < DORA_POLL_LIMIT; ++poll) {
    *status = dora_read(fabric, DORA_REG_SCAN_STATUS);
    if ((*status & mask) == value)
      return 0;
  }
  printf("dora: timed out waiting for %s (SCAN_STATUS 0x%08x)\n", what,
      (unsigned)*status);
  return 1;
}

static int scan_errors(const struct dora_fabric *fabric, const char *what)
{
  uint32_t errors = dora_errors(fabric) & DORA_SCAN_ERRORS;
  if (errors) {
    dora_print_errors(what, errors);
    return 1;
  }
  return 0;
}

int dora_program(const struct dora_fabric *fabric, const uint32_t *image,
    uint32_t words)
{
  const uint32_t all = DORA_SCAN_STATUS_BUSY | DORA_SCAN_STATUS_LOADING |
      DORA_SCAN_STATUS_DONE;
  uint32_t status;
  uint32_t shifted;

  if (image == NULL || words != fabric->scan_words) {
    printf("dora: the image has %u SCAN_DATA words, %s takes %u\n",
        (unsigned)words, fabric->name, (unsigned)fabric->scan_words);
    return 1;
  }
  if (dora_read(fabric, DORA_REG_STATUS) & DORA_STATUS_RUNNING) {
    printf("dora: cannot program %s while it runs\n", fabric->name);
    return 1;
  }
  if (scan_errors(fabric, "before programming"))
    return 1;

  /* The reset pulse, then an open session: LOADING, nothing shifted. */
  dora_write(fabric, DORA_REG_SCAN_CTRL, DORA_SCAN_CTRL_PROG_RST);
  if (wait_scan(fabric, DORA_SCAN_STATUS_BUSY, 0, "the PROG_RST pulse",
          &status))
    return 1;
  if ((status & all) != DORA_SCAN_STATUS_LOADING ||
      dora_read(fabric, DORA_REG_SCAN_SHIFTED) != 0) {
    printf("dora: after PROG_RST SCAN_STATUS is 0x%08x (expected LOADING "
        "only) and SCAN_SHIFTED %u\n", (unsigned)status,
        (unsigned)dora_read(fabric, DORA_REG_SCAN_SHIFTED));
    return 1;
  }

  /* SCAN_DATA writes wait while a word shifts (the bus is back-pressured). */
  for (uint32_t index = 0; index < words; ++index)
    dora_write(fabric, DORA_REG_SCAN_DATA, image[index]);
  if (wait_scan(fabric, DORA_SCAN_STATUS_BUSY, 0, "the last SCAN_DATA word",
          &status) || scan_errors(fabric, "shifting the image"))
    return 1;
  shifted = dora_read(fabric, DORA_REG_SCAN_SHIFTED);
  if (shifted != fabric->scan_bits) {
    printf("dora: SCAN_SHIFTED is %u after the image, expected %u\n",
        (unsigned)shifted, (unsigned)fabric->scan_bits);
    return 1;
  }

  /* The drain, prog_done_i, the settle; then the session closes. */
  dora_write(fabric, DORA_REG_SCAN_CTRL, DORA_SCAN_CTRL_FINISH);
  if (wait_scan(fabric, all, DORA_SCAN_STATUS_DONE, "SCAN_STATUS.DONE",
          &status) || scan_errors(fabric, "finishing the image"))
    return 1;
  if (dora_read(fabric, DORA_REG_SCAN_SHIFTED) != fabric->scan_bits) {
    printf("dora: SCAN_SHIFTED changed during FINISH\n");
    return 1;
  }
  return 0;
}

int dora_set_reset(const struct dora_fabric *fabric, int asserted)
{
  uint32_t level = asserted ? DORA_CTRL_RESET : 0;
  uint32_t status;

  dora_write(fabric, DORA_REG_CTRL,
      (dora_read(fabric, DORA_REG_CTRL) & ~DORA_CTRL_RESET_MASK) | level);
  status = dora_read(fabric, DORA_REG_STATUS);
  if ((dora_read(fabric, DORA_REG_CTRL) & DORA_CTRL_RESET_MASK) != level ||
      !(status & DORA_STATUS_RESET) != !asserted) {
    printf("dora: CTRL.RESET=%u did not take effect (STATUS 0x%08x)\n",
        (unsigned)(asserted != 0), (unsigned)status);
    return 1;
  }
  return 0;
}

int dora_run(const struct dora_fabric *fabric, uint32_t cycles)
{
  uint32_t status = dora_read(fabric, DORA_REG_STATUS);
  uint32_t start;
  uint32_t done;

  if (cycles == 0)
    return 0;
  if (status & (DORA_STATUS_RUNNING | DORA_STATUS_RESET)) {
    printf("dora: cannot run %s: STATUS 0x%08x (running or in reset)\n",
        fabric->name, (unsigned)status);
    return 1;
  }
  if (dora_errors(fabric) & DORA_ERROR_RUN) {
    printf("dora: ERROR.RUN is already set; clear it before a run\n");
    return 1;
  }

  start = dora_read(fabric, DORA_REG_EN_CYCLES);
  dora_write(fabric, DORA_REG_RUN_CYCLES, cycles);
  /* The run is over when RUNNING is clear and EN_CYCLES advanced by cycles. */
  for (uint32_t poll = 0; poll < DORA_POLL_LIMIT; ++poll) {
    status = dora_read(fabric, DORA_REG_STATUS);
    if (status & DORA_STATUS_RUNNING)
      continue;
    done = dora_read(fabric, DORA_REG_EN_CYCLES) - start;
    if (dora_errors(fabric) & DORA_ERROR_RUN) {
      dora_print_errors("RUN_CYCLES", dora_errors(fabric));
      return 1;
    }
    if (done == cycles)
      return 0;
    if (done > cycles) {
      printf("dora: en_i was high for %u cycles, expected %u\n",
          (unsigned)done, (unsigned)cycles);
      return 1;
    }
  }
  printf("dora: timed out waiting for a %u-cycle run (STATUS 0x%08x, "
      "EN_CYCLES advanced by %u)\n", (unsigned)cycles, (unsigned)status,
      (unsigned)(dora_read(fabric, DORA_REG_EN_CYCLES) - start));
  return 1;
}
