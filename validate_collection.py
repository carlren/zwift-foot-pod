"""Check the Bluetooth-only collector and return to normal cadence publishing."""
import asyncio
import csv
import json
import math
from pathlib import Path
from types import SimpleNamespace

from bleak import BleakClient
from collect import PACKET, decode_status, record, SERVICE, DATA, CONTROL, STATUS
from validate import find_pod, MEAS


async def main():
    assert PACKET.unpack(PACKET.pack(0xFFFFFFFF, 0xFFFFFFFF, -32768, 32767, -1, 0, 1, 4096))[2:] == (-32768, 32767, -1, 0, 1, 4096)
    for invalid in (b"", bytes(16), b"\x01\xff" + bytes(14)):
        try:
            decode_status(invalid)
        except ValueError:
            pass
        else:
            raise AssertionError("Malformed status accepted")
    args = SimpleNamespace(seconds=20, label="collection-validation", foot="left",
                           reference_spm=None, speed_kph=None)
    # No serial port is opened: all control and IMU data use Bluetooth.
    directory, report = await record(args)
    assert report["completed"] and 95 < report["received_hz"] < 110
    assert report["samples"] > 1900 and report["missing_packets"] < report["samples"] * 0.01
    assert report["status_after"]["imu_errors"] == report["status_before"]["imu_errors"]
    assert not report["status_after"]["collecting"] and not report["status_after"]["subscribed"]
    with (directory / "imu.csv").open() as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == report["samples"]
    gravity = sum(math.sqrt(sum(float(r[k]) ** 2 for k in ("ax_g", "ay_g", "az_g"))) for r in rows) / len(rows)
    assert 0.7 < gravity < 1.3, "Expected a stationary board"
    device = await find_pod()
    imu_frames, cadence_frames = [], []
    async with BleakClient(device) as client:
        assert client.services.get_service(SERVICE)
        await client.start_notify(DATA, lambda _, p: imu_frames.append(bytes(p)))
        await client.write_gatt_char(CONTROL, b"\x09", response=True)
        await client.start_notify(MEAS, lambda _, p: cadence_frames.append(bytes(p)))
        await asyncio.sleep(3.2)
        status = decode_status(await client.read_gatt_char(STATUS))
        assert not status["collecting"] and not imu_frames, "Stream ran without a valid start command"
        assert len(cadence_frames) >= 3 and all(len(p) == 4 for p in cadence_frames)
    report["validation"] = "PASS: packet format, Bluetooth-only capture, CSV, gaps, stop, reconnect, cadence"
    report["mean_acceleration_g"] = round(gravity, 4)
    report["recording"] = str(directory)
    (Path(__file__).resolve().parent / "validation/collection-report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(report["validation"], flush=True)


if __name__ == "__main__":
    asyncio.run(main())
