#include <Adafruit_TinyUSB.h>
#include <bluefruit.h>
#include <nrfx_twim.h>
#include <hal/nrf_gpio.h>
#include <math.h>
#include "cadence.h"
#include "companion.h"

// Seeed nRF52 Boards 1.1.13; XIAO nRF52840 Sense (original, not Plus).
constexpr uint8_t IMU_ADDRESS = 0x6A;
constexpr float STEP_LENGTH_M = 0.70f; // Mock speed only; calibrate later.
constexpr float BATTERY_DIVIDER = 1510.0f / 510.0f; // R16=1 MΩ, R17=510 kΩ.

BLEService rsc(0x1814);
BLECharacteristic measurement(0x2A53), feature(0x2A54), location(0x2A5D);
BLEDis deviceInfo;
BLEService collection("e85b0001-6d10-4a22-90c5-c813f72b1357");
BLECharacteristic imuData("e85b0002-6d10-4a22-90c5-c813f72b1357");
BLECharacteristic collectionControl("e85b0003-6d10-4a22-90c5-c813f72b1357");
BLECharacteristic collectionStatus("e85b0004-6d10-4a22-90c5-c813f72b1357");
BLECharacteristic batteryVoltage("e85b0005-6d10-4a22-90c5-c813f72b1357");
uint16_t batteryAdc = 0, batteryMv = 0;
bool batteryCharging = false, usbPower = false;
BLEService batteryService(0x180F);
BLECharacteristic batteryLevel(0x2A19);
uint8_t batteryPct = 0;
PodClients clients;
uint8_t cadencePacket[4] = {};
bool imuReady = false;
GyroCadence gyroCadence;
uint8_t whoAmI = 0, fixedCadence = 0;
uint32_t samples = 0, imuErrors = 0;
uint32_t notifications = 0, notifyErrors = 0, lastSample = 0;
float ax = 0, ay = 0, az = 0, gx = 0, gy = 0, gz = 0;
char command[40];
uint8_t commandLength = 0;
bool commandOverflow = false;
char logBuffer[512];
uint16_t logLength = 0, logOffset = 0;
const nrfx_twim_t imuBus = NRFX_TWIM_INSTANCE(1);
volatile bool transferDone = false, transferOk = false;

void imuTransferDone(nrfx_twim_evt_t const* event, void*) {
  transferOk = event->type == NRFX_TWIM_EVT_DONE;
  transferDone = true;
}

bool transfer(nrfx_twim_xfer_desc_t const& request) {
  transferDone = false; transferOk = false;
  if (nrfx_twim_xfer(&imuBus, &request, 0) != NRFX_SUCCESS) return false;
  uint32_t started = millis();
  while (!transferDone && uint32_t(millis() - started) < 50) delay(1);
  if (!transferDone) { nrfx_twim_disable(&imuBus); imuReady = false; }
  return transferDone && transferOk;
}

bool readRegisters(uint8_t reg, uint8_t* data, uint8_t length) {
  nrfx_twim_xfer_desc_t request = NRFX_TWIM_XFER_DESC_TXRX(IMU_ADDRESS, &reg, 1, data, length);
  return transfer(request);
}

bool writeRegister(uint8_t reg, uint8_t value) {
  uint8_t data[] = {reg, value};
  nrfx_twim_xfer_desc_t request = NRFX_TWIM_XFER_DESC_TX(IMU_ADDRESS, data, 2);
  return transfer(request);
}

