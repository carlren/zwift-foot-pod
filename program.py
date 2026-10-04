"""Build, then optionally flash the one connected XIAO Sense (application only)."""
import argparse
import getpass
import os
from pathlib import Path
import subprocess
import time

import serial
from serial.tools import list_ports

ROOT = Path(__file__).resolve().parent
FQBN = "Seeeduino:nrf52:xiaonRF52840Sense"


def board():
    ports = [p for p in list_ports.comports() if p.vid == 0x2886 and p.pid in (0x8045, 0x0045)]
    if len(ports) != 1:
        raise RuntimeError(f"Expected one XIAO Sense, found {len(ports)}")
    return ports[0]


def access(port):
    if not os.access(port, os.R_OK | os.W_OK):
        subprocess.run(["sudo", "-n", "setfacl", "-m", f"u:{getpass.getuser()}:rw", port], check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--upload", action="store_true")
    args = parser.parse_args()
    subprocess.run([
        str(ROOT / "tools/arduino-cli"), "compile", "--fqbn", FQBN,
        "--build-property", "compiler.c.extra_flags=-DNRFX_TWIM_ENABLED=1 -DNRFX_TWIM1_ENABLED=1",
        "--build-property", "compiler.cpp.extra_flags=-DNRFX_TWIM_ENABLED=1 -DNRFX_TWIM1_ENABLED=1",
        "--build-property", f"tools.nrfutil.cmd={ROOT}/.venv/bin/adafruit-nrfutil",
        "--build-property", f'recipe.objcopy.uf2.pattern="{ROOT}/.venv/bin/python" '
        '"{runtime.platform.path}/tools/uf2conv/uf2_wrap.py" '
        '"{runtime.platform.path}/tools/uf2conv/uf2conv.py" "{build.board}" '
        '"{build.path}" "{build.source.path}" "{build.project_name}"',
        "--output-dir", str(ROOT / "build"), str(ROOT / "footpod")
    ], check=True)
    if not args.upload:
        return
    port = board()
    access(port.device)
    if port.pid != 0x0045:
        try:
            with serial.Serial(port.device, 1200) as handle:
                handle.dtr = False
        except OSError as error:
            # USB may disappear before the 1200-baud control request returns.
            if error.errno not in (5, 19, 71):
                raise
        deadline = time.monotonic() + 12
        while time.monotonic() < deadline:
            try:
                port = board()
                if port.pid == 0x0045:
                    break
            except RuntimeError:
                pass
            time.sleep(0.2)
        else:
            raise RuntimeError("Bootloader did not appear; double tap RESET, then retry")
    access(port.device)
    subprocess.run([str(ROOT / ".venv/bin/adafruit-nrfutil"), "dfu", "serial",
                    "-pkg", str(ROOT / "build/footpod.ino.zip"), "-p", port.device,
                    "-b", "115200", "--singlebank"], check=True)
    deadline = time.monotonic() + 12
    while time.monotonic() < deadline:
        try:
            port = board()
            if port.pid == 0x8045:
                access(port.device)
                print("Firmware running on", port.device)
                return
        except RuntimeError:
            pass
        time.sleep(0.2)
    raise RuntimeError("Application did not re-enumerate")


if __name__ == "__main__":
    main()
