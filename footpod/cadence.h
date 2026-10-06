#pragma once
#include <math.h>
#include <stdint.h>

// Same signed Y-gyro cycle detector validated in the development dashboard.
// One complete one-foot rotation cycle represents two total steps.
struct GyroCadence {
  static constexpr uint32_t MIN_STRIDE_US = 450000, STOP_US = 3000000;
  static constexpr float PEAK_DPS = 40.0f, REARM_DPS = -20.0f, FILTER_SECONDS = 0.04f;
  float filtered = 0, spm = 0;
  uint32_t last_sample_us = 0, last_stride_us = 0, cycles = 0;
  bool have_sample = false, have_stride = false, armed = false;

  void reset() { *this = GyroCadence(); }

  bool update(float rotation_y_dps, uint32_t now_us) {
    uint32_t dt_us = uint32_t(now_us - last_sample_us);
    if (!have_sample || dt_us == 0 || dt_us > 100000) {
      filtered = rotation_y_dps;
      armed = false;
    } else {
      float dt = dt_us * 0.000001f;
      filtered += (1.0f - expf(-dt / FILTER_SECONDS)) * (rotation_y_dps - filtered);
    }
    last_sample_us = now_us; have_sample = true;
    if (have_stride && uint32_t(now_us - last_stride_us) > STOP_US) {
      have_stride = false; spm = 0; armed = false;
    }
    if (filtered <= REARM_DPS) armed = true;
    if (!armed || filtered < PEAK_DPS) return false;
    armed = false;
    uint32_t interval = uint32_t(now_us - last_stride_us);
    if (have_stride && interval < MIN_STRIDE_US) return false;
    if (have_stride) {
      float measured = 120000000.0f / interval;
      spm = spm ? 0.6f * spm + 0.4f * measured : measured;
    }
    last_stride_us = now_us; have_stride = true; ++cycles;
    return true;
  }

  uint8_t cadence(uint32_t now_us) const {
    if (!have_stride || uint32_t(now_us - last_stride_us) > STOP_US) return 0;
    float bounded = fminf(255.0f, fmaxf(0.0f, spm));
    return uint8_t(lroundf(bounded));
  }
};
