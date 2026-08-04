#include <stddef.h>
#include <stdint.h>
#include <stdio.h>

#include "rta-v4.h"
#include "rta-v4-systolic-images.h"
#include "rta-v4-test-runtime.h"

#define RTA_V4_ROWS 4U
#define RTA_V4_COLUMNS 4U
#define RTA_V4_LANES 4U
#define RTA_V4_SYSTOLIC_K 4U
#define RTA_V4_COMPUTE_FLUSH_STEPS 16U

struct rta_v4_image {
  const uint8_t *start;
  const uint8_t *end;
  const char *name;
};

#define RTA_V4_IMAGE(name) { \
  _binary_systolic_##name##_bin_start, \
  _binary_systolic_##name##_bin_end, #name \
}

static const struct rta_v4_image clear_image = RTA_V4_IMAGE(clear);
static const struct rta_v4_image compute_image = RTA_V4_IMAGE(compute);
static const struct rta_v4_image drain_images[RTA_V4_COLUMNS] = {
  RTA_V4_IMAGE(drain_col0),
  RTA_V4_IMAGE(drain_col1),
  RTA_V4_IMAGE(drain_col2),
  RTA_V4_IMAGE(drain_col3),
};

#undef RTA_V4_IMAGE

/* DORA array_systolic baseline_mixed_k4 oracle. */
static const int16_t expected[RTA_V4_ROWS][RTA_V4_COLUMNS] = {
  {  64,  32,  64,  112},
  { -64, -48, -64, -112},
  { -32,   0,  32,  -16},
  {  80,  48,  48,   48},
};

static size_t image_size(const struct rta_v4_image *image)
{
  return (size_t)((uintptr_t)image->end - (uintptr_t)image->start);
}

static uint8_t i4_nibble(int value)
{
  return (uint8_t)value & UINT8_C(0xf);
}

static uint8_t pack_i4_lanes(const uint8_t lanes[RTA_V4_LANES],
    uint32_t first_lane)
{
  return (uint8_t)((lanes[first_lane + 1U] << 4) |
      lanes[first_lane]);
}

static uint32_t make_a_packet(uint32_t row, uint32_t k)
{
  uint8_t lanes[RTA_V4_LANES];
  for (uint32_t lane = 0; lane < RTA_V4_LANES; ++lane) {
    int value = (int)(row * 17U + k * 11U + lane * 5U + 1U);
    if ((row + k + lane) & 1U)
      value = -value;
    lanes[lane] = i4_nibble(value);
  }
  return rta_v4_pack_lane(
      pack_i4_lanes(lanes, 0), pack_i4_lanes(lanes, 2), 1);
}

static uint32_t make_b_packet(uint32_t k, uint32_t column)
{
  uint8_t lanes[RTA_V4_LANES];
  for (uint32_t lane = 0; lane < RTA_V4_LANES; ++lane) {
    int value = (int)(column * 13U + k * 7U + lane * 3U + 2U);
    if ((column + k + lane + 1U) & 1U)
      value = -value;
    lanes[lane] = i4_nibble(value);
  }
  return rta_v4_pack_lane(
      pack_i4_lanes(lanes, 0), pack_i4_lanes(lanes, 2), 1);
}

static int configure_image(
    const struct rta_v4_image *image, uint32_t command)
{
  return rta_v4_configure(
      image->start, image_size(image), command, image->name);
}

static void step(uint32_t count)
{
  for (uint32_t cycle = 0; cycle < count; ++cycle)
    rta_v4_write(RTA_V4_COMPUTE_CONTROL, RTA_V4_COMPUTE_STEP);
}

static int check_compute_protocol(const char *phase)
{
  uint32_t status = rta_v4_read(RTA_V4_COMPUTE_STATUS);
  if ((status & RTA_V4_COMPUTE_ANY_ERROR) ||
      (status & RTA_V4_COMPUTE_RESET_ACTIVE)) {
    printf("RTA V4 %s compute protocol failed: status 0x%x error 0x%x\n",
        phase, status, rta_v4_read(RTA_V4_COMPUTE_ERROR));
    return 1;
  }
  return 0;
}

int main(void)
{
  if (rta_v4_validate_identity() ||
      configure_image(&clear_image, RTA_V4_CONFIG_START))
    return 1;

  /* Cold START holds compute reset until software explicitly releases it. */
  rta_v4_zero_inputs();
  rta_v4_write(RTA_V4_COMPUTE_CONTROL, 0);
  step(3);
  if (check_compute_protocol("clear"))
    return 1;

  if (configure_image(&compute_image, RTA_V4_CONFIG_RELOAD))
    return 1;

  for (uint32_t k = 0; k < RTA_V4_SYSTOLIC_K; ++k) {
    for (uint32_t row = 0; row < RTA_V4_ROWS; ++row)
      rta_v4_write(RTA_V4_WEST_INPUT(row), make_a_packet(row, k));
    for (uint32_t column = 0; column < RTA_V4_COLUMNS; ++column)
      rta_v4_write(RTA_V4_NORTH_INPUT(column), make_b_packet(k, column));
    step(1);
  }
  rta_v4_zero_inputs();
  step(RTA_V4_COMPUTE_FLUSH_STEPS);
  if (check_compute_protocol("compute"))
    return 1;

  for (int column = (int)RTA_V4_COLUMNS - 1; column >= 0; --column) {
    const struct rta_v4_image *image = &drain_images[column];
    if (configure_image(image, RTA_V4_CONFIG_RELOAD))
      return 1;

    rta_v4_zero_inputs();
    step(2U + (RTA_V4_COLUMNS - 1U - (uint32_t)column));
    rta_v4_write(RTA_V4_COMPUTE_CONTROL, RTA_V4_COMPUTE_CAPTURE);

    uint32_t status = rta_v4_read(RTA_V4_COMPUTE_STATUS);
    if (!(status & RTA_V4_COMPUTE_SNAPSHOT_VALID) ||
        (status & (RTA_V4_COMPUTE_ANY_ERROR |
                   RTA_V4_COMPUTE_RESET_ACTIVE))) {
      printf("RTA V4 drain column %d failed: status 0x%x error 0x%x\n",
          column, status, rta_v4_read(RTA_V4_COMPUTE_ERROR));
      return 1;
    }

    for (uint32_t row = 0; row < RTA_V4_ROWS; ++row) {
      uint16_t actual = (uint16_t)rta_v4_read(RTA_V4_EAST_OUTPUT(row));
      uint16_t wanted = (uint16_t)expected[row][column];
      if (actual != wanted) {
        printf("RTA V4 systolic C[%u][%d] = 0x%04x, expected 0x%04x\n",
            row, column, (unsigned int)actual, (unsigned int)wanted);
        return 1;
      }
    }

    if (rta_v4_read(RTA_V4_ACTIVITY) != UINT32_C(0xffff)) {
      printf("RTA V4 drain column %d activity mask mismatch\n", column);
      return 1;
    }
  }

  printf("RTA V4 systolic 4x4 signed-INT4 dot4 GEMM is correct\n");
  return 0;
}