bool startImu() {
  pinMode(PIN_LSM6DS3TR_C_POWER, OUTPUT);
  // Seeed's IMU library requires high drive on the sensor supply pin, P1.08.
  nrf_gpio_cfg(g_ADigitalPinMap[PIN_LSM6DS3TR_C_POWER], NRF_GPIO_PIN_DIR_OUTPUT,
               NRF_GPIO_PIN_INPUT_DISCONNECT, NRF_GPIO_PIN_NOPULL,
               NRF_GPIO_PIN_H0H1, NRF_GPIO_PIN_NOSENSE);
  digitalWrite(PIN_LSM6DS3TR_C_POWER, HIGH);
  delay(20);
  // The bundled Nordic driver supports asynchronous reads and a bounded timeout.
  nrfx_twim_config_t busConfig = NRFX_TWIM_DEFAULT_CONFIG(27, 7);
  busConfig.frequency = NRF_TWIM_FREQ_400K;
  if (nrfx_twim_init(&imuBus, &busConfig, imuTransferDone, nullptr) != NRFX_SUCCESS) return false;
  nrfx_twim_enable(&imuBus);
  if (!readRegisters(0x0F, &whoAmI, 1) || whoAmI != 0x6A) return false;
  // CTRL3_C: block update + address increment. 104 Hz, ±8 g, ±1000 dps.
  if (!writeRegister(0x12, 0x44) || !writeRegister(0x10, 0x4C) ||
      !writeRegister(0x11, 0x48)) return false;
  uint8_t config[3];
  return readRegisters(0x10, config, 3) && config[0] == 0x4C &&
         config[1] == 0x48 && config[2] == 0x44;
}

int16_t signedWord(const uint8_t* data) {
  return static_cast<int16_t>(uint16_t(data[0]) | (uint16_t(data[1]) << 8));
}

void resetEstimator() {
  gyroCadence.reset();
}

void writeWord(uint8_t* out, uint32_t value) {
  for (uint8_t i = 0; i < 4; ++i) out[i] = uint8_t(value >> (8 * i));
}

// Native HVX is nonblocking. A busy phone queue never stalls sensor sampling
// or the separate Zwift connection. All notification paths use the same API.
uint32_t notify(uint16_t handle, BLECharacteristic& characteristic,
                const uint8_t* data, uint16_t length) {
  ble_gatts_hvx_params_t request = {};
  request.handle = characteristic.handles().value_handle;
  request.type = BLE_GATT_HVX_NOTIFICATION;
  request.p_len = &length; request.p_data = data;
  return sd_ble_gatts_hvx(handle, &request);
}

void streamImu(const uint8_t* raw, uint32_t sample_us) {
  uint8_t packet[20];
  writeWord(packet, samples); writeWord(packet + 4, sample_us);
  memcpy(packet + 8, raw, 12);
  for (auto& peer : clients.slots) {
    if (peer.handle == 0xffff || !peer.collecting || !imuData.notifyEnabled(peer.handle)) continue;
    if (notify(peer.handle, imuData, packet, sizeof(packet)) == NRF_SUCCESS) ++peer.sent;
    else ++peer.dropped;
  }
}

void readCollectionStatus(uint16_t handle, BLECharacteristic*, ble_gatts_evt_read_t* request) {
  auto* peer = clients.find(handle);
  // Same v1 wire format; collection state and counters belong to the reader.
  uint8_t data[16] = {1, uint8_t((imuReady ? 1 : 0) |
    (peer && peer->collecting ? 2 : 0) | (imuData.notifyEnabled(handle) ? 4 : 0)), whoAmI, 0};
  writeWord(data + 4, peer ? peer->sent : 0);
  writeWord(data + 8, peer ? peer->dropped : 0); writeWord(data + 12, imuErrors);
  ble_gatts_rw_authorize_reply_params_t reply = {};
  reply.type = BLE_GATTS_AUTHORIZE_TYPE_READ;
  reply.params.read.gatt_status = request->offset <= sizeof(data) ?
      BLE_GATT_STATUS_SUCCESS : BLE_GATT_STATUS_ATTERR_INVALID_OFFSET;
  reply.params.read.update = 1;
  reply.params.read.offset = 0; reply.params.read.len = sizeof(data);
  reply.params.read.p_data = data;
  sd_ble_gatts_rw_authorize_reply(handle, &reply);
}

void collectionCommand(uint16_t handle, BLECharacteristic*, uint8_t* data, uint16_t length) {
  auto* peer = clients.find(handle);
  if (peer && length == 1 && data[0] <= 1) peer->collecting = data[0] == 1;
}

