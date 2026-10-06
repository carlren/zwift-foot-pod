# Carl Foot Pod — cadence and Bluetooth IMU collection

Firmware for the original Seeed XIAO nRF52840 Sense, publishing directly over
Bluetooth as **Carl Foot Pod**. No computer or relay is needed after boot.

Firmware version 0.2.1. Cadence detection and speed are placeholders. Zwift pairing
and changing cadence have been confirmed by Carl. Battery life and battery-only
power have not been tested here; collection control and data use Bluetooth only.

## Live visualization app

```sh
rtk .venv/bin/python dashboard.py
```

Open **http://127.0.0.1:8766** on this computer. Choose an activity label, duration,
shoe side, and optional reference cadence, then click **Connect & record**. Disconnect
the pod from Zwift first. **Stop & save** stops collection and releases the pod.
The server uses Python's standard library and the existing BLE recorder; no new
dependencies or firmware update are needed. It only listens on this computer.

The dashboard shows all six IMU axes, acceleration magnitude, foot-strike markers,
estimated total steps/min, optional reference cadence, sample rate and packet gaps.
The shoe animation and normalized curve illustrate the **estimated one-foot rhythm**,
not reconstructed foot position. Battery voltage and charger status are read at
connection time; they are not continuously refreshed during the high-rate stream.

The fit is explicitly the current **threshold prototype**, matching the firmware's
1.30 g detection, 1.08 g rearm, minimum stride interval and cadence smoothing.
It is not a trained or validated gait algorithm. The live detector settings can be
tuned while recording; changes reset the detector and apply to subsequent samples.
The displayed history retains the fit that was calculated at each sample's time.
Replace `Detector.update()` in `dashboard.py` as the real algorithm is developed.

All raw samples remain in `imu.csv` and `session.json`. The dashboard also saves
`fit.csv` with every sample's acceleration magnitude, foot-strike decision, cadence,
phase, and detector settings, plus `fit-settings.json` with configuration changes.
Download the raw data, fit, and session details through the links in the app.
The display shows the latest 20 seconds, updating five times per second; recording
keeps every received sample. If the connection fails, partial files are retained
and the app reports the error. Click **Connect & record** to start a new session.

```sh
rtk .venv/bin/python test_dashboard.py
```

This verifies cadence on synthetic 109/180 spm signals, the stop timeout, extra-strike
rejection, request validation, live snapshots and fit CSV output. The browser and
real-pod integration check is recorded in `validation/dashboard-report.json`.

## Read the battery voltage

```sh
rtk .venv/bin/python battery.py
```

This reads five measurements over Bluetooth and saves `validation/battery-report.json`.
The board also includes `battery_mv`, `charging`, and `usb_power` in USB telemetry.
Voltage is sampled once per second from AIN7 / P0.31, with the battery divider enabled
by keeping P0.14 LOW. The 12-bit ADC uses the internal 3.0 V reference, a 40 µs sample
time, and 4× oversampling. The schematic's 1 MΩ / 510 kΩ divider gives:
`battery_mV = round(adc_count * 3000 / 4096 * 1510 / 510)`.
This is an uncalibrated voltage reading, not a battery percentage or a current reading.
The charger output on P0.17 is active LOW; USB power presence comes from VBUSDETECT.
Charger-current settings are unchanged.

The read-only characteristic `e85b0005-6d10-4a22-90c5-c813f72b1357` is in the existing
collection service. Its six bytes are `<HHBB`: battery millivolts, raw ADC count,
charger-active flag (0/1), and USB-present flag (0/1). The existing IMU data and
status formats are unchanged. Voltage while USB is connected confirms that the
battery input is readable; battery-only powering still needs a separate test.

## Record IMU data on battery

The board boots in normal cadence mode. The computer's recorder starts and stops
collection over Bluetooth, with no USB commands needed. Collection temporarily
pauses RSC publishing; finishing or disconnecting returns the pod to cadence mode.
Only one Bluetooth client can connect: disconnect the pod from Zwift before recording.
Keep this computer within Bluetooth range of the shoe.

From a terminal on this computer:

```sh
cd /home/carlren/Documents/zwift-foot-pod-firmware
rtk .venv/bin/python collect.py --seconds 15 --label stationary
rtk .venv/bin/python collect.py --seconds 90 --label walking --foot left
rtk .venv/bin/python collect.py --seconds 90 --label running --foot left
```

