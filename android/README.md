# Foot Pod Lab for Android

Personal companion app for Carl's XIAO Sense foot pod, firmware **0.4.0 or newer**.
Version **1.0.1**, package `com.carlren.footpod`. Native Java / Android framework,
no runtime third-party libraries, account sign-in or Internet permission. Minimum
Android 12; targets Android 15 and can run on newer Android phones.

## Install and use

Download [Foot-Pod-Lab-1.0.1.apk](https://drive.google.com/file/d/1NDdZ-bwayQZ8dlKcvDCeHdjqc7yNuZNr/view?usp=drivesdk) on the Galaxy,
install it over the existing app to keep recordings, and allow installation from that app if Android prompts. Open **Foot Pod
Lab**, grant **Nearby devices**, and allow notifications for connection / recording
status. Turn on Bluetooth and power the pod. No Android Settings pairing is needed.

1. Tap **Connect**. Live gyro / accelerometer graphs and cadence appear immediately;
   connecting creates no recording files. Battery voltage is refreshed every five
   seconds, while estimated battery percentage also receives change notifications.
   A dedicated **Foot pod battery** card shows a fill bar, estimated percentage,
   voltage and charging state. The bar is green above 50%, amber at 21–50%, red at
   0–20%. Unknown percentage stays “—”; disconnected readings are labeled “last read”.
2. Choose duration (default 60 seconds), label, optional reference steps/min and
   treadmill speed in mph. Tap **Record** only when the preview looks right.
3. The countdown stops recording automatically. **Stop recording** saves early;
   both keep preview running. Recording uses a foreground connected-device service
   and a bounded wake lock to continue when the screen is locked.
4. Count steps from both feet. After recording, enter **Counted steps** and tap
   **Calculate & save reference**. It uses the actual saved device duration. This
   annotates the session; it does not alter the cadence detector.
5. **Share recording ZIP**, then choose Drive (or another sharing target). A ZIP
   contains `imu.csv`, `fit.csv` and `session.json`. Older sessions remain available
   under **Choose recording**. The app does not automatically upload recordings.
6. **Disconnect** releases only the phone's BLE connection and saves any active
   recording. Zwift on a separate device can remain connected to the pod.

Both graphs show the latest 20 seconds. Cyan / amber / violet are X / Y / Z; the
gyro graph also shows filtered Y in white and estimated stride markers in green.
The cadence headline comes from the pod's RSC stream; the app's **Gyro fit** runs
the same signed Y-axis detector for comparison. The app does not change firmware
mode or calibration constants. Acceleration is shown as a secondary signal.
Battery percentage is a voltage-based estimate, particularly under load / charge.

Raw data stay in private app storage. Stopping, losing Bluetooth, or encountering
bad packets preserves partial recordings and marks failures in metadata. Writes
are flushed and checkpointed roughly every second; force-stopping the app can
lose data still in memory. Reopening retains the raw files and marks interrupted
sessions incomplete. Uninstalling the app removes its recordings: share wanted
sessions first. No samples are stored on the board.

## Build

This computer has JDK 17 at `/home/carlren/android-dev/jdk-17` and Android SDK at
`/home/carlren/android-dev/android-sdk`. The Gradle wrapper pins 8.10.2 and the
Android plugin pins 8.7.2. Compile SDK / build tools are 35.

```sh
rtk python3 android/build.py
```

The build script accepts `JAVA_HOME` / `ANDROID_HOME` on another computer. It
builds the release, runs Android lint, verifies its APK signature, and copies it
to `android/dist/Foot-Pod-Lab-1.0.1.apk` with a SHA-256 checksum. Its persistent
personal signing key and password are outside this repository in
`~/.local/share/foot-pod-lab/`, with restricted permissions. Preserve those files
privately to sign future updates; never upload or commit them. Only the APK is
distributed. Generated APKs, caches and machine paths are ignored by Git.

## Checks and limitations

```sh
rtk .venv/bin/python android/check.py
```

This compiles the exact Java protocol / detector / recording-window code on the
host, checks malformed packets, signed raw values, unsigned sequence/time wraps,
packet gaps, record boundaries, countdown, reference calculation, synthetic cadence
and stop timeout. It replays all five original walking recordings and checks every
stride decision and fit against the validated desktop detector; the raw reference
recordings are included in this repository. Evidence is in
`validation/android-protocol-report.json`.

`app/src/androidTest/.../TestProbe.java` is a dependency-free Android instrumentation
check for the actual CSV / fit / metadata writer, reference annotation, ZIP export,
read-only sharing provider, traversal rejection, partial sessions and interrupted
session recovery. Synthetic inputs occur only in this test APK, never in the
delivered application. To run on a disposable emulator using debug builds:

```sh
rtk ./gradlew assembleDebug assembleDebugAndroidTest
rtk adb -s EMULATOR_SERIAL install -r app/build/outputs/apk/debug/app-debug.apk
rtk adb -s EMULATOR_SERIAL install -r app/build/outputs/apk/androidTest/debug/app-debug-androidTest.apk
rtk adb -s EMULATOR_SERIAL shell am instrument -w com.carlren.footpod.test/com.carlren.footpod.TestProbe
```

Do not replace a release installation containing wanted recordings with a debug
build: the signing keys differ. The supplied APK was signature-verified, installed,
launched and visually checked in an Android 15 emulator. Native Android storage
checks passed there. The [user-supplied Galaxy screenshot](../docs/images/android-live-preview.jpg)
now shows live BLE preview on the physical phone: 114 steps/min, 105.0 Hz, 1,157
samples with zero displayed gaps, and battery power at 4.144 V / approximately 96%.
It does not establish screen-lock recording, battery runtime or a sustained test
of two physical phone-plus-Zwift radio links. Firmware 0.4.0's prior bench check
exercised concurrent cadence / raw IMU / battery data using one computer central.

Android implementation follows the official guidance for
[BLE permissions](https://developer.android.com/develop/connectivity/bluetooth/bt-permissions),
[background BLE connections](https://developer.android.com/develop/connectivity/bluetooth/ble/background),
and [edge-to-edge window insets](https://developer.android.com/develop/ui/views/layout/edge-to-edge).

## License

The project-owned Android application is [MIT-licensed](../LICENSE).
See [upstream notices and license scope](../THIRD_PARTY_NOTICES.md).
