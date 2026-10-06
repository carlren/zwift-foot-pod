"""Read battery voltage, ADC count, charger state, and USB power over Bluetooth."""
import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
import struct

from bleak import BleakClient
from validate import find_pod
from collect import STATUS, decode_status

BATTERY = "e85b0005-6d10-4a22-90c5-c813f72b1357"


async def main():
    device = await find_pod()
    report = {"checked_utc": datetime.now(timezone.utc).isoformat(), "address": device.address,
              "readings": []}
    async with BleakClient(device) as client:
        report["firmware"] = bytes(await client.read_gatt_char(
            "00002a28-0000-1000-8000-00805f9b34fb")).decode()
        for index in range(5):
            payload = await client.read_gatt_char(BATTERY)
            if len(payload) != 6:
                raise ValueError("Battery diagnostic must contain 6 bytes")
            mv, adc, charging, usb = struct.unpack("<HHBB", payload)
            assert adc <= 4095 and charging in (0, 1) and usb in (0, 1)
            assert abs(mv - round(adc * 3000 / 4096 * 1510 / 510)) <= 1
            row = dict(voltage_v=mv / 1000, adc_raw=adc, charging=bool(charging), usb_power=bool(usb))
            report["readings"].append(row)
            print(json.dumps(row), flush=True)
            if index < 4:
                await asyncio.sleep(1.1)
        report["imu"] = decode_status(await client.read_gatt_char(STATUS))
    report["readable"] = all(2.5 <= r["voltage_v"] <= 4.4 for r in report["readings"])
    output = Path(__file__).resolve().parent / "validation/battery-report.json"
    output.write_text(json.dumps(report, indent=2) + "\n")
    print("Battery voltage readable:", report["readable"], "— saved", output, flush=True)


if __name__ == "__main__":
    asyncio.run(main())
