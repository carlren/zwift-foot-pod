"""Local live IMU dashboard. Run .venv/bin/python dashboard.py, then open localhost:8766."""
import argparse
import asyncio
from collections import deque
import csv
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import math
from pathlib import Path
import re
import threading
import time
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

from collect import Recording, stream

ROOT = Path(__file__).resolve().parent


class Detector:
    """Signed gyro-cycle prototype. One complete rotation cycle represents one-foot stride."""
    def __init__(self, peak=40, rearm=-20, min_stride_ms=450, axis='y'):
        self.peak,self.rearm,self.minimum,self.axis=peak,rearm,min_stride_ms/1000,axis
        self.last=self.last_t=self.filtered=None
        self.armed=False
        self.spm=0.0
        self.strikes=0

    def update(self, sample):
        t=sample['time_s']
        raw=sample['gyro'][{'x':0,'y':1,'z':2}[self.axis]]
        dt=t-self.last_t if self.last_t is not None else 0
        # A short low-pass filter removes high-frequency jitter, preserving signed rotation.
        if self.filtered is None or dt<=0 or dt>.1:
            self.filtered=raw
            self.armed=False
        else:
            self.filtered+=(1-math.exp(-dt/.04))*(raw-self.filtered)
        self.last_t=t
        if self.last is not None and t-self.last>3:
            self.last,self.spm,self.armed=None,0.0,False
        if self.filtered<=self.rearm:
            self.armed=True
        event=False
        if self.armed and self.filtered>=self.peak:
            self.armed=False
            if self.last is None or t-self.last>=self.minimum:
                if self.last is not None:
                    measured=120/(t-self.last)
                    self.spm=measured if not self.spm else .6*self.spm+.4*measured
                self.last=t;self.strikes+=1;event=True
        cadence=min(255,max(0,self.spm))
        phase=((t-self.last)*cadence/120)%1 if cadence and self.last is not None else None
        return dict(magnitude=round(math.sqrt(sum(v*v for v in sample['accel'])),5),
            gyro_axis=self.axis,gyro_signal=raw,gyro_filtered=round(self.filtered,4),
            strike=event,cadence=round(cadence,2),strikes=self.strikes,phase=phase,
            rhythm=(1+math.cos(2*math.pi*phase))/2 if phase is not None else None)


def settings(data):
    peak,rearm=float(data.get('peak',40)),float(data.get('rearm',-20))
    minimum=float(data.get('min_stride_ms',450));axis=data.get('axis','y')
    if not all(math.isfinite(v) for v in (peak,rearm,minimum)) or not (5<=peak<=900 and -900<=rearm<=0 and 250<=minimum<=2000) or axis not in ('x','y','z'):
        raise ValueError('Choose X/Y/Z, a positive gyro trigger of 5–900 °/s, a negative rearm of -900–0 °/s, and 250–2000 ms minimum stride')
    return dict(peak=peak,rearm=rearm,min_stride_ms=minimum,axis=axis)


def recording_args(data):
    label = str(data.get("label", "walking"))
    seconds = float(data.get("seconds", 180))
    foot = data.get("foot", "left")
    reference = data.get("reference_spm")
    reference = None if reference in (None, "") else float(reference)
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", label):
        raise ValueError("Use a short label containing letters, digits, hyphens or underscores")
    if not math.isfinite(seconds) or not 5 <= seconds <= 3600 or foot not in ("left", "right"):
        raise ValueError("Choose a duration of 5–3600 seconds and left or right foot")
    if reference is not None and (not math.isfinite(reference) or not 0 <= reference <= 255):
        raise ValueError("Reference cadence must be 0–255 steps/min")
    return SimpleNamespace(label=label, seconds=seconds, foot=foot, reference_spm=reference, speed_kph=None)


