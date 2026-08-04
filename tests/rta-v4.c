#include <stdint.h>
#include <stdio.h>

#include "rta-v4.h"
#include "rta-v4-add-chain.h"
#include "rta-v4-test-runtime.h"

int main(void)
{
  const uint8_t input = UINT8_C(0xa7);
  const uint8_t expected = (uint8_t)(input + UINT8_C(10));

  if (rta_v4_validate_identity() ||
      rta_v4_configure(rta_v4_add_chain_bitstream,
          sizeof(rta_v4_add_chain_bitstream), RTA_V4_CONFIG_START,
          "add-chain"))
    return 1;

  rta_v4_zero_inputs();
  rta_v4_write(RTA_V4_WEST_INPUT(0), rta_v4_pack_lane(input, 0, 0));

  /*
   * The streaming test's latency is an index delta of 13. A sample launched
   * from reset crosses 14 enabled register edges, including the output pad.
   */
  rta_v4_write(RTA_V4_COMPUTE_CONTROL, 0);
  for (uint32_t cycle = 0;
       cycle < RTA_V4_ADD_CHAIN_MANUAL_STEPS;
       ++cycle)
    rta_v4_write(RTA_V4_COMPUTE_CONTROL, RTA_V4_COMPUTE_STEP);
  rta_v4_write(RTA_V4_COMPUTE_CONTROL, RTA_V4_COMPUTE_CAPTURE);

  uint32_t status = rta_v4_read(RTA_V4_COMPUTE_STATUS);
  if (!(status & RTA_V4_COMPUTE_SNAPSHOT_VALID) ||
      (status & RTA_V4_COMPUTE_ANY_ERROR)) {
    printf("RTA V4 compute protocol failed: status 0x%x error 0x%x\n",
        status, rta_v4_read(RTA_V4_COMPUTE_ERROR));
    return 1;
  }

  uint8_t actual = (uint8_t)rta_v4_read(RTA_V4_EAST_OUTPUT(0));
  if (actual != expected) {
    printf("RTA V4 add-chain result 0x%x, expected 0x%x\n", actual, expected);
    return 1;
  }

  if (rta_v4_read(RTA_V4_ACTIVITY) != UINT32_C(0xffff)) {
    printf("RTA V4 activity mask mismatch\n");
    return 1;
  }

  printf("RTA V4 add-chain result 0x%x is correct\n", actual);
  return 0;
}
