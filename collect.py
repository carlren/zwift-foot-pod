"""Record the battery-powered foot pod's six-axis IMU over Bluetooth to CSV."""
import argparse
import asyncio
import csv
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import struct
import time

from bleak import BleakClient, BleakScanner

ROOT = Path(__file__).resolve().parent
SERVICE, DATA, CONTROL, STATUS = (
    f"e85b000{i}-6d10-4a22-90c5-c813f72b1357" for i in range(1, 5)
)
PACKET = struct.Struct("<II6h") # sequence, device us, gyro XYZ, accel XYZ
ACCEL_G_PER_LSB, GYRO_DPS_PER_LSB = 0.000244, 0.035


def decode_status(payload):
    if len(payload) != 16:
        raise ValueError("Unexpected IMU status length")
    version, flags, who, reserved, sent, dropped, errors = struct.unpack("<BBBBIII", payload)
    if version != 1 or reserved or flags & ~7:
        raise ValueError("Unsupported IMU stream protocol")
    return dict(version=version, imu_ok=bool(flags & 1), collecting=bool(flags & 2),
                subscribed=bool(flags & 4), who_am_i=who, sent=sent, dropped=dropped,
                imu_errors=errors)


def positive(value):
    number = float(value)
    if not 0 < number < float("inf"):
        raise argparse.ArgumentTypeError("Must be a finite positive number")
    return number