Add `--speed-kph 5` for a known treadmill speed, or `--reference-spm 109` for a known
total step rate. These are annotations, not pod measurements. A reference step count
or video is useful for checking the future algorithm against actual foot strikes.
Use a new recording label for each speed, mounting position, or activity. Keep the
pod secured in the same orientation on the shoe during each recording.

Each session creates a new folder under `recordings/` containing:

- `imu.csv`: all received samples at approximately 104 Hz, with sequence numbers,
  device microseconds, unwrapped session time, host receive timestamps, raw gyro /
  accelerometer values, and converted degrees/second / g values.
- `session.json`: activity label, shoe side, optional reference cadence / speed,
  firmware version, sample rate, packet gaps, saturation counts, sensor errors,
  and whether the recording finished successfully.

Ctrl+C stops early and retains the partial recording. Radio disconnection, stalled
data, malformed packets, or a device reset end the capture and preserve an error
in the session file; run the recorder again for a fresh session. Bluetooth
notifications are not guaranteed delivery. The pod keeps sampling during congestion
and the recorder counts gaps. Acquisition timestamps, rather than host arrival times,
are the timing reference for algorithm development. No samples are stored on the pod;
data outside computer radio range cannot be recovered.

The BLE protocol has service `e85b0001-6d10-4a22-90c5-c813f72b1357`, data / control /
status UUIDs with suffix numbers `0002`, `0003`, `0004` in the same base. A data packet
is 20 bytes, `<II6h`: sample sequence, device microseconds, gyro X/Y/Z, accel X/Y/Z.
Both counters are unsigned 32-bit and wrap. Scale factors remain 0.035 degrees/second
and 0.000244 g per count. Write byte `01` to control to start, `00` to stop; subscribe
to data first. The 16-byte status is `<BBBBIII`: version=1, flags (IMU ready=1,
collection enabled=2, data subscribed=4), sensor identity, reserved=0, cumulative
sent packets, rejected packets, and sensor read errors.

```sh
rtk .venv/bin/python validate_collection.py # 20-second Bluetooth-only hardware check
```

This also verifies CSV output and return to cadence mode after disconnect/reconnect.
Evidence is saved to `validation/collection-report.json`. USB can provide power for
the bench check; the collector never opens the USB serial port.

## Current behavior

- Reads the LSM6DS3TR-C accelerometer and gyro at 104 Hz over the internal I²C bus.
  Acceleration is in g (±8 g), angular velocity in degrees/second (±1000 dps).
- Checks sensor identity and configuration, reads only fresh data, and stops reporting
  cadence when sensor data is stale. I²C has a 50 ms timeout; a stalled sensor cannot
  block Bluetooth indefinitely. Reboot to recover after a bus timeout.
- The mock detector uses acceleration magnitude, 1.30 g detection / 1.08 g rearm,
  a 450 ms minimum stride interval, smoothing, and a 3 second stop timeout. It assumes
  one pod on one shoe and doubles the detected foot-strike rate to get total steps/min.
  Shaking the board can trigger it; it is not a validated gait algorithm.
- In cadence mode, publishes a four-byte Running Speed and Cadence measurement once per second,
  including zero cadence while idle. It advertises continuously and automatically
  advertises again after disconnection. One Bluetooth client is supported at a time.
- Starts without waiting for a USB serial connection. USB prints JSON telemetry at
  5 Hz while a serial host is connected and reading. A stalled reader can lose
  telemetry updates but cannot pause the IMU or Bluetooth. The red LED indicates
  failed IMU startup.

## Bluetooth format

| Item | UUID / value |
| --- | --- |
| Advertised service | RSC `1814` |
| RSC Measurement (notify + CCCD) | `2A53` |
| RSC Feature (read) | `2A54`, value `0000` (no optional features) |
| Sensor Location (read) | `2A5D`, value `06` (left foot) |
| Device information | `180A` |
| Appearance | `0441` (running/walking sensor in shoe) |

Measurement: `[flags=0, speed_low, speed_high, cadence_spm]`.
Speed is an unsigned little-endian integer in units of 1/256 m/s. For now it is
`cadence * 0.70 meters / 60 seconds`; this is mock speed, not measured speed.
Only the mandatory fields are sent; stride length, distance, running-status detection,
and calibration control are not claimed.