class Dashboard:
    def __init__(self, loop):
        self.loop = loop
        self.lock = threading.Lock()
        self.history = deque(maxlen=5000)
        self.config = settings({})
        self.detector = Detector(**self.config)
        self.state = dict(phase='idle', samples=0, missing=0, cadence=0, strikes=0, run_id=time.time_ns()//1000,
                          config=self.config, error=None, directory=None, reference_spm=None,
                          recording=False, recorded_samples=0, recorded_seconds=0)
        self.task = self.stop_event = None
        self.recording = None
        self.connection = {}
        self.fit_handle = self.fit_writer = None
        self.fit_changes = []
        self.index = 0
        self.deadline = None
        self.record_started = None
        # Keep the latest saved dashboard session available for reference annotation after restart.
        for path in sorted((ROOT/'recordings').glob('*/session.json'),reverse=True):
            if not (path.parent/'fit.csv').exists():
                continue
            try:
                report = json.loads(path.read_text())
                if report.get('exclude_from_training'):
                    continue
                self.state.update(directory=str(path.parent),report=report,reference_spm=report.get('reference_spm'),
                    recorded_samples=report.get('samples',0),recorded_seconds=report.get('device_duration_s',0),
                    seconds=report.get('seconds_requested',180),label=report.get('label','walking'))
                break
            except (ValueError,OSError):
                continue

    def snapshot(self, since):
        with self.lock:
            state = dict(self.state)
            state['points'] = [p for p in self.history if p['index']>since]
            state['cursor'] = self.index
            state['age_s'] = round(time.monotonic()-self.state.get('last_received',time.monotonic()),2)
            if self.recording:
                state['timer_elapsed_seconds'] = round(min(self.state['seconds'],max(0,time.monotonic()-self.record_started)),3)
                state['timer_remaining_seconds'] = round(max(0,self.deadline-time.monotonic()),3)
            else:
                report = self.state.get('report') or {}
                state['timer_elapsed_seconds'] = report.get('wall_duration_s',report.get('device_duration_s',0))
                state['timer_remaining_seconds'] = 0
            return state

    def update(self, values):
        with self.lock:
            self.state.update(values)
            self.connection.update(values)

    def finish_recording(self, error=None, stopped_by_user=False):
        # Caller holds the lock. Keep the Bluetooth stream and detector running.
        if not self.recording:
            return
        saved = self.recording
        saved.metadata['wall_duration_s'] = round(min(self.state['seconds'],max(0,time.monotonic()-self.record_started)),3)
        report = saved.finish(error,stopped_by_user,self.connection)
        self.fit_handle.close()
        (saved.directory/'fit-settings.json').write_text(json.dumps(
            dict(algorithm='signed-gyro-cycle-prototype-v1',changes=self.fit_changes),indent=2)+'\n')
        self.recording = self.fit_handle = self.fit_writer = None
        self.deadline = None
        self.record_started = None
        self.state.update(recording=False,report=report,recorded_samples=report['samples'],
                          recorded_seconds=report['device_duration_s'])
        if self.state['phase']=='recording':
            self.state['phase']='preview'

    def sample(self, point):
        with self.lock:
            fit = self.detector.update(point)
            self.index += 1
            point.update(fit,index=self.index)
            self.history.append(point)
            self.state.update(cadence=fit['cadence'],strikes=fit['strikes'],samples=self.state['samples']+1,
                              missing=point['missing'],last_received=time.monotonic(),latest=point)
            if self.recording and time.monotonic()>=self.deadline:
                self.finish_recording()
            if self.recording:
                relative = self.recording.append(point)
                self.fit_writer.writerow([point['sequence'],relative,fit['gyro_axis'],fit['gyro_signal'],fit['gyro_filtered'],fit['magnitude'],int(fit['strike']),
                    fit['cadence'],fit['phase'],self.config['peak'],self.config['rearm'],self.config['min_stride_ms']])
                count = self.recording.metadata['samples']
                self.state.update(recorded_samples=count,recorded_seconds=relative)
                if count%100==0:
                    self.recording.flush();self.fit_handle.flush()

    async def preview(self):
        failure = None
        try:
            connection = await stream(self.sample,self.update,self.stop_event)
            self.connection.update(connection)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            failure = error
            self.update(dict(phase='error',error=str(error),cadence=0))
        finally:
            with self.lock:
                self.finish_recording(failure,stopped_by_user=failure is None)
                if self.state['phase']!='error':
                    self.state.update(phase='disconnected',cadence=0)

    async def command(self, action, data):
        if action=='connect':
            if self.task and not self.task.done():
                raise ValueError('The pod is already connected')
            with self.lock:
                self.history.clear()
                self.detector = Detector(**self.config)
                self.connection = {}
                self.state.update(phase='connecting',run_id=self.state['run_id']+1,samples=0,missing=0,
                    cadence=0,strikes=0,error=None,latest=None,battery=None,recording=False,
                    reference_spm=None)
            self.stop_event = asyncio.Event()
            self.task = asyncio.create_task(self.preview())
        elif action=='record':
            args = recording_args(data)
            with self.lock:
                if self.state['phase']!='preview' or not self.task or self.task.done() or not self.state['samples']:
                    raise ValueError('Connect and wait for live samples before recording')
                self.recording = Recording(args,self.connection)
                self.fit_handle = (self.recording.directory/'fit.csv').open('x',newline='')
                self.fit_writer = csv.writer(self.fit_handle)
                self.fit_writer.writerow(['sequence','time_s','gyro_axis','gyro_raw_dps','gyro_filtered_dps','acceleration_magnitude_g','stride_event','cadence_spm',
                                         'phase','gyro_peak_dps','gyro_rearm_dps','min_stride_ms'])
                self.fit_changes = [dict(time_s=0,**self.config)]
                self.record_started = time.monotonic()
                self.deadline = self.record_started+args.seconds
                self.state.update(phase='recording',recording=True,directory=str(self.recording.directory),
                    recorded_samples=0,recorded_seconds=0,report=None,reference_spm=args.reference_spm,
                    label=args.label,seconds=args.seconds,foot=args.foot)
        elif action=='stop':
            with self.lock:
                self.finish_recording(stopped_by_user=True)
        elif action=='reference':
            with self.lock:
                if self.recording or not self.state.get('directory'):
                    raise ValueError('Finish a recording before saving its reference cadence')
                path = Path(self.state['directory'])/'session.json'
                report = json.loads(path.read_text())
                duration = report.get('wall_duration_s',report.get('device_duration_s',0))
                if 'steps' in data:
                    steps = float(data['steps'])
                    if not math.isfinite(steps) or not 0 <= steps <= 1_000_000 or steps != int(steps) or duration <= 0:
                        raise ValueError('Enter a nonnegative whole count of steps for the completed recording')
                    reference = round(steps*60/duration,2)
                    report['reference_step_count'] = int(steps)
                    report['reference_count_duration_s'] = duration
                    report['reference_source'] = 'manual_total_step_count'
                else:
                    reference = data.get('reference_spm')
                    report['reference_source'] = 'manual_cadence'
                    report.pop('reference_step_count',None)
                    report.pop('reference_count_duration_s',None)
                reference = recording_args({'reference_spm':reference}).reference_spm
                report['reference_spm'] = reference
                path.write_text(json.dumps(report,indent=2)+'\n')
                self.state.update(report=report,reference_spm=reference)
                return {'ok':True,'reference_spm':reference,'count_duration_s':duration}
        elif action=='disconnect':
            if self.task and not self.task.done():
                if self.state['phase']=='connecting':
                    self.task.cancel()
                self.stop_event.set()
                self.update(dict(phase='disconnecting'))
                try:
                    await asyncio.wait_for(asyncio.shield(self.task),25)
                except asyncio.CancelledError:
                    self.update(dict(phase='disconnected',cadence=0))
        elif action=='tune':
            config = settings(data)
            with self.lock:
                self.config = config
                self.detector = Detector(**config)
                self.state['config'] = config
                if self.recording:
                    self.fit_changes.append(dict(time_s=self.state['recorded_seconds'],**config))
        else:
            raise ValueError('Unknown command')
        return {'ok':True}


