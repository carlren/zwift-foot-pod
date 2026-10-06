#pragma once
#include <stdint.h>

// Handles are assigned by the BLE stack, not slot indices. Never use a global
// "current connection": a companion disconnect must not alter Zwift's slot.
struct PodClient {
  volatile uint16_t handle = 0xffff;
  volatile bool collecting = false;
  bool cadencePending = false;
  uint32_t sent = 0, dropped = 0;
};

struct PodClients {
  PodClient slots[2];
  PodClient* find(uint16_t handle) {
    for (auto& slot : slots) if (slot.handle == handle && handle != 0xffff) return &slot;
    return nullptr;
  }
  void connect(uint16_t handle) {
    if (find(handle)) return;
    for (auto& slot : slots) if (slot.handle == 0xffff) {
      slot = PodClient{}; slot.handle = handle; return;
    }
  }
  void disconnect(uint16_t handle) {
    if (auto* slot = find(handle)) *slot = PodClient{};
  }
};

// Typical LiPo open-circuit curve, 0..100% in 10% increments (Zephyr's
// BATTERY_OCV_TABLE_LIPO_DEFAULT, based on Analog Devices AN4189 Table 1).
// An estimate only: charging, temperature, load and cell aging shift voltage.
inline uint8_t batteryPercent(uint16_t mv) {
  const uint16_t curve[] = {3306,3687,3741,3775,3793,3821,3884,3945,4008,4086,4177};
  if (mv <= curve[0]) return 0;
  for (uint8_t i = 1; i < 11; ++i) if (mv < curve[i])
    return (i-1)*10 + ((mv-curve[i-1])*10 + (curve[i]-curve[i-1])/2) /
                       (curve[i]-curve[i-1]);
  return 100;
}