void collectionConnected(uint16_t handle) { clients.connect(handle); }
void collectionDisconnected(uint16_t handle, uint8_t) { clients.disconnect(handle); }

void readBattery() {
  batteryAdc = analogRead(PIN_VBAT);
  batteryMv = uint16_t(lroundf(batteryAdc * (3000.0f / 4096.0f) * BATTERY_DIVIDER));
  batteryCharging = digitalRead(23) == LOW; // P0.17, active-low charger output.
  usbPower = (NRF_POWER->USBREGSTATUS & POWER_USBREGSTATUS_VBUSDETECT_Msk) != 0;
  uint8_t data[6] = {uint8_t(batteryMv), uint8_t(batteryMv >> 8),
                    uint8_t(batteryAdc), uint8_t(batteryAdc >> 8),
                    uint8_t(batteryCharging), uint8_t(usbPower)};
  batteryVoltage.write(data, sizeof(data));
  uint8_t previous = batteryPct;
  batteryPct = batteryPercent(batteryMv);
  batteryLevel.write8(batteryPct);
  if (previous != batteryPct) for (auto& peer : clients.slots)
    if (peer.handle != 0xffff && batteryLevel.notifyEnabled(peer.handle))
      notify(peer.handle, batteryLevel, &batteryPct, 1);
}

void sampleImu(uint32_t now) {
  uint8_t status, raw[12];
  if (!readRegisters(0x1E, &status, 1)) { ++imuErrors; return; }
  if ((status & 3) != 3) return; // Only consume fresh accel AND gyro data.
  if (!readRegisters(0x22, raw, sizeof(raw))) { ++imuErrors; return; }
  gx = signedWord(raw) * 0.035f;
  gy = signedWord(raw + 2) * 0.035f;
  gz = signedWord(raw + 4) * 0.035f;
  ax = signedWord(raw + 6) * 0.000244f;
  ay = signedWord(raw + 8) * 0.000244f;
  az = signedWord(raw + 10) * 0.000244f;
  ++samples; lastSample = now;
  uint32_t sample_us = micros();
  gyroCadence.update(gy, sample_us);
  streamImu(raw, sample_us);
}

uint8_t cadence(uint32_t now) {
  if (fixedCadence) return fixedCadence;
  if (!imuReady || !samples || uint32_t(now - lastSample) > 250) return 0;
  return gyroCadence.cadence(micros());
}

void publish(uint32_t now) {
  uint8_t spm = cadence(now);
  // RSC: flags, speed (m/s * 256, little endian), cadence (steps/min).
  // Mandatory speed uses a placeholder step length; no optional features claimed.
  uint16_t speed = uint16_t(lroundf(spm * STEP_LENGTH_M / 60.0f * 256.0f));
  uint8_t packet[4] = {0, uint8_t(speed), uint8_t(speed >> 8), spm};
  memcpy(cadencePacket, packet, sizeof(packet));
  measurement.write(packet, sizeof(packet));
  for (auto& peer : clients.slots)
    if (peer.handle != 0xffff) peer.cadencePending = true;
}

void flushCadence() {
  for (auto& peer : clients.slots) {
    if (peer.handle == 0xffff || !peer.cadencePending) continue;
    if (!measurement.notifyEnabled(peer.handle)) { peer.cadencePending = false; continue; }
    uint32_t result = notify(peer.handle, measurement, cadencePacket, sizeof(cadencePacket));
    // Give cadence priority over raw samples; retry queue congestion next loop.
    if (result == NRF_ERROR_RESOURCES) continue;
    peer.cadencePending = false;
    if (result == NRF_SUCCESS) ++notifications; else ++notifyErrors;
  }
}

bool cadenceSubscribed() {
  for (auto& peer : clients.slots)
    if (peer.handle != 0xffff && measurement.notifyEnabled(peer.handle)) return true;
  return false;
}

