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


class PacketDecoder:
    """Shared timestamp/sequence validation for live preview and saved recordings."""
    def __init__(self):
        self.last_seq = self.last_us = None
        self.elapsed_us = self.missing = 0

    def decode(self, payload):
        if len(payload) != PACKET.size:
            raise ValueError(f"IMU packet must be 20 bytes; got {len(payload)}")
        seq, device_us, *raw = PACKET.unpack(payload)
        if self.last_seq is not None:
            increment = (seq - self.last_seq) & 0xFFFFFFFF
            interval = (device_us - self.last_us) & 0xFFFFFFFF
            if not 0 < increment < 0x80000000 or not 0 < interval < 3_000_000:
                raise ValueError("Duplicate/out-of-order data or device clock reset")
            self.missing += increment - 1
            self.elapsed_us += interval
        self.last_seq, self.last_us = seq, device_us
        return dict(sequence=seq, device_us=device_us, elapsed_us=self.elapsed_us,
                    time_s=self.elapsed_us / 1_000_000, raw=raw,
                    received_utc=datetime.now(timezone.utc).isoformat(), received_monotonic_ns=time.monotonic_ns(),
                    gyro=[round(v * GYRO_DPS_PER_LSB, 6) for v in raw[:3]],
                    accel=[round(v * ACCEL_G_PER_LSB, 6) for v in raw[3:]], missing=self.missing)


class Recording:
    """Open files only when the user actually starts recording."""
    def __init__(self, args, connection=None):
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S_%fZ")
        self.directory = ROOT / "recordings" / f"{stamp}_{args.label}"
        self.directory.mkdir(parents=True)
        self.metadata = dict(started_utc=datetime.now(timezone.utc).isoformat(), label=args.label,
            seconds_requested=args.seconds, foot=args.foot, reference_spm=args.reference_spm,
            speed_kph=args.speed_kph, protocol_version=1, nominal_hz=104,
            accel_g_per_lsb=ACCEL_G_PER_LSB, gyro_dps_per_lsb=GYRO_DPS_PER_LSB,
            accel_range_g=8, gyro_range_dps=1000, completed=False, samples=0, missing_packets=0,
            clipped_samples=0, timing_gaps_over_20ms=0, max_interval_us=0)
        self.metadata.update({k:v for k,v in (connection or {}).items()
                              if k in ('address','firmware','status_before','battery')})
        self.handle = (self.directory / 'imu.csv').open('x', newline='')
        self.writer = csv.writer(self.handle)
        self.writer.writerow(['sequence','device_us','elapsed_us','received_utc','received_monotonic_ns',
                             'gx_raw','gy_raw','gz_raw','ax_raw','ay_raw','az_raw',
                             'gx_dps','gy_dps','gz_dps','ax_g','ay_g','az_g'])
        self.first_time = self.first_seq = self.last_time = self.last_seq = None

    def append(self, sample):
        seq, t = sample['sequence'], sample['elapsed_us']
        if self.first_time is None:
            self.first_time, self.first_seq = t, seq
        if self.last_time is not None:
            interval = t - self.last_time
            self.metadata['missing_packets'] += ((seq-self.last_seq)&0xFFFFFFFF)-1
            self.metadata['timing_gaps_over_20ms'] += int(interval>20_000)
            self.metadata['max_interval_us'] = max(self.metadata['max_interval_us'],interval)
        elapsed = t-self.first_time
        self.writer.writerow([seq,sample['device_us'],elapsed,sample['received_utc'],sample['received_monotonic_ns'],
                              *sample['raw'],*sample['gyro'],*sample['accel']])
        self.metadata['samples'] += 1
        self.metadata['clipped_samples'] += int(any(v in (-32768,32767) for v in sample['raw']))
        self.last_time, self.last_seq = t,seq
        return elapsed/1_000_000

    def flush(self):
        self.handle.flush()

    def finish(self, error=None, stopped_by_user=False, connection=None):
        self.handle.close()
        self.metadata['completed'] = error is None and self.metadata['samples']>=2
        self.metadata['stopped_by_user'] = stopped_by_user
        if error is not None:
            self.metadata['error'] = type(error).__name__+': '+str(error)
        self.metadata.update({k:v for k,v in (connection or {}).items() if k=='status_after'})
        self.metadata['ended_utc'] = datetime.now(timezone.utc).isoformat()
        elapsed = (self.last_time-self.first_time) if self.last_time is not None else 0
        self.metadata['device_duration_s'] = elapsed/1_000_000
        if elapsed:
            self.metadata['received_hz'] = round((self.metadata['samples']-1)*1_000_000/elapsed,3)
            self.metadata['sampled_hz'] = round(((self.last_seq-self.first_seq)&0xFFFFFFFF)*1_000_000/elapsed,3)
        (self.directory/'session.json').write_text(json.dumps(self.metadata,indent=2)+'\n')
        return self.metadata


