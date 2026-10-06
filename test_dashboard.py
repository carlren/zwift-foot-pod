"""Small repeatable checks for the actual live detector and dashboard request validation."""
import asyncio
import math
from pathlib import Path
import tempfile

from dashboard import Dashboard, Detector, recording_args, settings
from collect import PacketDecoder, PACKET
import collect
import dashboard
from types import SimpleNamespace


def point(t, magnitude=1, rotation=0):
    return dict(time_s=t,elapsed_us=int(t*1_000_000),device_us=int(t*1_000_000),sequence=int(t*100),
                accel=[0,0,magnitude],gyro=[0,rotation,0],raw=[0,int(rotation/.035),0,0,0,int(magnitude/0.000244)],
                received_utc='2026-10-06T00:00:00+00:00',received_monotonic_ns=int(t*1e9),missing=0)


def main():
    for spm in (70, 109, 180):
        detector = Detector()
        period = 120 / spm
        for i in range(1000):
            t = i/100
            result = detector.update(point(t,1,rotation=150*math.sin(2*math.pi*t/period)))
        assert abs(result["cadence"] - spm) < 2, result
        assert result["strikes"] >= 5
        assert 0 <= result["rhythm"] <= 1
        assert detector.update(point(14))["cadence"] == 0
    detector=Detector()
    for i in range(600):
        assert not detector.update(point(i/100,2 if i%100<5 else 1))['strike'], 'Acceleration alone triggered a cycle'
    detector=Detector()
    for i in range(200):
        detector.update(point(i/100,rotation=100))
    assert detector.strikes==0, 'Steady positive rotation counted as cycles without reversal'
    for data in ({"peak": float("nan")}, {"peak": 1, "rearm": 1.1}, {"min_stride_ms": 0}):
        try:
            settings(data)
        except ValueError:
            pass
        else:
            raise AssertionError("Invalid detector configuration accepted")
    for data in ({"label": "../bad"}, {"seconds": float("inf")}, {"reference_spm": -1}, {"foot": "both"}):
        try:
            recording_args(data)
        except ValueError:
            pass
        else:
            raise AssertionError("Invalid recording parameters accepted")
    decoder = PacketDecoder()
    decoder.decode(PACKET.pack(0xFFFFFFFF,0xFFFFFF00,0,0,0,0,0,4096))
    decoded = decoder.decode(PACKET.pack(0,0x100,0,0,0,0,0,4096))
    assert decoded['elapsed_us']==512 and decoded['missing']==0
    try:
        decoder.decode(PACKET.pack(0,0x100,0,0,0,0,0,4096))
    except ValueError:
        pass
    else:
        raise AssertionError('Duplicate packet accepted')
    loop = asyncio.new_event_loop()
    app = Dashboard(loop)
    with tempfile.TemporaryDirectory() as directory:
        original_root = collect.ROOT
        collect.ROOT = Path(directory)
        try:
            app.task = SimpleNamespace(done=lambda:False)
            app.update(dict(phase='preview',firmware='test'))
            app.sample(point(0,1.6))
            assert not list(Path(directory).iterdir()), 'Preview wrote files'
            loop.run_until_complete(app.command('record',{'label':'unit','seconds':5}))
            saved = Path(app.state['directory'])
            app.sample(point(.6));app.sample(point(1.2))
            assert app.state['recorded_samples']==2
            timer=app.snapshot(0)
            assert 0<=timer['timer_remaining_seconds']<=5 and timer['timer_elapsed_seconds']>=0
            loop.run_until_complete(app.command('stop',{}))
            assert app.state['phase']=='preview' and not app.state['recording']
            app.sample(point(1.8))
            assert len((saved/'imu.csv').read_text().splitlines())==3
            assert len((saved/'fit.csv').read_text().splitlines())==3
            import csv,json
            with (saved/'imu.csv').open() as f:rows=list(csv.DictReader(f))
            assert rows[0]['sequence']=='60' and rows[0]['elapsed_us']=='0'
            report=json.loads((saved/'session.json').read_text())
            assert report['samples']==2 and report['stopped_by_user']
            assert 'wall_duration_s' in report
            report['wall_duration_s']=60
            (saved/'session.json').write_text(json.dumps(report))
            reply=loop.run_until_complete(app.command('reference',{'steps':109}))
            assert reply['reference_spm']==109
            annotated=json.loads((saved/'session.json').read_text())
            assert annotated['reference_step_count']==109 and annotated['reference_count_duration_s']==60
            assert app.snapshot(0)['timer_elapsed_seconds']==60
            report['wall_duration_s']=30
            (saved/'session.json').write_text(json.dumps(report))
            assert loop.run_until_complete(app.command('reference',{'steps':50}))['reference_spm']==100
            assert loop.run_until_complete(app.command('reference',{'steps':0}))['reference_spm']==0
            assert loop.run_until_complete(app.command('reference',{'reference_spm':120}))['reference_spm']==120
            for bad in (-1,1.5,float('inf')):
                try:
                    loop.run_until_complete(app.command('reference',{'steps':bad}))
                except ValueError:
                    pass
                else:
                    raise AssertionError('Invalid step count accepted')
            snapshot=app.snapshot(3)
            assert len(snapshot['points'])==1 and snapshot['cursor']==4
            loop.run_until_complete(app.command('record',{'label':'second','seconds':5}))
            assert Path(app.state['directory'])!=saved
            app.sample(point(2))
            loop.run_until_complete(app.command('stop',{}))
            connected = Dashboard(loop)
            previous_stream = dashboard.stream
            async def fake_stream(on_sample,on_state,stop_event):
                on_state({'phase':'preview'})
                on_sample(point(0))
                await stop_event.wait()
                return {}
            dashboard.stream = fake_stream
            try:
                before=set(Path(directory).rglob('*'))
                loop.run_until_complete(connected.command('connect',{'label':'','seconds':0}))
                loop.run_until_complete(asyncio.sleep(0))
                assert connected.state['phase']=='preview' and connected.state['samples']==1
                assert set(Path(directory).rglob('*'))==before
                loop.run_until_complete(connected.command('disconnect',{}))
                assert connected.state['phase']=='disconnected'
            finally:
                dashboard.stream=previous_stream
            previous_collect_stream=collect.stream
            async def fake_cli_stream(on_sample,on_state,stop_event,seconds):
                on_state(dict(phase='preview',firmware='test',status_before={'imu_ok':True}))
                decoder=PacketDecoder()
                for i in range(12):
                    on_sample(decoder.decode(PACKET.pack(i,10000+i*10000,0,0,0,0,0,4096)))
                return dict(status_after={'imu_ok':True})
            collect.stream=fake_cli_stream
            try:
                path,report=loop.run_until_complete(collect.record(recording_args({'label':'cli-unit','seconds':5})))
                assert report['completed'] and report['samples']==12 and report['missing_packets']==0
                assert report['firmware']=='test' and report['status_after']['imu_ok']
                assert len((path/'imu.csv').read_text().splitlines())==13
                assert not (path/'fit.csv').exists()
            finally:
                collect.stream=previous_collect_stream
        finally:
            collect.ROOT=original_root
    loop.close()
    print('PASS: cadence, timing, validation, timestamp wrap, file-free preview, recording boundaries, stop preserves preview, repeated recording, CLI recorder')



if __name__ == "__main__":
    main()
