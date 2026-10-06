"""Small repeatable checks for the actual live detector and dashboard request validation."""
import asyncio
from pathlib import Path
import tempfile

from dashboard import Dashboard, Detector, recording_args, settings


def point(t, magnitude=1):
    return dict(time_s=t, sequence=int(t*100), accel=[0, 0, magnitude], gyro=[0, 0, 0], missing=0)


def main():
    for spm in (109, 180):
        detector = Detector()
        period = 120 / spm
        for i in range(1000):
            t = i/100
            result = detector.update(point(t, 1.6 if (t % period) < .04 else 1))
        assert abs(result["cadence"] - spm) < 2, result
        assert result["strikes"] >= 8
        assert 0 <= result["rhythm"] <= 1
        assert detector.update(point(14))["cadence"] == 0
    detector = Detector()
    assert detector.update(point(0, 1.6))["strike"]
    detector.update(point(.1))
    assert not detector.update(point(.2, 1.6))["strike"]
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
    loop = asyncio.new_event_loop()
    app = Dashboard(loop)
    with tempfile.TemporaryDirectory() as directory:
        app.update(dict(phase="streaming", directory=directory))
        app.sample(point(0, 1.6))
        app.sample(point(.6))
        snapshot = app.snapshot(1)
        assert len(snapshot["points"]) == 1 and snapshot["cursor"] == 2
        app.fit_handle.flush()
        assert len((Path(directory)/"fit.csv").read_text().splitlines()) == 3
        app.fit_handle.close()
    loop.close()
    print("PASS: cadence at 109/180 spm, stop timeout, duplicate-strike guard, input validation, live snapshots, fit CSV")


if __name__ == "__main__":
    main()
