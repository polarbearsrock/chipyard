#ifndef CHIPYARD_RTA_V4_TEST_RUNTIME_H
#define CHIPYARD_RTA_V4_TEST_RUNTIME_H

#include <stddef.h>
#include <stdint.h>

void rta_v4_write(uintptr_t offset, uint32_t value);
uint32_t rta_v4_read(uintptr_t offset);

int rta_v4_validate_identity(void);
int rta_v4_configure(const uint8_t *bitstream, size_t bitstream_bytes,
    uint32_t command, const char *phase_name);
void rta_v4_zero_inputs(void);

#endif
