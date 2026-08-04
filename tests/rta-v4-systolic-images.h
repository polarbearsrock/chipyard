#ifndef CHIPYARD_RTA_V4_SYSTOLIC_IMAGES_H
#define CHIPYARD_RTA_V4_SYSTOLIC_IMAGES_H

#include <stdint.h>

#define RTA_V4_DECLARE_SYSTOLIC_IMAGE(name) \
  extern const uint8_t _binary_systolic_##name##_bin_start[]; \
  extern const uint8_t _binary_systolic_##name##_bin_end[]

RTA_V4_DECLARE_SYSTOLIC_IMAGE(clear);
RTA_V4_DECLARE_SYSTOLIC_IMAGE(compute);
RTA_V4_DECLARE_SYSTOLIC_IMAGE(drain_col0);
RTA_V4_DECLARE_SYSTOLIC_IMAGE(drain_col1);
RTA_V4_DECLARE_SYSTOLIC_IMAGE(drain_col2);
RTA_V4_DECLARE_SYSTOLIC_IMAGE(drain_col3);

#undef RTA_V4_DECLARE_SYSTOLIC_IMAGE

#endif