void serialCommands() {
  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\r') continue;
    if (c != '\n') {
      if (commandLength < sizeof(command) - 1) command[commandLength++] = c;
      else commandOverflow = true;
      continue;
    }
    if (commandOverflow) { commandLength = 0; commandOverflow = false; continue; }
    command[commandLength] = 0;
    unsigned value; char extra;
    if (!strcmp(command, "imu")) { fixedCadence = 0; resetEstimator(); }
    else if (sscanf(command, "mock %3u %c", &value, &extra) == 1 && value >= 1 && value <= 255)
      fixedCadence = value;
    else if (!strcmp(command, "stop")) { fixedCadence = 0; resetEstimator(); }
    else if (Serial && Serial.availableForWrite() >= 40)
      Serial.println("Commands: imu | mock 1..255 | stop");
    commandLength = 0;
  }
}

void telemetry(uint32_t now) {
  if (!Serial || logOffset < logLength) return;
  int length = snprintf(logBuffer, sizeof(logBuffer),
    "{\"ms\":%lu,\"mode\":\"%s\",\"imu_ok\":%s,\"who\":%u,\"samples\":%lu,"
    "\"imu_errors\":%lu,\"a_g\":[%.4f,%.4f,%.4f],\"gyro_dps\":[%.2f,%.2f,%.2f],"
    "\"strikes\":%lu,\"cadence_spm\":%u,\"connected\":%s,\"subscribed\":%s,"
    "\"notifications\":%lu,\"notify_errors\":%lu,\"battery_mv\":%u,"
    "\"battery_pct\":%u,\"connections\":%u,\"charging\":%s,\"usb_power\":%s}\n",
    (unsigned long)now, fixedCadence ? "mock" : "imu", imuReady ? "true" : "false",
    whoAmI, (unsigned long)samples, (unsigned long)imuErrors, ax, ay, az, gx, gy, gz,
    (unsigned long)gyroCadence.cycles, cadence(now), Bluefruit.connected() ? "true" : "false",
    cadenceSubscribed() ? "true" : "false", (unsigned long)notifications,
    (unsigned long)notifyErrors, batteryMv, batteryPct, Bluefruit.Periph.connected(), batteryCharging ? "true" : "false",
    usbPower ? "true" : "false");
  logLength = length > 0 && length < int(sizeof(logBuffer)) ? length : 0;
  logOffset = 0;
}

void flushTelemetry() {
  if (!Serial) { logLength = logOffset = 0; return; }
  // Never wait for USB: a client can hold DTR high without draining the port.
  int available = Serial.availableForWrite();
  if (available > 0 && logOffset < logLength) {
    size_t count = min(uint16_t(available), uint16_t(logLength - logOffset));
    logOffset += Serial.write(reinterpret_cast<uint8_t*>(logBuffer + logOffset), count);
  }
}

