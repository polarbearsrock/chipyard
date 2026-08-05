#include <stddef.h>
#include <stdint.h>
#include <stdio.h>

#include "rta-v4.h"
#include "rta-v4-systolic-images.h"
#include "rta-v4-test-runtime.h"

#define RTA_V4_ROWS 4U
#define RTA_V4_COLUMNS 4U
#define RTA_V4_LANES 4U
#define RTA_V4_SYSTOLIC_K_MAX 8U
#define RTA_V4_RANDOM_CASES 8U
#define RTA_V4_COMPUTE_FLUSH_STEPS 16U
#define RTA_V4_RANDOM_BASE_SEED UINT32_C(0x1aceb00c)
#define RTA_V4_RANDOM_SEED_STRIDE UINT32_C(0x01010101)

struct rta_v4_image {
  const uint8_t *start;
  const uint8_t *end;
  const char *name;
};

struct rta_v4_result_matrix {
  int16_t cell[RTA_V4_ROWS][RTA_V4_COLUMNS];
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
static const struct rta_v4_result_matrix baseline_expected = {
  .cell = {
    {  64,  32,  64,  112},
    { -64, -48, -64, -112},
    { -32,   0,  32,  -16},
    {  80,  48,  48,   48},
  },
};

/*
 * Each logical matrix element is a packed vector of four signed INT4 lanes:
 * A[4][K][4] times B[K][4][4]. Raw nibbles keep packing independent from the
 * signed arithmetic used by the software reference model.
 */
static uint8_t a_nibbles[RTA_V4_ROWS][RTA_V4_SYSTOLIC_K_MAX]
    [RTA_V4_LANES];
static uint8_t b_nibbles[RTA_V4_SYSTOLIC_K_MAX][RTA_V4_COLUMNS]
    [RTA_V4_LANES];
static struct rta_v4_result_matrix reference_result;

static size_t image_size(const struct rta_v4_image *image)
{
  return (size_t)((uintptr_t)image->end - (uintptr_t)image->start);
}

static uint8_t i4_nibble(int32_t value)
{
  return (uint8_t)((uint32_t)value & UINT32_C(0xf));
}

static int32_t signed_i4(uint8_t nibble)
{
  uint32_t value = (uint32_t)nibble & UINT32_C(0xf);
  return (value & UINT32_C(0x8)) ? (int32_t)value - 16 : (int32_t)value;
}

static int32_t signed_i16(uint16_t value)
{
  return (value & UINT16_C(0x8000))
      ? (int32_t)value - INT32_C(65536) : (int32_t)value;
}

static uint8_t pack_i4_lanes(const uint8_t lanes[RTA_V4_LANES],
    uint32_t first_lane)
{
  return (uint8_t)(((lanes[first_lane + 1U] & UINT8_C(0xf)) << 4) |
      (lanes[first_lane] & UINT8_C(0xf)));
}

static uint32_t make_a_packet(uint32_t row, uint32_t k)
{
  return rta_v4_pack_lane(
      pack_i4_lanes(a_nibbles[row][k], 0),
      pack_i4_lanes(a_nibbles[row][k], 2), 1);
}

static uint32_t make_b_packet(uint32_t k, uint32_t column)
{
  return rta_v4_pack_lane(
      pack_i4_lanes(b_nibbles[k][column], 0),
      pack_i4_lanes(b_nibbles[k][column], 2), 1);
}

static void clear_operands(void)
{
  for (uint32_t row = 0; row < RTA_V4_ROWS; ++row) {
    for (uint32_t k = 0; k < RTA_V4_SYSTOLIC_K_MAX; ++k) {
      for (uint32_t lane = 0; lane < RTA_V4_LANES; ++lane)
        a_nibbles[row][k][lane] = 0;
    }
  }

  for (uint32_t k = 0; k < RTA_V4_SYSTOLIC_K_MAX; ++k) {
    for (uint32_t column = 0; column < RTA_V4_COLUMNS; ++column) {
      for (uint32_t lane = 0; lane < RTA_V4_LANES; ++lane)
        b_nibbles[k][column][lane] = 0;
    }
  }
}

static void fill_baseline_vectors(uint32_t case_k)
{
  clear_operands();
  for (uint32_t row = 0; row < RTA_V4_ROWS; ++row) {
    for (uint32_t k = 0; k < case_k; ++k) {
      for (uint32_t lane = 0; lane < RTA_V4_LANES; ++lane) {
        int32_t value = (int32_t)(row * 17U + k * 11U + lane * 5U + 1U);
        if ((row + k + lane) & 1U)
          value = -value;
        a_nibbles[row][k][lane] = i4_nibble(value);
      }
    }
  }

  for (uint32_t k = 0; k < case_k; ++k) {
    for (uint32_t column = 0; column < RTA_V4_COLUMNS; ++column) {
      for (uint32_t lane = 0; lane < RTA_V4_LANES; ++lane) {
        int32_t value =
            (int32_t)(column * 13U + k * 7U + lane * 3U + 2U);
        if ((column + k + lane + 1U) & 1U)
          value = -value;
        b_nibbles[k][column][lane] = i4_nibble(value);
      }
    }
  }
}

static uint32_t lfsr_next(uint32_t value)
{
  uint32_t feedback = ((value >> 31) ^ (value >> 21) ^
      (value >> 1) ^ value) & UINT32_C(1);
  return (value << 1) | feedback;
}

static uint32_t random_case_seed(uint32_t case_index)
{
  return RTA_V4_RANDOM_BASE_SEED ^
      (case_index * RTA_V4_RANDOM_SEED_STRIDE);
}

static void fill_random_vectors(uint32_t case_index, uint32_t case_k)
{
  uint32_t lfsr = random_case_seed(case_index);

  clear_operands();
  for (uint32_t row = 0; row < RTA_V4_ROWS; ++row) {
    for (uint32_t k = 0; k < case_k; ++k) {
      for (uint32_t lane = 0; lane < RTA_V4_LANES; ++lane) {
        lfsr = lfsr_next(lfsr);
        a_nibbles[row][k][lane] = (uint8_t)(lfsr & UINT32_C(0xf));
      }
    }
  }

  for (uint32_t k = 0; k < case_k; ++k) {
    for (uint32_t column = 0; column < RTA_V4_COLUMNS; ++column) {
      for (uint32_t lane = 0; lane < RTA_V4_LANES; ++lane) {
        lfsr = lfsr_next(lfsr);
        b_nibbles[k][column][lane] =
            (uint8_t)((lfsr >> 4) & UINT32_C(0xf));
      }
    }
  }
}

static int compute_reference(uint32_t case_k)
{
  for (uint32_t row = 0; row < RTA_V4_ROWS; ++row) {
    for (uint32_t column = 0; column < RTA_V4_COLUMNS; ++column) {
      int32_t sum = 0;
      for (uint32_t k = 0; k < case_k; ++k) {
        for (uint32_t lane = 0; lane < RTA_V4_LANES; ++lane) {
          sum += signed_i4(a_nibbles[row][k][lane]) *
              signed_i4(b_nibbles[k][column][lane]);
        }
      }
      if (sum < -32768 || sum > 32767) {
        printf("RTA V4 software reference overflow at K=%u C[%u][%u]\n",
            case_k, row, column);
        return 1;
      }
      reference_result.cell[row][column] = (int16_t)sum;
    }
  }
  return 0;
}

static int validate_reference_model(void)
{
  for (uint32_t row = 0; row < RTA_V4_ROWS; ++row) {
    for (uint32_t column = 0; column < RTA_V4_COLUMNS; ++column) {
      if (reference_result.cell[row][column] !=
          baseline_expected.cell[row][column]) {
        printf("RTA V4 software reference disagrees with baseline C[%u][%u]: "
            "%d, expected %d\n", row, column,
            (int)reference_result.cell[row][column],
            (int)baseline_expected.cell[row][column]);
        return 1;
      }
    }
  }
  return 0;
}

static int configure_image(
    const struct rta_v4_image *image, uint32_t command)
{
  return rta_v4_configure(
      image->start, image_size(image), command, image->name);
}

static int configure_case_image(const struct rta_v4_image *image,
    uint32_t command, const char *case_name, uint32_t case_index,
    uint32_t seed, uint32_t case_k)
{
  if (!configure_image(image, command))
    return 0;

  printf("RTA V4 %s case %u seed 0x%x K=%u failed to configure %s\n",
      case_name, case_index, seed, case_k, image->name);
  return 1;
}

static void step(uint32_t count)
{
  for (uint32_t cycle = 0; cycle < count; ++cycle)
    rta_v4_write(RTA_V4_COMPUTE_CONTROL, RTA_V4_COMPUTE_STEP);
}

static int check_compute_protocol(const char *case_name, uint32_t case_index,
    const char *phase)
{
  uint32_t status = rta_v4_read(RTA_V4_COMPUTE_STATUS);
  if ((status & RTA_V4_COMPUTE_ANY_ERROR) ||
      (status & RTA_V4_COMPUTE_RESET_ACTIVE)) {
    printf("RTA V4 %s case %u %s protocol failed: status 0x%x error "
        "0x%x\n", case_name, case_index, phase, status,
        rta_v4_read(RTA_V4_COMPUTE_ERROR));
    return 1;
  }
  return 0;
}

static int run_systolic_case(const char *case_name, uint32_t case_index,
    uint32_t seed, uint32_t case_k,
    const struct rta_v4_result_matrix *expected, uint32_t clear_command)
{
  if (case_k == 0 || case_k > RTA_V4_SYSTOLIC_K_MAX) {
    printf("RTA V4 %s case %u has invalid K=%u\n",
        case_name, case_index, case_k);
    return 1;
  }

  if (configure_case_image(&clear_image, clear_command, case_name,
      case_index, seed, case_k))
    return 1;

  /* Release reset after the first cold START; warm clears leave it released. */
  rta_v4_zero_inputs();
  rta_v4_write(RTA_V4_COMPUTE_CONTROL, 0);
  step(3);
  if (check_compute_protocol(case_name, case_index, "clear"))
    return 1;

  if (configure_case_image(&compute_image, RTA_V4_CONFIG_RELOAD, case_name,
      case_index, seed, case_k))
    return 1;

  for (uint32_t k = 0; k < case_k; ++k) {
    for (uint32_t row = 0; row < RTA_V4_ROWS; ++row)
      rta_v4_write(RTA_V4_WEST_INPUT(row), make_a_packet(row, k));
    for (uint32_t column = 0; column < RTA_V4_COLUMNS; ++column)
      rta_v4_write(RTA_V4_NORTH_INPUT(column), make_b_packet(k, column));
    step(1);
  }
  rta_v4_zero_inputs();
  step(RTA_V4_COMPUTE_FLUSH_STEPS);
  if (check_compute_protocol(case_name, case_index, "compute"))
    return 1;

  for (int column = (int)RTA_V4_COLUMNS - 1; column >= 0; --column) {
    const struct rta_v4_image *image = &drain_images[column];
    if (configure_case_image(image, RTA_V4_CONFIG_RELOAD, case_name,
        case_index, seed, case_k))
      return 1;

    rta_v4_zero_inputs();
    step(2U + (RTA_V4_COLUMNS - 1U - (uint32_t)column));
    rta_v4_write(RTA_V4_COMPUTE_CONTROL, RTA_V4_COMPUTE_CAPTURE);

    uint32_t status = rta_v4_read(RTA_V4_COMPUTE_STATUS);
    if (!(status & RTA_V4_COMPUTE_SNAPSHOT_VALID) ||
        (status & (RTA_V4_COMPUTE_ANY_ERROR |
                   RTA_V4_COMPUTE_RESET_ACTIVE))) {
      printf("RTA V4 %s case %u drain column %d failed: status 0x%x "
          "error 0x%x\n", case_name, case_index, column, status,
          rta_v4_read(RTA_V4_COMPUTE_ERROR));
      return 1;
    }

    for (uint32_t row = 0; row < RTA_V4_ROWS; ++row) {
      uint16_t actual = (uint16_t)rta_v4_read(RTA_V4_EAST_OUTPUT(row));
      int16_t wanted_signed = expected->cell[row][column];
      uint16_t wanted = (uint16_t)wanted_signed;
      if (actual != wanted) {
        printf("RTA V4 %s case %u seed 0x%x K=%u C[%u][%d] = "
            "0x%04x (%d), expected 0x%04x (%d)\n",
            case_name, case_index, seed, case_k, row, column,
            (unsigned int)actual, (int)signed_i16(actual),
            (unsigned int)wanted, (int)wanted_signed);
        return 1;
      }
    }

    if (rta_v4_read(RTA_V4_ACTIVITY) != UINT32_C(0xffff)) {
      printf("RTA V4 %s case %u drain column %d activity mismatch\n",
          case_name, case_index, column);
      return 1;
    }
  }

  printf("RTA V4 systolic %s case %u seed 0x%x K=%u is correct\n",
      case_name, case_index, seed, case_k);
  return 0;
}

int main(void)
{
  if (rta_v4_validate_identity())
    return 1;

  fill_baseline_vectors(4);
  if (compute_reference(4) || validate_reference_model() ||
      run_systolic_case("baseline", 0, 0, 4, &baseline_expected,
          RTA_V4_CONFIG_START))
    return 1;

  for (uint32_t case_index = 0;
       case_index < RTA_V4_RANDOM_CASES;
       ++case_index) {
    uint32_t case_k = case_index + 1U;
    uint32_t seed = random_case_seed(case_index);

    fill_random_vectors(case_index, case_k);
    if (compute_reference(case_k) ||
        run_systolic_case("random", case_index, seed, case_k,
            &reference_result, RTA_V4_CONFIG_RELOAD))
      return 1;
  }

  printf("RTA V4 systolic fixed oracle and 8 randomized signed-INT4 "
      "matrices are correct\n");
  return 0;
}
