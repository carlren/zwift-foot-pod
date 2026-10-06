"""Hardware check: concurrent RSC/IMU, live battery reads, free-slot advertising.

Uses one physical central. A separate phone is required to test two radio links.
"""
import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
import struct
import time

from bleak import BleakClient, BleakScanner
from collect import DATA, CONTROL, STATUS, PacketDecoder, decode_status
from validate import find_pod, MEAS

LEVEL = '00002a19-0000-1000-8000-00805f9b34fb'
VOLTAGE = 'e85b0005-6d10-4a22-90c5-c813f72b1357'
ROOT = Path(__file__).resolve().parent


async def main():
    report = dict(checked_utc=datetime.now(timezone.utc).isoformat(), result='FAIL',
                  physical_centrals=1, two_device_test='Not performed: needs a separate phone')
    device = await find_pod()
    decoder = PacketDecoder()
    samples, cadence, advertisements, levels = [], [], [], []
    def receive(_, payload):
        samples.append(decoder.decode(payload))
    def advertisement(d, a):
        if d.address == device.address:
            advertisements.append(time.monotonic())
    try:
        async with BleakClient(device) as client:
            report['firmware'] = bytes(await client.read_gatt_char(
                '00002a28-0000-1000-8000-00805f9b34fb')).decode()
            assert report['firmware'] == '0.4.0'
            initial = decode_status(await client.read_gatt_char(STATUS))
            assert initial['imu_ok'] and not initial['collecting'] and initial['sent'] == 0
            await client.start_notify(MEAS, lambda _, p: cadence.append((time.monotonic(), bytes(p))))
            await client.start_notify(LEVEL, lambda _, p: levels.append(bytes(p)))
            await client.start_notify(DATA, receive)
            await client.write_gatt_char(CONTROL, b'\x01', response=True)
            started = time.monotonic()
            async with BleakScanner(detection_callback=advertisement):
                await asyncio.sleep(4)
            # Exercise ATT reads during collection; no USB serial commands.
            readings = []
            for _ in range(5):
                mv, adc, charging, usb = struct.unpack('<HHBB', await client.read_gatt_char(VOLTAGE))
                pct = bytes(await client.read_gatt_char(LEVEL))
                assert 2500 <= mv <= 4400 and adc <= 4095
                assert len(pct) == 1 and pct[0] <= 100
                status = decode_status(await client.read_gatt_char(STATUS))
                assert status['collecting'] and status['subscribed']
                readings.append(dict(millivolts=mv, percent=pct[0], charging=bool(charging), usb_power=bool(usb)))
                await asyncio.sleep(3)
            await client.write_gatt_char(CONTROL, b'\x00', response=True)
            await asyncio.sleep(.2)
            await client.stop_notify(DATA)
            await asyncio.sleep(.2)
            final = decode_status(await client.read_gatt_char(STATUS))
            assert not final['collecting'] and not final['subscribed']
            assert final['imu_errors'] == initial['imu_errors']
            assert len(samples) > 1800
            hz = (len(samples)-1)/(samples[-1]['time_s']-samples[0]['time_s'])
            report.update(samples=len(samples), received_hz=round(hz,3), missing=decoder.missing,
                          status_after=final, battery_readings=readings)
            print('Stream:', len(samples), 'samples;', round(hz,3), 'Hz;', decoder.missing, 'missing', flush=True)
            assert 95 < hz < 110 and decoder.missing < len(samples)*.01
            concurrent = [p for t,p in cadence if started <= t <= started+samples[-1]['time_s']]
            assert len(concurrent) >= 17 and all(len(p)==4 and p[0]==0 for p in concurrent)
            times = [t for t,p in cadence]
            max_gap = max(b-a for a,b in zip(times,times[1:]))
            assert max_gap < 1.5, f'Cadence stalled during recording: {max_gap}'
            assert advertisements, 'Not advertising the free second connection slot'
            assert all(len(p)==1 and p[0]<=100 for p in levels)
            before_stop = len(cadence)
            await asyncio.sleep(3.2)
            assert len(cadence)-before_stop >= 3, 'Stopping capture stopped cadence'
            report.update(samples=len(samples), received_hz=round(hz,3), missing=decoder.missing,
                          status_after=final, concurrent_cadence_frames=len(concurrent),
                          max_cadence_gap_s=round(max_gap,3), battery_readings=readings,
                          battery_notifications=len(levels), advertising_while_connected=True)
            # Disconnect with collection enabled, then check that the reused slot is reset.
            await client.write_gatt_char(CONTROL, b'\x01', response=True)
        await asyncio.sleep(1)
        device = await find_pod()
        async with BleakClient(device) as client:
            fresh = decode_status(await client.read_gatt_char(STATUS))
            assert not fresh['collecting'] and not fresh['subscribed'] and fresh['sent']==0 and fresh['dropped']==0
            report['reconnect_collection_reset'] = True
        report['result'] = 'PASS'
        print(json.dumps(report, indent=2), flush=True)
    except Exception as error:
        report['error'] = f'{type(error).__name__}: {error}'
        raise
    finally:
        (ROOT/'validation/companion-report.json').write_text(json.dumps(report, indent=2)+'\n')


if __name__ == '__main__':
    asyncio.run(main())