In Zwift's **RUN** pairing screen, try **Carl Foot Pod** under **CADENCE** and keep
your existing treadmill/speed source under **RUN SPEED**. Selecting this pod for
speed uses the placeholder speed estimate. Our Bluetooth validator disconnects at
the end so the pod is available for Zwift.

## USB commands

Open the board's serial port at 115200 baud and send a newline after each command:

| Command | Effect |
| --- | --- |
| `imu` | Return to the mock IMU detector and reset its cadence estimate |
| `mock 109` | Publish fixed 109 steps/min; IMU sampling continues |
| `mock 180` | Publish fixed 180 steps/min |
| `stop` | Clear fixed mode and reset the detector; new motion can trigger cadence again |

Fixed cadence accepts 1–255. Commands are temporary; reboot always starts IMU mode.
The constants near the top of `footpod/footpod.ino` are the calibration knobs.
Replace `estimateCadence()` when developing the real algorithm. `validation/imu.jsonl`
contains the first stationary capture; raw gyro and acceleration remain available
through serial for walking/running data collection.

## Build, flash, and validate

Installed locally: Arduino CLI 1.4.1, Seeed nRF52 Boards 1.1.13, and `.venv`
dependencies pinned in `requirements.txt`. Bluefruit and the Nordic I²C driver are
provided by the board package. No board-package files were edited.

```sh
cd /home/carlren/Documents/zwift-foot-pod-firmware
rtk .venv/bin/python program.py          # compile only
rtk .venv/bin/python program.py --upload # compile and flash application
rtk .venv/bin/python validate.py         # USB + real Bluetooth hardware checks
```

`program.py` enables the bundled Nordic TWIM driver using build flags. The small
`imu_bus.c` file builds the vendor source that Seeed otherwise omits from `core.a`.
The IMU supply GPIO uses high drive, matching Seeed's own IMU library. `program.py`
only grants temporary serial-node access with `sudo -n setfacl` if needed; it does
not change global device permissions or group membership. Close serial monitors
before programming. If automatic bootloader entry fails, double tap RESET and retry.
The existing bootloader is retained. Compiled artifacts are in `build/`.

`validate.py` expects a stationary board and checks sensor identity, sample rate,
gravity, zero I²C errors, RSC discovery/metadata/CCCD, exact packets at 109/180/255
steps/min, rejected out-of-range input, zero heartbeat with the serial host closed,
and disconnect/reconnect. It leaves the board in IMU mode and saves evidence in
`validation/report.json`, `validation/imu.jsonl`, and `validation/ble.jsonl`.
Closing the serial session tests independence from the USB host, not battery power.

For a fresh toolchain, obtain Arduino CLI from Arduino's official downloads, place it
at `tools/arduino-cli`, then run:

```sh
rtk tools/arduino-cli core update-index --additional-urls https://files.seeedstudio.com/arduino/package_seeeduino_boards_index.json
rtk tools/arduino-cli core install Seeeduino:nrf52@1.1.13 --additional-urls https://files.seeedstudio.com/arduino/package_seeeduino_boards_index.json
rtk python3 -m venv .venv
rtk .venv/bin/pip install -r requirements.txt
```

## References

- [Seeed board documentation](https://wiki.seeedstudio.com/XIAO_BLE/)
- [Seeed battery-divider schematic](https://files.seeedstudio.com/wiki/XIAO-BLE/Seeed_Studio_XIAO_nRF52840_PDF.pdf)
- [Seeed IMU library (including the high-drive supply configuration)](https://github.com/Seeed-Studio/Seeed_Arduino_LSM6DS3/blob/master/LSM6DS3.cpp)
- [ST LSM6DS3TR-C datasheet](https://www.st.com/resource/en/datasheet/lsm6ds3tr-c.pdf)
- [Bluetooth Running Speed and Cadence service](https://www.bluetooth.com/specifications/specs/running-speed-and-cadence-service/)
- [Zwift running device pairing](https://support.zwift.com/de/-ry2NdSw9B)
- [Bleak Bluetooth client API](https://bleak.readthedocs.io/en/latest/api/client.html)
