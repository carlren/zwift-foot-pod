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

from collect import record

ROOT = Path(__file__).resolve().parent


class Detector:
    """Prototype matching the firmware's one-foot threshold detector; replace as we fit gait data."""
    def __init__(self, peak=1.30, rearm=1.08, min_stride_ms=450):
        self.peak, self.rearm, self.minimum = peak, rearm, min_stride_ms / 1000
        self.last = None
        self.armed = True
        self.spm = 0.0
        self.strikes = 0

    def update(self, sample):
        t = sample["time_s"]
        magnitude = math.sqrt(sum(v*v for v in sample["accel"]))
        if self.last is not None and t - self.last > 3:
            self.last, self.spm, self.armed = None, 0.0, True
        if magnitude < self.rearm:
            self.armed = True
        strike = False
        if self.armed and magnitude >= self.peak:
            self.armed = False
            if self.last is None or t - self.last >= self.minimum:
                if self.last is not None:
                    measured = 120 / (t - self.last) # Two total steps per one-foot stride.
                    self.spm = measured if not self.spm else 0.6*self.spm + 0.4*measured
                self.last = t
                self.strikes += 1
                strike = True
        cadence = min(255, max(0, self.spm))
        phase = ((t - self.last) * cadence / 120) % 1 if cadence and self.last is not None else None
        return dict(magnitude=round(magnitude, 5), strike=strike, cadence=round(cadence, 2),
                    strikes=self.strikes, phase=phase, rhythm=(1 + math.cos(2*math.pi*phase))/2 if phase is not None else None)


def settings(data):
    peak, rearm = float(data.get("peak", 1.30)), float(data.get("rearm", 1.08))
    minimum = float(data.get("min_stride_ms", 450))
    if not all(math.isfinite(v) for v in (peak, rearm, minimum)) or not (1.0 <= rearm < peak <= 5 and 250 <= minimum <= 2000):
        raise ValueError("Use 1.0 ≤ rearm < peak ≤ 5 g and a stride minimum of 250–2000 ms")
    return dict(peak=peak, rearm=rearm, min_stride_ms=minimum)


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
    if reference is not None and (not math.isfinite(reference) or not 30 <= reference <= 255):
        raise ValueError("Reference cadence must be 30–255 steps/min")
    return SimpleNamespace(label=label, seconds=seconds, foot=foot, reference_spm=reference, speed_kph=None)


class Dashboard:
    def __init__(self, loop):
        self.loop = loop
        self.lock = threading.Lock()
        self.history = deque(maxlen=5000)
        self.config = settings({})
        self.detector = Detector(**self.config)
        self.state = dict(phase="idle", samples=0, missing=0, cadence=0, strikes=0, run_id=0,
                          config=self.config, error=None, directory=None, reference_spm=None)
        self.task = None
        self.stop_event = None
        self.fit_handle = self.fit_writer = None
        self.fit_changes = []
        self.index = 0

    def snapshot(self, since):
        with self.lock:
            state = dict(self.state)
            state["points"] = [p for p in self.history if p["index"] > since]
            state["cursor"] = self.index
            state["age_s"] = round(time.monotonic() - self.state.get("last_received", time.monotonic()), 2)
            return state

    def update(self, values):
        with self.lock:
            self.state.update(values)
            if values.get("phase") == "streaming":
                directory = Path(values["directory"])
                self.fit_handle = (directory / "fit.csv").open("x", newline="")
                self.fit_writer = csv.writer(self.fit_handle)
                self.fit_writer.writerow(["sequence", "time_s", "magnitude_g", "foot_strike", "cadence_spm", "phase", "peak_g", "rearm_g", "min_stride_ms"])
            if self.fit_handle:
                self.fit_handle.flush()

    def sample(self, point):
        with self.lock:
            fit = self.detector.update(point)
            self.index += 1
            point.update(fit, index=self.index)
            self.history.append(point)
            self.state.update(cadence=fit["cadence"], strikes=fit["strikes"], samples=self.state["samples"]+1,
                              missing=point["missing"], last_received=time.monotonic(), latest=point)
            if self.fit_writer:
                self.fit_writer.writerow([point["sequence"], point["time_s"], fit["magnitude"], int(fit["strike"]), fit["cadence"], fit["phase"], self.config["peak"], self.config["rearm"], self.config["min_stride_ms"]])

    async def capture(self, args):
        try:
            directory, report = await record(args, on_sample=self.sample, on_state=self.update, stop_event=self.stop_event)
            self.update(dict(phase="stopped", report=report, directory=str(directory), cadence=0))
        except asyncio.CancelledError:
            self.update(dict(phase="stopped", cadence=0))
            raise
        except Exception as error:
            self.update(dict(phase="error", error=str(error), cadence=0))
        finally:
            with self.lock:
                if self.fit_handle:
                    self.fit_handle.close()
                    directory = Path(self.state["directory"])
                    (directory / "fit-settings.json").write_text(json.dumps(dict(algorithm="firmware-threshold-prototype", changes=self.fit_changes), indent=2)+"\n")
                self.fit_handle = self.fit_writer = None

    async def command(self, action, data):
        if action == "start":
            args = recording_args(data)
            if self.task and not self.task.done():
                raise ValueError("A recording is already running")
            with self.lock:
                self.history.clear()
                self.detector = Detector(**self.config)
                self.state.update(phase="connecting", run_id=self.state["run_id"]+1, samples=0, missing=0,
                                  cadence=0, strikes=0, error=None, directory=None, latest=None, battery=None,
                                  reference_spm=args.reference_spm, label=args.label, seconds=args.seconds)
                self.fit_changes = [dict(time_s=0, **self.config)]
            self.stop_event = asyncio.Event()
            self.task = asyncio.create_task(self.capture(args))
        elif action == "stop":
            if self.task and not self.task.done():
                if self.state["phase"] == "connecting":
                    self.task.cancel()
                self.stop_event.set()
                self.update(dict(phase="stopping"))
                try:
                    await asyncio.wait_for(asyncio.shield(self.task), 25)
                except asyncio.CancelledError:
                    self.update(dict(phase="stopped", cadence=0))
        elif action == "tune":
            config = settings(data)
            with self.lock:
                self.config = config
                self.detector = Detector(**config)
                self.state["config"] = config
                t = self.state.get("latest") or {}
                self.fit_changes.append(dict(time_s=t.get("time_s", 0), **config))
        else:
            raise ValueError("Unknown command")
        return {"ok": True}


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
                if self.path != "/api/" + action or action not in ("start", "stop", "tune"):
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
            app.stop_event.set()
            try:
                await asyncio.wait_for(asyncio.shield(app.task), 25)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                app.task.cancel()
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
