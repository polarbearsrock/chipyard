/* s2chitni & Claude (AI-generated) */
#ifndef CHIPYARD_DORA_RUNTIME_H
#define CHIPYARD_DORA_RUNTIME_H

/*
 * Bare-metal runtime for a DORA fabric behind DORA's TileLink register shell
 * (DoraFabricTL, shell ABI version 1; see DORA's docs/chisel_pilot.md, "SoC
 * shell ABI"). Generalised from rta-v4-test-runtime.
 *
 * Nothing here retypes an offset, a field or an identity value: they all come
 * from the C header DORA writes for the fabric (dora.hdl.cheader,
 * <DORA_OUT>/sw/dora_<top>.h). The runtime uses only the header's generic
 * part (DORA_REG_*, DORA_<REG>_<FIELD>, DORA_SHELL_*), which is the same in
 * every header of one ABI version; dora-runtime.c includes the header named
 * by DORA_FABRIC_HEADER for it. The fabric's own values reach the runtime
 * through struct dora_fabric, which DORA_FABRIC_DESCRIPTOR fills from the
 * header's DORA_<TOP>_* and dora_<top>_* symbols:
 *
 *   #include "dora_hycube_array.h"
 *   #include "dora-runtime.h"
 *   static const struct dora_fabric fabric =
 *       DORA_FABRIC_DESCRIPTOR(HYCUBE_ARRAY, hycube_array);
 *
 * Every function that returns int returns 0 on success and 1 on failure,
 * after printing why (lines start with "dora:").
 */

#include <stddef.h>
#include <stdint.h>

struct dora_fabric {
  const char *name;            /* top module, without the SoC module prefix */
  uintptr_t base;              /* DORA_<TOP>_BASE */
  uint32_t id;                 /* DORA_<TOP>_ID: what ID reads */
  uint32_t abi_version;        /* DORA_<TOP>_ABI_VERSION: what ABI_VERSION reads */
  const uint32_t *hw_digest;   /* dora_<top>_hw_digest: what HW_DIGEST[i] reads */
  uint32_t hw_digest_words;
  const uint32_t *layout_hash; /* dora_<top>_layout_hash: what LAYOUT_HASH[i] reads */
  uint32_t layout_hash_words;
  uint32_t scan_bits;          /* DORA_<TOP>_SCAN_BITS */
  uint32_t scan_words;         /* DORA_<TOP>_SCAN_WORDS: SCAN_DATA words per image */
  uint32_t chain_width;        /* DORA_<TOP>_CHAIN_WIDTH */
  uint32_t mem_ports;          /* DORA_<TOP>_MEM_PORTS */
  uint32_t spm_words;          /* DORA_<TOP>_SPM_WORDS: words per port's scratchpad */
};

#define DORA_RUNTIME_COUNT_OF(array) \
  ((uint32_t)(sizeof(array) / sizeof((array)[0])))

/* The descriptor of the fabric whose header defines DORA_<TOP>_* (TOP) and
 * dora_<top>_* (top), e.g. DORA_FABRIC_DESCRIPTOR(HYCUBE_ARRAY, hycube_array). */
#define DORA_FABRIC_DESCRIPTOR(TOP, top)                                     \
  {                                                                          \
    .name = #top,                                                            \
    .base = DORA_##TOP##_BASE,                                               \
    .id = DORA_##TOP##_ID,                                                   \
    .abi_version = DORA_##TOP##_ABI_VERSION,                                 \
    .hw_digest = dora_##top##_hw_digest,                                     \
    .hw_digest_words = DORA_RUNTIME_COUNT_OF(dora_##top##_hw_digest),        \
    .layout_hash = dora_##top##_layout_hash,                                 \
    .layout_hash_words = DORA_RUNTIME_COUNT_OF(dora_##top##_layout_hash),    \
    .scan_bits = DORA_##TOP##_SCAN_BITS,                                     \
    .scan_words = DORA_##TOP##_SCAN_WORDS,                                   \
    .chain_width = DORA_##TOP##_CHAIN_WIDTH,                                 \
    .mem_ports = DORA_##TOP##_MEM_PORTS,                                     \
    .spm_words = DORA_##TOP##_SPM_WORDS,                                     \
  }

/* One 32-bit shell register at base + offset (fenced, as rta-v4 does). */
uint32_t dora_read(const struct dora_fabric *fabric, uint32_t offset);
void dora_write(const struct dora_fabric *fabric, uint32_t offset,
    uint32_t value);

/* ID, ABI_VERSION, HW_DIGEST[], LAYOUT_HASH[], SCAN_BITS, CHAIN_WIDTH,
 * MEM_PORTS and SPM_WORDS against the header; prints the digests it read. */
int dora_check_identity(const struct dora_fabric *fabric);

/* The shell's state after an SoC reset: CTRL at its reset value (RESET=1),
 * STATUS = RESET only, the scan programmer idle with no session, every
 * counter and ERROR 0, every SPM_ADDR at its reset value. */
int dora_check_reset_state(const struct dora_fabric *fabric);

/* Sticky errors (ERROR), clearing them (rw1c), and their names. */
uint32_t dora_errors(const struct dora_fabric *fabric);
void dora_clear_errors(const struct dora_fabric *fabric, uint32_t mask);
void dora_print_errors(const char *what, uint32_t errors);

/* count words of memory port port's scratchpad from word address, through
 * SPM_ADDR and SPM_WDATA / SPM_RDATA (the fabric must not be running). The
 * range must lie inside the scratchpad; afterwards SPM_ADDR must have
 * advanced by count and no HOST_* error may be set. */
int dora_spm_write(const struct dora_fabric *fabric, uint32_t port,
    uint32_t address, const uint32_t *words, uint32_t count);
int dora_spm_read(const struct dora_fabric *fabric, uint32_t port,
    uint32_t address, uint32_t *words, uint32_t count);

/* Read words [0, count) of port's scratchpad and compare them with
 * expected[]; prints the first report_limit mismatches and stores their
 * number in *mismatches. Returns 1 on any mismatch or protocol error. */
int dora_spm_verify(const struct dora_fabric *fabric, uint32_t port,
    const uint32_t *expected, uint32_t count, uint32_t report_limit,
    uint32_t *mismatches);

/* Program one configuration image of scan_words SCAN_DATA words (the
 * header's image, already in shift order): PROG_RST, every SCAN_DATA word,
 * a check that SCAN_SHIFTED is SCAN_BITS, FINISH, then wait for
 * SCAN_STATUS.DONE with the session closed. */
int dora_program(const struct dora_fabric *fabric, const uint32_t *image,
    uint32_t words);

/* Set CTRL.RESET (the level of the fabric's reset_i) and check STATUS. */
int dora_set_reset(const struct dora_fabric *fabric, int asserted);

/* Drive en_i for exactly cycles cycles in one RUN_CYCLES burst and wait for
 * it to end: EN_CYCLES must advance by exactly cycles and ERROR.RUN stay
 * clear. The fabric must be out of reset (CTRL.RESET = 0) and not running.
 * A kernel runs in one burst: the LSU keeps loading while en_i is low. */
int dora_run(const struct dora_fabric *fabric, uint32_t cycles);

#endif