def handler(app):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def send(self, status, payload, content_type="application/json"):
            body = payload if isinstance(payload, bytes) else json.dumps(payload, allow_nan=False).encode()
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def do_GET(self):
            url = urlsplit(self.path)
            if url.path == "/":
                self.send(200, (ROOT / "dashboard.html").read_bytes(), "text/html; charset=utf-8")
            elif url.path == "/api/state":
                try:
                    since = int(parse_qs(url.query).get("since", ["0"])[0])
                    self.send(200, app.snapshot(since))
                except ValueError:
                    self.send(400, {"error": "Invalid cursor"})
            elif url.path in ("/download/imu.csv", "/download/fit.csv", "/download/session.json"):
                with app.lock:
                    directory = app.state.get("directory")
                file = Path(directory) / url.path.rsplit("/", 1)[-1] if directory else None
                if file and file.is_file():
                    self.send(200, file.read_bytes(), "text/csv; charset=utf-8" if file.suffix == ".csv" else "application/json")
                else:
                    self.send(404, {"error": "No recording available"})
            else:
                self.send(404, {"error": "Not found"})

        def do_POST(self):
            origin = self.headers.get("Origin")
            if origin and origin not in (f"http://127.0.0.1:{self.server.server_port}", f"http://localhost:{self.server.server_port}"):
                self.send(403, {"error": "Local dashboard requests only"}); return
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if not 0 < size <= 4096 or self.headers.get("Content-Type") != "application/json":
                    raise ValueError("Send a JSON request under 4 KB")
                data = json.loads(self.rfile.read(size))
                if not isinstance(data, dict):
                    raise ValueError("Expected a JSON object")
                action = self.path.removeprefix("/api/")
                if self.path != "/api/" + action or action not in ("connect", "record", "stop", "disconnect", "tune", "reference"):
                    raise ValueError("Unknown command")
                future = asyncio.run_coroutine_threadsafe(app.command(action, data), app.loop)
                self.send(200, future.result(timeout=30))
            except (ValueError, TypeError) as error:
                self.send(400, {"error": str(error)})
            except Exception as error:
                self.send(500, {"error": str(error)})
    return Handler


async def main(port):
    app = Dashboard(asyncio.get_running_loop())
    server = ThreadingHTTPServer(("127.0.0.1", port), handler(app))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    print(f"Foot Pod Lab: http://127.0.0.1:{port}", flush=True)
    try:
        await asyncio.Event().wait()
    finally:
        if app.task and not app.task.done():
            await app.command('disconnect',{})
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8766)
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("Port must be between 1 and 65535")
    try:
        asyncio.run(main(args.port))
    except KeyboardInterrupt:
        pass
