"""Hardware check: live IMU, RSC metadata/packets, no-USB-host streaming, reconnect."""
import asyncio
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import statistics
import struct
import time

import serial
from bleak import BleakClient, BleakScanner
from program import board, access

ROOT = Path(__file__).resolve().parent
BASE = "-0000-1000-8000-00805f9b34fb"
RSC, MEAS, FEATURE, LOCATION = (f"0000{u}" + BASE for u in ("1814", "2a53", "2a54", "2a5d"))


async def find_pod():
    device = await BleakScanner.find_device_by_filter(
        lambda d, a: a.local_name == "Carl Foot Pod" and RSC in a.service_uuids,
        timeout=15,
    )
    assert device is not None, "Carl Foot Pod not advertising RSC"
    return device


def telemetry(handle, seconds):
    rows = []
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        line = handle.readline().decode(errors="replace").strip()
        if not line.startswith("{"):
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue # A serial session can begin in the middle of a queued line.
    return rows


async def main():
    report = {"started_utc": datetime.now(timezone.utc).isoformat(), "result": "FAIL"}
    port = board()
    assert port.pid == 0x8045, "Board is in bootloader"
    access(port.device)
    handle = serial.Serial(port.device, 115200, timeout=0.3)
    packets = []
    rows = []

    def notification(_, payload):
        assert len(payload) == 4, f"RSC length {len(payload)}"
        flags, speed, cadence = struct.unpack("<BHB", payload)
        assert flags == 0, f"Unadvertised optional features: {flags}"
        packets.append({"time": time.monotonic(), "raw": payload.hex(),
                        "cadence_spm": cadence, "speed_raw": speed})

    try:
        handle.write(b"imu\n")
        rows = await asyncio.to_thread(telemetry, handle, 3)
        assert len(rows) >= 10, "Missing serial telemetry"
        assert all(r["imu_ok"] and r["who"] == 0x6A and r["imu_errors"] == 0 for r in rows)
        rate = (rows[-1]["samples"] - rows[0]["samples"]) / ((rows[-1]["ms"] - rows[0]["ms"]) / 1000)
        assert 80 < rate < 110, f"IMU rate: {rate} Hz"
        magnitude = statistics.mean(math.sqrt(sum(v*v for v in r["a_g"])) for r in rows)
        assert 0.7 < magnitude < 1.3, f"Expected stationary gravity, got {magnitude} g"
        report["imu"] = {"who_am_i": "0x6a", "sample_rate_hz": round(rate, 2),
                         "mean_acceleration_g": round(magnitude, 4), "errors": rows[-1]["imu_errors"]}
        print("IMU:", report["imu"], flush=True)
        device = await find_pod()
        report["address"] = device.address
        report["advertised_name"] = device.name
        async with BleakClient(device) as client:
            assert client.services.get_service(RSC)
            characteristic = client.services.get_characteristic(MEAS)
            assert "notify" in characteristic.properties
            assert any(d.uuid == "00002902" + BASE for d in characteristic.descriptors)
            assert await client.read_gatt_char(FEATURE) == b"\x00\x00"
            assert await client.read_gatt_char(LOCATION) == b"\x06"
            report["gatt"] = {"service": "1814", "measurement": "2a53", "cccd": True,
                              "feature": "0000", "location": 6}
            await client.start_notify(MEAS, notification)
            report["mock_checks"] = []
            for spm in (109, 180, 255):
                handle.write(f"mock {spm}\n".encode())
                await asyncio.sleep(1.2)
                start = len(packets)
                await asyncio.sleep(3.2)
                current = packets[start:]
                expected_speed = int(spm * 0.7 / 60 * 256 + 0.5)
                assert len(current) >= 3, "Missing heartbeat notifications"
                assert all(p["cadence_spm"] == spm and p["speed_raw"] == expected_speed for p in current)
                check = {"cadence_spm": spm, "packets": len(current), "raw": current[-1]["raw"]}
                report["mock_checks"].append(check)
                print("RSC mock:", check, flush=True)
            # Reject out-of-range commands rather than overflowing the uint8 cadence.
            handle.write(b"mock 256\nmock 4294967297\nmock -1\nmock 1 " + b" " * 50 + b"junk\n")
            await asyncio.sleep(2.2)
            assert packets[-1]["cadence_spm"] == 255
            report["invalid_commands"] = "rejected out of range, overflow, negative, and truncated input"
            handle.write(b"imu\n")
            await asyncio.sleep(4.2)
            assert packets[-1]["cadence_spm"] == 0 and packets[-1]["speed_raw"] == 0
            # No host serial session; firmware still sends the zero heartbeat over BLE.
            handle.close()
            start = len(packets)
            await asyncio.sleep(4.2)
            idle = packets[start:]
            assert len(idle) >= 4 and all(p["raw"] == "00000000" for p in idle)
            report["idle_without_serial_host"] = {"packets": len(idle), "raw": idle[-1]["raw"]}
        await asyncio.sleep(1)
        device = await find_pod()
        start = len(packets)
        async with BleakClient(device) as client:
            await client.start_notify(MEAS, notification)
            await asyncio.sleep(3.2)
            assert len(packets) - start >= 3
            report["reconnect"] = "passed"
        access(port.device)
        handle = serial.Serial(port.device, 115200, timeout=0.3)
        handle.write(b"imu\n")
        final = await asyncio.to_thread(telemetry, handle, 1)
        assert final and final[-1]["notify_errors"] == 0
        report["notify_errors"] = final[-1]["notify_errors"]
        report["result"] = "PASS"
        print("PASS: IMU, RSC payloads, idle heartbeat, and reconnect", flush=True)
    except Exception as error:
        report["error"] = str(error)
        raise
    finally:
        if handle.is_open:
            handle.write(b"imu\n")
            handle.close()
        (ROOT / "validation/imu.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
        (ROOT / "validation/ble.jsonl").write_text("".join(json.dumps(p) + "\n" for p in packets))
        (ROOT / "validation/report.json").write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    asyncio.run(main())