async def record(args, on_sample=None, on_state=None, stop_event=None):
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S_%fZ")
    directory = ROOT / "recordings" / f"{stamp}_{args.label}"
    directory.mkdir(parents=True)
    metadata = dict(started_utc=datetime.now(timezone.utc).isoformat(), label=args.label,
                    seconds_requested=args.seconds, foot=args.foot,
                    reference_spm=args.reference_spm, speed_kph=args.speed_kph,
                    protocol_version=1, nominal_hz=104, accel_g_per_lsb=ACCEL_G_PER_LSB,
                    gyro_dps_per_lsb=GYRO_DPS_PER_LSB, accel_range_g=8,
                    gyro_range_dps=1000, completed=False, samples=0, missing_packets=0,
                    clipped_samples=0, timing_gaps_over_20ms=0, max_interval_us=0)
    last_seq = last_us = first_seq = None
    elapsed_us = 0
    last_received = time.monotonic()
    stream_error = None
    disconnected = asyncio.Event()
    print("Recording to", directory, flush=True)
    try:
        with (directory / "imu.csv").open("x", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["sequence", "device_us", "elapsed_us", "received_utc",
                             "received_monotonic_ns", "gx_raw", "gy_raw", "gz_raw",
                             "ax_raw", "ay_raw", "az_raw", "gx_dps", "gy_dps", "gz_dps",
                             "ax_g", "ay_g", "az_g"])

            def receive(_, payload):
                nonlocal last_seq, last_us, first_seq, elapsed_us, last_received, stream_error
                if stream_error:
                    return
                try:
                    if len(payload) != PACKET.size:
                        raise ValueError(f"IMU packet must be 20 bytes; got {len(payload)}")
                    seq, device_us, *raw = PACKET.unpack(payload)
                    if last_seq is not None:
                        increment = (seq - last_seq) & 0xFFFFFFFF
                        interval = (device_us - last_us) & 0xFFFFFFFF
                        if not 0 < increment < 0x80000000 or not 0 < interval < 3_000_000:
                            raise ValueError("Duplicate/out-of-order data or device clock reset")
                        metadata["missing_packets"] += increment - 1
                        metadata["timing_gaps_over_20ms"] += int(interval > 20_000)
                        metadata["max_interval_us"] = max(metadata["max_interval_us"], interval)
                        elapsed_us += interval
                    else:
                        first_seq = seq
                    last_received = time.monotonic()
                    writer.writerow([seq, device_us, elapsed_us,
                                     datetime.now(timezone.utc).isoformat(), time.monotonic_ns(),
                                     *raw, *(round(v * GYRO_DPS_PER_LSB, 6) for v in raw[:3]),
                                     *(round(v * ACCEL_G_PER_LSB, 6) for v in raw[3:])])
                    last_seq, last_us = seq, device_us
                    metadata["samples"] += 1
                    metadata["clipped_samples"] += int(any(v in (-32768, 32767) for v in raw))
                    if on_sample:
                        on_sample(dict(sequence=seq, time_s=elapsed_us / 1_000_000,
                                       gyro=[round(v * GYRO_DPS_PER_LSB, 6) for v in raw[:3]],
                                       accel=[round(v * ACCEL_G_PER_LSB, 6) for v in raw[3:]],
                                       missing=metadata["missing_packets"]))
                except Exception as error:
                    stream_error = error

            device = await BleakScanner.find_device_by_filter(
                lambda d, a: a.local_name == "Carl Foot Pod" and SERVICE in a.service_uuids,
                timeout=15,
            )
            if device is None:
                raise RuntimeError("Pod not found. Power it on and disconnect it from Zwift first.")
            metadata["address"] = device.address
            async with BleakClient(device, disconnected_callback=lambda _: disconnected.set()) as client:
                metadata["firmware"] = bytes(await client.read_gatt_char(
                    "00002a28-0000-1000-8000-00805f9b34fb")).decode()
                initial = decode_status(await client.read_gatt_char(STATUS))
                if not initial["imu_ok"] or initial["who_am_i"] != 0x6A:
                    raise RuntimeError(f"IMU is not ready: {initial}")
                metadata["status_before"] = initial
                try:
                    if on_state:
                        update = dict(phase="streaming", directory=str(directory), firmware=metadata["firmware"])
                        battery_uuid = "e85b0005-6d10-4a22-90c5-c813f72b1357"
                        if client.services.get_characteristic(battery_uuid):
                            mv, adc, charge, usb = struct.unpack("<HHBB", await client.read_gatt_char(battery_uuid))
                            update["battery"] = dict(voltage_v=mv / 1000, charging=bool(charge), usb_power=bool(usb))
                        on_state(update)
                    await client.start_notify(DATA, receive)
                    await client.write_gatt_char(CONTROL, b"\x01", response=True)
                    last_received = started = time.monotonic()
                    deadline = started + args.seconds
                    print(f"Collecting {args.label} for {args.seconds:g}s — Ctrl+C stops early", flush=True)
                    ticks = 0
                    while time.monotonic() < deadline:
                        await asyncio.sleep(min(1, max(0, deadline - time.monotonic())))
                        handle.flush()
                        if stop_event and stop_event.is_set():
                            metadata["stopped_by_user"] = True
                            break
                        if stream_error:
                            raise stream_error
                        if disconnected.is_set():
                            raise RuntimeError("Bluetooth disconnected; partial capture saved")
                        if time.monotonic() - last_received > 3:
                            raise RuntimeError("No IMU packets for 3 seconds; partial capture saved")
                        ticks += 1
                        if on_state:
                            update = dict(samples=metadata["samples"], missing=metadata["missing_packets"])
                            on_state(update)
                        if ticks % 5 == 0:
                            print(f"{metadata['samples']} samples; {metadata['missing_packets']} missing", flush=True)
                    if metadata["samples"] < 2:
                        raise RuntimeError("Not enough IMU samples received")
                    metadata["completed"] = True
                finally:
                    if client.is_connected:
                        await client.write_gatt_char(CONTROL, b"\x00", response=True)
                        await asyncio.sleep(0.1) # Drain notifications already queued in the radio.
                        await client.stop_notify(DATA)
                        await asyncio.sleep(0.25)
                        metadata["status_after"] = decode_status(await client.read_gatt_char(STATUS))
                    handle.flush()
                if stream_error:
                    raise stream_error
    except BaseException as error:
        metadata["completed"] = False
        metadata["error"] = type(error).__name__ + ": " + str(error)
        raise
    finally:
        metadata["ended_utc"] = datetime.now(timezone.utc).isoformat()
        metadata["device_duration_s"] = elapsed_us / 1_000_000
        if elapsed_us:
            metadata["received_hz"] = round((metadata["samples"] - 1) * 1_000_000 / elapsed_us, 3)
            metadata["sampled_hz"] = round(((last_seq - first_seq) & 0xFFFFFFFF) * 1_000_000 / elapsed_us, 3)
        (directory / "session.json").write_text(json.dumps(metadata, indent=2) + "\n")
        print(f"Saved {metadata['samples']} samples to {directory / 'imu.csv'}", flush=True)
    return directory, metadata


def arguments():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seconds", type=positive, default=60)
    parser.add_argument("--label", default="unlabeled", help="e.g. stationary, walking, running")
    parser.add_argument("--foot", choices=("left", "right"), default="left")
    parser.add_argument("--reference-spm", type=positive, help="Known total steps/min, if measured")
    parser.add_argument("--speed-kph", type=positive, help="Known treadmill speed, if available")
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", args.label):
        parser.error("Label must be 1–64 letters, digits, hyphens or underscores")
    return args


if __name__ == "__main__":
    try:
        asyncio.run(record(arguments()))
    except KeyboardInterrupt:
        print("Stopped; partial capture saved.")