async def stream(on_sample, on_state=None, stop_event=None, seconds=None):
    """One Bluetooth connection, no disk writes. Recording is an independent consumer."""
    decoder = PacketDecoder()
    last_received = time.monotonic()
    stream_error = None
    disconnected = asyncio.Event()
    connection = {}

    def receive(_, payload):
        nonlocal last_received, stream_error
        if stream_error:
            return
        try:
            sample = decoder.decode(payload)
            last_received = time.monotonic()
            on_sample(sample)
        except Exception as error:
            stream_error = error

    device = await BleakScanner.find_device_by_filter(
        lambda d,a:a.local_name=='Carl Foot Pod' and SERVICE in a.service_uuids, timeout=15)
    if device is None:
        raise RuntimeError('Pod not found. Power it on and check that a Bluetooth connection slot is free.')
    connection['address'] = device.address
    async with BleakClient(device,disconnected_callback=lambda _:disconnected.set()) as client:
        connection['firmware'] = bytes(await client.read_gatt_char('00002a28-0000-1000-8000-00805f9b34fb')).decode()
        initial = decode_status(await client.read_gatt_char(STATUS))
        if not initial['imu_ok'] or initial['who_am_i']!=0x6A:
            raise RuntimeError(f'IMU is not ready: {initial}')
        connection['status_before'] = initial
        battery_uuid = 'e85b0005-6d10-4a22-90c5-c813f72b1357'
        if client.services.get_characteristic(battery_uuid):
            mv,adc,charge,usb = struct.unpack('<HHBB',await client.read_gatt_char(battery_uuid))
            connection['battery'] = dict(voltage_v=mv/1000,charging=bool(charge),usb_power=bool(usb))
            level_uuid = '00002a19-0000-1000-8000-00805f9b34fb'
            if client.services.get_characteristic(level_uuid):
                level = bytes(await client.read_gatt_char(level_uuid))
                if len(level) != 1 or level[0] > 100:
                    raise ValueError('Invalid Bluetooth battery percentage')
                connection['battery'].update(percent=level[0], percent_estimated=True)
        if on_state:
            on_state(dict(phase='preview',**connection))
        try:
            await client.start_notify(DATA,receive)
            await client.write_gatt_char(CONTROL,b'\x01',response=True)
            last_received = time.monotonic()
            deadline = last_received+seconds if seconds is not None else float('inf')
            while time.monotonic()<deadline:
                await asyncio.sleep(.1)
                if stop_event and stop_event.is_set():
                    break
                if stream_error:
                    raise stream_error
                if disconnected.is_set():
                    raise RuntimeError('Bluetooth disconnected; partial capture saved')
                if time.monotonic()-last_received>3:
                    raise RuntimeError('No IMU packets for 3 seconds; partial capture saved')
        finally:
            if client.is_connected:
                await client.write_gatt_char(CONTROL,b'\x00',response=True)
                await asyncio.sleep(.1)
                await client.stop_notify(DATA)
                await asyncio.sleep(.25)
                connection['status_after'] = decode_status(await client.read_gatt_char(STATUS))
        if stream_error:
            raise stream_error
    return connection


async def record(args, on_sample=None, on_state=None, stop_event=None):
    saved = Recording(args)
    connection = {}
    failure = None
    print('Recording to',saved.directory,flush=True)
    def receive(sample):
        saved.append(sample)
        if saved.metadata['samples']%500==0:
            print(f"{saved.metadata['samples']} samples; {saved.metadata['missing_packets']} missing",flush=True)
        if saved.metadata['samples']%100==0:
            saved.flush()
        if on_sample:
            on_sample(sample)
    def status(values):
        if values.get('phase')=='preview':
            print(f'Collecting {args.label} for {args.seconds:g}s — Ctrl+C stops early',flush=True)
        connection.update(values)
        saved.metadata.update({k:v for k,v in values.items() if k in ('address','firmware','status_before','battery')})
        if on_state:
            on_state(dict(values,directory=str(saved.directory)))
    try:
        connection.update(await stream(receive,status,stop_event,args.seconds))
        if saved.metadata['samples']<2:
            raise RuntimeError('Not enough IMU samples received')
    except BaseException as error:
        failure = error
        raise
    finally:
        saved.finish(failure,bool(stop_event and stop_event.is_set()),connection)
        print(f"Saved {saved.metadata['samples']} samples to {saved.directory/'imu.csv'}",flush=True)
    return saved.directory,saved.metadata


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