void setup() {
  // Keep the divider enabled (P0.14 LOW), including while USB charges the battery.
  digitalWrite(VBAT_ENABLE, LOW); pinMode(VBAT_ENABLE, OUTPUT);
  pinMode(PIN_VBAT, INPUT); pinMode(23, INPUT);
  analogReadResolution(12); analogReference(AR_INTERNAL_3_0);
  analogSampleTime(40); // Microseconds; high-impedance battery divider.
  analogOversampling(4);
  Serial.begin(115200); // Never wait for USB: standalone battery operation.
  // 20-byte packets need no MTU negotiation; buffer short radio scheduling bursts.
  Bluefruit.configPrphConn(23, 6, 64, 1);
  Bluefruit.begin(2, 0);
  imuReady = startImu();
  digitalWrite(LED_RED, imuReady ? HIGH : LOW);
  Bluefruit.autoConnLed(false);
  Bluefruit.setName("Carl Foot Pod");
  Bluefruit.setTxPower(4);
  Bluefruit.Periph.setConnInterval(12, 24); // 15–30 ms, enough for the 104 Hz stream.
  Bluefruit.Periph.setConnectCallback(collectionConnected);
  Bluefruit.Periph.setDisconnectCallback(collectionDisconnected);
  deviceInfo.setManufacturer("Carl");
  deviceInfo.setModel("XIAO nRF52840 Sense");
  deviceInfo.setSoftwareRev("0.4.0");
  deviceInfo.begin();
  rsc.begin();
  measurement.setProperties(CHR_PROPS_NOTIFY);
  measurement.setPermission(SECMODE_OPEN, SECMODE_NO_ACCESS);
  measurement.setFixedLen(4);
  measurement.begin();
  feature.setProperties(CHR_PROPS_READ);
  feature.setPermission(SECMODE_OPEN, SECMODE_NO_ACCESS);
  feature.setFixedLen(2); feature.begin(); feature.write16(0);
  location.setProperties(CHR_PROPS_READ);
  location.setPermission(SECMODE_OPEN, SECMODE_NO_ACCESS);
  location.setFixedLen(1); location.begin(); location.write8(6); // Left foot.
  publish(millis());
  collection.begin();
  imuData.setProperties(CHR_PROPS_NOTIFY);
  imuData.setPermission(SECMODE_OPEN, SECMODE_NO_ACCESS);
  imuData.setFixedLen(20); imuData.begin();
  collectionControl.setProperties(CHR_PROPS_WRITE);
  collectionControl.setPermission(SECMODE_NO_ACCESS, SECMODE_OPEN);
  collectionControl.setFixedLen(1);
  collectionControl.setWriteCallback(collectionCommand, false);
  collectionControl.begin();
  collectionStatus.setProperties(CHR_PROPS_READ);
  collectionStatus.setPermission(SECMODE_OPEN, SECMODE_NO_ACCESS);
  collectionStatus.setFixedLen(16);
  collectionStatus.setReadAuthorizeCallback(readCollectionStatus, false);
  collectionStatus.begin();
  batteryVoltage.setProperties(CHR_PROPS_READ);
  batteryVoltage.setPermission(SECMODE_OPEN, SECMODE_NO_ACCESS);
  batteryVoltage.setFixedLen(6); batteryVoltage.begin();
  batteryService.begin();
  batteryLevel.setProperties(CHR_PROPS_READ | CHR_PROPS_NOTIFY);
  batteryLevel.setPermission(SECMODE_OPEN, SECMODE_NO_ACCESS);
  batteryLevel.setFixedLen(1);
  batteryLevel.setUserDescriptor("Battery level (estimated)");
  batteryLevel.begin();
  readBattery();
  Bluefruit.Advertising.addFlags(BLE_GAP_ADV_FLAGS_LE_ONLY_GENERAL_DISC_MODE);
  Bluefruit.Advertising.addAppearance(0x0441); // Running/walking sensor, in shoe.
  Bluefruit.Advertising.addService(rsc);
  Bluefruit.Advertising.addName();
  Bluefruit.ScanResponse.addService(collection);
  Bluefruit.Advertising.restartOnDisconnect(true);
  Bluefruit.Advertising.setInterval(160, 244); // 100–152.5 ms; leave airtime for both links.
  Bluefruit.Advertising.setFastTimeout(30);
  Bluefruit.Advertising.start(0); // Continue advertising at rest, without USB.
}

void loop() {
  static uint32_t sampleTimer = 0, publishTimer = 0, logTimer = 0, advertisingTimer = 0;
  uint32_t now = millis();
  serialCommands();
  flushCadence();
  if (imuReady && uint32_t(now - sampleTimer) >= 5) {
    sampleTimer = now; sampleImu(now);
  }
  if (uint32_t(now - publishTimer) >= 1000) {
    publishTimer = now; readBattery(); publish(now);
  }
  if (uint32_t(now - logTimer) >= 200) {
    logTimer = now; telemetry(now);
  }
  if (uint32_t(now - advertisingTimer) >= 200) {
    advertisingTimer = now;
    // Bluefruit's automatic restart only handles the last client disconnect.
    if (Bluefruit.Periph.connected() < 2 && !Bluefruit.Advertising.isRunning())
      Bluefruit.Advertising.start(0);
  }
  flushTelemetry();
  delay(1);
}
