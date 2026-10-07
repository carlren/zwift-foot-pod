# License scope and upstream notices

The [MIT license](LICENSE) covers project-owned software and its associated
software documentation: the firmware application and gyro detector, Android app,
desktop dashboard/collector, development/check scripts, and original Python CAD
generation/render scripts. Copyright (c) 2026 Carl Yuheng Ren.

Third-party components retain their own licenses. The root MIT license does not
relicense the board/SDK, vendor CAD, or upstream material. Photos, workout datasets
and STL/STEP assets are outside this software license grant.

## Components used by the software

| Component | Use | Upstream licensing |
| --- | --- | --- |
| Seeed nRF52 Boards 1.1.13 / Arduino-Adafruit core | Board startup, GPIO, ADC, USB and runtime | Core license is LGPL-2.1-or-later; individual bundled files/libraries have their own notices. [Source](https://github.com/Seeed-Studio/Adafruit_nRF52_Arduino). |
| Adafruit Bluefruit52Lib | BLE peripheral services and connections | MIT; Copyright (c) 2016 Adafruit Industries. [License copy](LICENSES/Adafruit-Bluefruit-MIT.txt). |
| Adafruit TinyUSB Arduino | USB serial support | MIT; Copyright (c) 2019 Ha Thach for Adafruit Industries. [License copy](LICENSES/Adafruit-TinyUSB-MIT.txt). |
| Nordic nrfx TWIM driver | Internal IMU I²C bus | BSD-3-Clause; Copyright (c) 2015–2020 Nordic Semiconductor ASA. [License copy](LICENSES/Nordic-nrfx-BSD-3-Clause.txt). |
| Nordic SoftDevice S140 API | BLE stack API on the nRF52840 | Nordic's supplied license, including its Nordic-chip usage condition. [API header notice](LICENSES/Nordic-SoftDevice-API.txt). This project does not relicense the SoftDevice. |
| Gradle wrapper | Android build launcher | Apache-2.0; existing notices remain in `gradlew`, `gradlew.bat` and the wrapper JAR. [License copy](LICENSES/Apache-2.0.txt). |
| Zephyr default LiPo OCV table | Battery-percent voltage breakpoints | Apache-2.0; Copyright 2024 Embeint Inc. [Upstream table](https://github.com/zephyrproject-rtos/zephyr/blob/main/include/zephyr/dt-bindings/battery/battery.h). |

The battery table's microvolt values were rounded to millivolts in
`footpod/companion.h`; the interpolation code is project-owned. The source table
is based on Analog Devices Application Note 4189, Table 1. Its Apache-2.0
attribution and [license text](LICENSES/Apache-2.0.txt) are retained here.

The board core/libraries are installed by the build toolchain; their sources have
not been modified in this project. `footpod/imu_bus.c` includes the installed
Nordic driver so it is compiled into the application. Thus the firmware does use
vendor software, even though we wrote the application/algorithm ourselves. Keep
the pinned SDK's upstream notices and applicable source/relinking terms with
firmware distributions; this document is not a complete SDK bill of materials.

## Enclosure board reference

`enclosure/low-profile-v5/references/sense-official-XIAO-nRF52840 v15.step` is an
unchanged, third-party board shape used for enclosure fit checks. The same file is
inside the original enclosure ZIP. It is not Seeed firmware code and is not
covered by the project MIT license. See the [enclosure provenance](enclosure/README.md#provenance-and-licensing)
for its source and the supplied package's licensing information.
