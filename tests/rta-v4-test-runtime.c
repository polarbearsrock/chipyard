#include <stddef.h>
#include <stdint.h>
#include <stdio.h>

#include "mmio.h"
#include "rta-v4.h"
#include "rta-v4-test-runtime.h"

#define RTA_V4_TIMEOUT UINT32_C(1000000)

static const uint32_t expected_layout_hash[8] = {
  UINT32_C(0x36c02b05), UINT32_C(0x3e368648),
  UINT32_C(0x4ccd7b84), UINT32_C(0x33bd5fac),
  UINT32_C(0xfc295734), UINT32_C(0x667b01ac),
  UINT32_C(0x7a4ba926), UINT32_C(0x8a0b9e7a)
};

void rta_v4_write(uintptr_t offset, uint32_t value)
{
  reg_write32(RTA_V4_BASE + offset, value);
  __asm__ volatile ("fence iorw, iorw" ::: "memory");
}

uint32_t rta_v4_read(uintptr_t offset)
{
  uint32_t value;
  __asm__ volatile ("fence iorw, iorw" ::: "memory");
  value = reg_read32(RTA_V4_BASE + offset);
  __asm__ volatile ("fence iorw, iorw" ::: "memory");
  return value;
}

static uint32_t bitstream_word(
    const uint8_t *bitstream, size_t bitstream_bytes, uint32_t word_index)
{
  uint32_t word = 0;
  size_t byte_index = (size_t)word_index * 4U;

  for (uint32_t lane = 0; lane < 4U; ++lane) {
    size_t index = byte_index + lane;
    if (index < bitstream_bytes)
      word |= (uint32_t)bitstream[index] << (8U * lane);
  }
  return word;
}

int rta_v4_validate_identity(void)
{
  if (rta_v4_read(RTA_V4_DEVICE_ID) != RTA_V4_ID_VALUE ||
      rta_v4_read(RTA_V4_ABI_VERSION) != RTA_V4_ABI_VERSION_VALUE ||
      rta_v4_read(RTA_V4_CAPABILITIES) != RTA_V4_CAPABILITIES_VALUE ||
      rta_v4_read(RTA_V4_BITSTREAM_BITS) != RTA_V4_SCAN_BITS) {
    printf("RTA V4 identity or ABI mismatch\n");
    return 1;
  }

  for (uint32_t index = 0; index < 8U; ++index) {
    uint32_t actual = rta_v4_read(RTA_V4_LAYOUT_HASH + 8U * index);
    if (actual != expected_layout_hash[index]) {
      printf("RTA V4 layout hash mismatch at word %u\n", index);
      return 1;
    }
  }

  rta_v4_write(RTA_V4_SCRATCH, UINT32_C(0xdecafbad));
  if (rta_v4_read(RTA_V4_SCRATCH) != UINT32_C(0xdecafbad)) {
    printf("RTA V4 scratch register mismatch\n");
    return 1;
  }
  return 0;
}

int rta_v4_configure(const uint8_t *bitstream, size_t bitstream_bytes,
    uint32_t command, const char *phase_name)
{
  if (bitstream == NULL || bitstream_bytes != RTA_V4_SCAN_BYTES) {
    printf("RTA V4 %s image has %lu bytes, expected %u\n", phase_name,
        (unsigned long)bitstream_bytes, RTA_V4_SCAN_BYTES);
    return 1;
  }
  if (command != RTA_V4_CONFIG_START && command != RTA_V4_CONFIG_RELOAD) {
    printf("RTA V4 %s has invalid configuration command 0x%x\n",
        phase_name, command);
    return 1;
  }

  if (command == RTA_V4_CONFIG_RELOAD) {
    uint32_t compute_status = rta_v4_read(RTA_V4_COMPUTE_STATUS);
    if (!(compute_status & RTA_V4_COMPUTE_CONFIGURED) ||
        (compute_status & (RTA_V4_COMPUTE_RESET_ACTIVE |
                           RTA_V4_COMPUTE_RUN_ACTIVE))) {
      printf("RTA V4 %s cannot preserve state from compute status 0x%x\n",
          phase_name, compute_status);
      return 1;
    }
  }

  rta_v4_write(RTA_V4_CONFIG_COMMAND, command);

  for (uint32_t word = 0; word < RTA_V4_SCAN_WORDS; ++word) {
    uint32_t timeout = RTA_V4_TIMEOUT;
    uint32_t status;
    do {
      status = rta_v4_read(RTA_V4_CONFIG_STATUS);
      if (status & RTA_V4_CFG_ANY_ERROR) {
        printf("RTA V4 %s configuration error 0x%x after word %u\n",
            phase_name, rta_v4_read(RTA_V4_CONFIG_ERROR), word);
        return 1;
      }
    } while (!(status & RTA_V4_CFG_DATA_READY) && --timeout);

    if (!timeout) {
      printf("RTA V4 %s timed out waiting for configuration data-ready\n",
          phase_name);
      return 1;
    }
    rta_v4_write(RTA_V4_CONFIG_DATA,
        bitstream_word(bitstream, bitstream_bytes, word));
  }

  for (uint32_t timeout = RTA_V4_TIMEOUT; timeout; --timeout) {
    uint32_t status = rta_v4_read(RTA_V4_CONFIG_STATUS);
    if (status & RTA_V4_CFG_ANY_ERROR) {
      printf("RTA V4 %s configuration failed: 0x%x\n", phase_name,
          rta_v4_read(RTA_V4_CONFIG_ERROR));
      return 1;
    }
    if (status & RTA_V4_CFG_CONFIGURED) {
      if (rta_v4_read(RTA_V4_CONFIG_BITS_IN) != RTA_V4_SCAN_BITS ||
          rta_v4_read(RTA_V4_CONFIG_BITS_OUT) != RTA_V4_SCAN_BITS) {
        printf("RTA V4 %s scan counters do not match\n", phase_name);
        return 1;
      }
      if (command == RTA_V4_CONFIG_RELOAD &&
          (rta_v4_read(RTA_V4_COMPUTE_STATUS) &
           RTA_V4_COMPUTE_RESET_ACTIVE)) {
        printf("RTA V4 %s warm reload unexpectedly reset compute state\n",
            phase_name);
        return 1;
      }
      return 0;
    }
  }

  printf("RTA V4 %s timed out waiting for configuration completion\n",
      phase_name);
  return 1;
}

void rta_v4_zero_inputs(void)
{
  for (uint32_t lane = 0; lane < 4U; ++lane) {
    rta_v4_write(RTA_V4_WEST_INPUT(lane), 0);
    rta_v4_write(RTA_V4_NORTH_INPUT(lane), 0);
  }
}
