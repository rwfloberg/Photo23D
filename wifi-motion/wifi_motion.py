#!/usr/bin/env python3
"""WiFi RSSI motion & presence detector.

People moving between your laptop and the WiFi router absorb and reflect the
2.4/5 GHz signal, which makes the received signal strength (RSSI) wobble.
This script samples the RSSI of your current WiFi connection several times a
second, learns what an empty room looks like, and reports:

  MOTION   - the signal is fluctuating much more than in the empty room
  PRESENT  - motion was seen recently, or the average signal has shifted
             (a person standing still in the signal path)
  EMPTY    - looks like the calibration baseline

No extra hardware and no third-party packages are needed on Linux or Windows.
On macOS it uses CoreWLAN through PyObjC (`pip install pyobjc-framework-CoreWLAN`).

Run `python3 wifi_motion.py --help` for options, or `--simulate` to try it
without WiFi.
"""

from __future__ import annotations

import argparse
import collections
import csv
import math
import os
import platform
import random
import re
import shutil
import statistics
import subprocess
import sys
import time
from typing import Deque, List, Optional

# --------------------------------------------------------------------------
# RSSI sources
# --------------------------------------------------------------------------


class SourceError(RuntimeError):
    pass


class RSSISource:
    name = "base"

    def read(self) -> Optional[float]:
        """Return the current signal level in dBm, or None if unavailable."""
        raise NotImplementedError

    def close(self) -> None:
        pass


class LinuxProcSource(RSSISource):
    """Reads /proc/net/wireless (fast, no subprocess)."""

    name = "linux /proc/net/wireless"
    PATH = "/proc/net/wireless"

    def __init__(self, iface: Optional[str] = None):
        self.iface = iface
        if not os.path.exists(self.PATH):
            raise SourceError(f"{self.PATH} not found")
        if self.read() is None:
            raise SourceError(
                "no connected wireless interface in /proc/net/wireless"
                + (f" named {iface}" if iface else "")
            )

    def read(self) -> Optional[float]:
        with open(self.PATH) as f:
            lines = f.readlines()[2:]
        for line in lines:
            if ":" not in line:
                continue
            name, rest = line.split(":", 1)
            name = name.strip()
            if self.iface and name != self.iface:
                continue
            fields = rest.split()
            if len(fields) < 3:
                continue
            try:
                level = float(fields[2].rstrip("."))
            except ValueError:
                continue
            if level == 0:
                continue  # interface present but not associated
            if level > 0:  # some older drivers report 256 + dBm
                level -= 256
            self.iface = name
            return level
        return None


class LinuxIwSource(RSSISource):
    """Fallback: parses `iw dev <iface> link`."""

    name = "linux iw"

    def __init__(self, iface: Optional[str] = None):
        if not shutil.which("iw"):
            raise SourceError("`iw` not installed")
        self.iface = iface or self._find_iface()
        if not self.iface:
            raise SourceError("no wireless interface found via `iw dev`")
        if self.read() is None:
            raise SourceError(f"{self.iface} is not connected to a network")

    @staticmethod
    def _find_iface() -> Optional[str]:
        out = subprocess.run(["iw", "dev"], capture_output=True, text=True).stdout
        m = re.search(r"Interface\s+(\S+)", out)
        return m.group(1) if m else None

    def read(self) -> Optional[float]:
        out = subprocess.run(
            ["iw", "dev", self.iface, "link"], capture_output=True, text=True
        ).stdout
        m = re.search(r"signal:\s*(-?\d+)\s*dBm", out)
        return float(m.group(1)) if m else None


class MacCoreWLANSource(RSSISource):
    """macOS: CoreWLAN via PyObjC. Fast and needs no sudo."""

    name = "macOS CoreWLAN"

    def __init__(self, iface: Optional[str] = None):
        try:
            import CoreWLAN  # type: ignore
        except ImportError as e:
            raise SourceError(
                "PyObjC CoreWLAN missing - run: pip3 install pyobjc-framework-CoreWLAN"
            ) from e
        client = CoreWLAN.CWWiFiClient.sharedWiFiClient()
        self._if = client.interfaceWithName_(iface) if iface else client.interface()
        if self._if is None:
            raise SourceError("no WiFi interface found")
        if self.read() is None:
            raise SourceError("WiFi is not connected to a network")

    def read(self) -> Optional[float]:
        v = self._if.rssiValue()
        return float(v) if v else None


class MacWdutilSource(RSSISource):
    """macOS fallback: `sudo wdutil info` (slow, needs root)."""

    name = "macOS wdutil"

    def __init__(self, iface: Optional[str] = None):
        if not shutil.which("wdutil"):
            raise SourceError("`wdutil` not found")
        if os.geteuid() != 0:
            raise SourceError("`wdutil` needs sudo")
        if self.read() is None:
            raise SourceError("wdutil reported no RSSI (WiFi not connected?)")

    def read(self) -> Optional[float]:
        out = subprocess.run(["wdutil", "info"], capture_output=True, text=True).stdout
        m = re.search(r"RSSI\s*:\s*(-?\d+)\s*dBm", out)
        return float(m.group(1)) if m else None


class WindowsNetshSource(RSSISource):
    """Windows: `netsh wlan show interfaces` (signal is a coarse percentage)."""

    name = "windows netsh"

    def __init__(self, iface: Optional[str] = None):
        self.iface = iface
        if self.read() is None:
            raise SourceError("netsh reported no connected WiFi interface")

    def read(self) -> Optional[float]:
        out = subprocess.run(
            ["netsh", "wlan", "show", "interfaces"], capture_output=True, text=True
        ).stdout
        blocks = re.split(r"\n\s*\n", out)
        for block in blocks:
            if self.iface and self.iface not in block:
                continue
            m = re.search(r"Signal\s*:\s*(\d+)\s*%", block)
            if m:
                # Windows maps roughly -100 dBm..-50 dBm onto 0..100 %.
                return int(m.group(1)) / 2.0 - 100.0
        return None


class SimulatedSource(RSSISource):
    """Synthetic RSSI with a scripted story, for trying the tool without WiFi.

    Timeline (in simulated seconds):
        0-45    empty room
        45-60   someone walks around
        60-100  they sit still in the signal path (mean drops a few dB)
        100-110 they walk out
        110+    empty again
    """

    name = "simulator"

    def __init__(self, rate: float, seed: int = 1):
        self.rate = rate
        self.n = 0
        self.rng = random.Random(seed)
        self.base = -55.0

    def sim_time(self) -> float:
        return self.n / self.rate

    def read(self) -> Optional[float]:
        t = self.sim_time()
        self.n += 1
        noise = self.rng.gauss(0, 0.6)
        if 45 <= t < 60 or 100 <= t < 110:
            # Body crossing the Fresnel zone: slow multipath fades + jitter.
            fade = 4.0 * math.sin(2 * math.pi * 0.7 * t) + self.rng.gauss(0, 2.0)
            value = self.base - 2.0 + fade + noise
        elif 60 <= t < 100:
            # Still person: attenuated mean, breathing adds a tiny wobble.
            value = self.base - 4.5 + 0.3 * math.sin(2 * math.pi * 0.25 * t) + noise
        else:
            value = self.base + noise
        return float(round(value))  # real drivers report whole dBm


def open_source(iface: Optional[str]) -> RSSISource:
    system = platform.system()
    if system == "Linux":
        candidates = [LinuxProcSource, LinuxIwSource]
    elif system == "Darwin":
        candidates = [MacCoreWLANSource, MacWdutilSource]
    elif system == "Windows":
        candidates = [WindowsNetshSource]
    else:
        raise SourceError(f"unsupported platform: {system}")
    errors = []
    for cls in candidates:
        try:
            return cls(iface)
        except SourceError as e:
            errors.append(f"  {cls.name}: {e}")
        except OSError as e:
            errors.append(f"  {cls.name}: {e}")
    raise SourceError("could not read WiFi signal strength:\n" + "\n".join(errors))


# --------------------------------------------------------------------------
# Optional background traffic (more received frames = fresher RSSI)
# --------------------------------------------------------------------------


def default_gateway() -> Optional[str]:
    system = platform.system()
    try:
        if system == "Linux":
            out = subprocess.run(["ip", "route"], capture_output=True, text=True).stdout
            m = re.search(r"default via (\S+)", out)
        elif system == "Darwin":
            out = subprocess.run(
                ["route", "-n", "get", "default"], capture_output=True, text=True
            ).stdout
            m = re.search(r"gateway:\s*(\S+)", out)
        else:
            return None
    except OSError:
        return None
    return m.group(1) if m else None


def start_traffic() -> Optional[subprocess.Popen]:
    gw = default_gateway()
    if not gw or not shutil.which("ping"):
        return None
    return subprocess.Popen(
        ["ping", "-i", "0.2", gw],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


# --------------------------------------------------------------------------
# Detection
# --------------------------------------------------------------------------

EMPTY, PRESENT, MOTION = "EMPTY", "PRESENT", "MOTION"


def rolling_std(values: List[float], window: int) -> List[float]:
    out = []
    for i in range(window, len(values) + 1):
        out.append(statistics.pstdev(values[i - window : i]))
    return out


class Detector:
    """Turns a stream of RSSI samples into EMPTY / PRESENT / MOTION.

    motion score  = std-dev of RSSI over a short window, divided by the
                    threshold learned from the empty room (>1 means motion)
    presence      = motion within the last `hold` seconds, or the long-window
                    mean has drifted more than `presence_db` from baseline
    """

    def __init__(
        self,
        rate: float,
        window: float = 2.0,
        sensitivity: float = 3.0,
        hold: float = 30.0,
        presence_db: float = 3.0,
        presence_window: float = 10.0,
        adapt_tau: float = 300.0,
    ):
        self.rate = rate
        self.win_n = max(3, int(round(window * rate)))
        self.mean_n = max(self.win_n, int(round(presence_window * rate)))
        self.sensitivity = sensitivity
        self.hold = hold
        self.presence_db = presence_db
        self.adapt_alpha = 1.0 / max(1.0, adapt_tau * rate)
        self.trigger_n = max(1, int(round(0.5 * rate)))
        self.release_n = max(1, int(round(2.0 * rate)))

        self.buf: Deque[float] = collections.deque(maxlen=self.mean_n)
        self.base_mean: Optional[float] = None
        self.threshold: Optional[float] = None
        self.state = EMPTY
        self.score = 0.0
        self.shift = 0.0
        self._above = 0
        self._below = 0
        self._motion_active = False
        self._last_motion_t = -math.inf

    @property
    def calibrated(self) -> bool:
        return self.threshold is not None

    def calibrate(self, samples: List[float]) -> None:
        if len(samples) < self.win_n * 3:
            raise ValueError(
                f"need at least {self.win_n * 3} calibration samples, got {len(samples)}"
            )
        stds = rolling_std(samples, self.win_n)
        mu = statistics.fmean(stds)
        sigma = statistics.pstdev(stds)
        # Integer-dBm readings in a quiet room can give near-zero variance,
        # so enforce a floor to avoid triggering on single 1 dB flickers.
        self.threshold = max(mu + self.sensitivity * sigma, mu + 0.5, 0.75)
        self.base_mean = statistics.fmean(samples)
        self.buf.clear()
        self.buf.extend(samples[-self.mean_n :])

    def update(self, t: float, rssi: float) -> str:
        if not self.calibrated:
            raise RuntimeError("call calibrate() first")
        self.buf.append(rssi)
        recent = list(self.buf)[-self.win_n :]
        self.score = statistics.pstdev(recent) / self.threshold
        self.shift = statistics.fmean(self.buf) - self.base_mean

        # Debounced motion with hysteresis.
        if self.score > 1.0:
            self._above += 1
            self._below = 0
        elif self.score < 0.8:
            self._below += 1
            self._above = 0
        if not self._motion_active and self._above >= self.trigger_n:
            self._motion_active = True
        elif self._motion_active and self._below >= self.release_n:
            self._motion_active = False
        if self._motion_active:
            self._last_motion_t = t

        if self._motion_active:
            state = MOTION
        elif t - self._last_motion_t < self.hold or abs(self.shift) > self.presence_db:
            state = PRESENT
        else:
            state = EMPTY
            # Slowly follow environmental drift while the room looks empty.
            self.base_mean += self.adapt_alpha * (rssi - self.base_mean)

        self.state = state
        return state


# --------------------------------------------------------------------------
# Terminal UI
# --------------------------------------------------------------------------

SPARK = "▁▂▃▄▅▆▇█"
COLORS = {EMPTY: "\033[32m", PRESENT: "\033[33m", MOTION: "\033[1;31m"}
RESET = "\033[0m"


def sparkline(values: List[float], lo: float, hi: float) -> str:
    if hi - lo < 1e-9:
        hi = lo + 1
    out = []
    for v in values:
        idx = int((v - lo) / (hi - lo) * (len(SPARK) - 1))
        out.append(SPARK[min(len(SPARK) - 1, max(0, idx))])
    return "".join(out)


def bar(score: float, width: int = 20) -> str:
    filled = min(width, int(round(score / 2.0 * width)))  # full bar = 2x threshold
    mark = width // 2  # threshold position
    cells = ["█" if i < filled else ("│" if i == mark else "·") for i in range(width)]
    return "".join(cells)


class Display:
    def __init__(self, quiet: bool, color: bool):
        self.quiet = quiet
        self.color = color
        self.tty = sys.stdout.isatty()
        self.history: Deque[float] = collections.deque(maxlen=40)

    def paint(self, state: str) -> str:
        return f"{COLORS[state]}{state:<7}{RESET}" if self.color else f"{state:<7}"

    def event(self, clock: str, msg: str) -> None:
        if self.tty and not self.quiet:
            sys.stdout.write("\r\033[K")
        print(f"[{clock}] {msg}", flush=True)

    def status(self, clock: str, rssi: float, det: Detector) -> None:
        self.history.append(rssi)
        if self.quiet or not self.tty:
            return
        lo = min(self.history) - 1
        hi = max(self.history) + 1
        line = (
            f"\r\033[K[{clock}] {rssi:6.1f} dBm {sparkline(list(self.history), lo, hi):<40} "
            f"motion {bar(det.score)} {det.score:4.1f}x  "
            f"shift {det.shift:+5.1f} dB  {self.paint(det.state)}"
        )
        sys.stdout.write(line)
        sys.stdout.flush()


# --------------------------------------------------------------------------
# Main loop
# --------------------------------------------------------------------------


def run_hook(cmd: str, state: str, rssi: float) -> None:
    env = dict(os.environ, WIFI_MOTION_STATE=state, WIFI_MOTION_RSSI=f"{rssi:.1f}")
    try:
        subprocess.Popen(cmd, shell=True, env=env)
    except OSError as e:
        print(f"hook failed: {e}", file=sys.stderr)


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Detect motion and presence from WiFi signal strength (RSSI)."
    )
    p.add_argument("--iface", help="wireless interface (default: auto-detect)")
    p.add_argument("--rate", type=float, default=10.0, help="samples per second (default 10)")
    p.add_argument(
        "--calibrate", type=float, default=20.0, metavar="SEC",
        help="seconds of empty-room baseline to record at start (default 20)",
    )
    p.add_argument(
        "--sensitivity", type=float, default=3.0,
        help="motion threshold in baseline std-devs; lower = more sensitive (default 3)",
    )
    p.add_argument("--window", type=float, default=2.0, metavar="SEC",
                   help="motion analysis window (default 2 s)")
    p.add_argument("--hold", type=float, default=30.0, metavar="SEC",
                   help="stay PRESENT this long after motion stops (default 30 s)")
    p.add_argument("--presence-db", type=float, default=3.0, metavar="DB",
                   help="mean signal shift that counts as presence (default 3 dB)")
    p.add_argument("--traffic", action="store_true",
                   help="ping the router in the background so RSSI updates more often")
    p.add_argument("--log", metavar="CSV", help="append every sample to a CSV file")
    p.add_argument("--on-change", metavar="CMD",
                   help="shell command to run on state changes "
                        "($WIFI_MOTION_STATE and $WIFI_MOTION_RSSI are set)")
    p.add_argument("--quiet", action="store_true", help="only print state changes")
    p.add_argument("--no-color", action="store_true", help="disable ANSI colors")
    p.add_argument("--simulate", action="store_true",
                   help="use synthetic data instead of real WiFi (demo/testing)")
    p.add_argument("--speed", type=float, default=1.0,
                   help="simulation speed multiplier (only with --simulate)")
    p.add_argument("--duration", type=float, metavar="SEC",
                   help="stop after this many seconds of detection")
    return p.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    color = not args.no_color and sys.stdout.isatty()
    if color and os.name == "nt":
        os.system("")  # enables ANSI escape handling in the Windows console

    if args.simulate:
        source: RSSISource = SimulatedSource(args.rate)
        speed = max(0.01, args.speed)
    else:
        try:
            source = open_source(args.iface)
        except SourceError as e:
            print(e, file=sys.stderr)
            print("Tip: try --simulate to see how it works without WiFi.", file=sys.stderr)
            return 2
        speed = 1.0

    def clock_now() -> float:
        return source.sim_time() if isinstance(source, SimulatedSource) else time.time()

    def clock_str(t: float) -> str:
        if isinstance(source, SimulatedSource):
            return f"sim {t:6.1f}s"
        return time.strftime("%H:%M:%S", time.localtime(t))

    period = 1.0 / args.rate / speed
    traffic = start_traffic() if args.traffic and not args.simulate else None
    det = Detector(
        rate=args.rate,
        window=args.window,
        sensitivity=args.sensitivity,
        hold=args.hold,
        presence_db=args.presence_db,
    )
    disp = Display(args.quiet, color)
    log_file = None
    writer = None
    if args.log:
        new = not os.path.exists(args.log) or os.path.getsize(args.log) == 0
        log_file = open(args.log, "a", newline="")
        writer = csv.writer(log_file)
        if new:
            writer.writerow(["timestamp", "rssi_dbm", "motion_score", "shift_db", "state"])

    def sample() -> Optional[float]:
        try:
            return source.read()
        except (OSError, ValueError):
            return None

    print(f"Source: {source.name}" + (f" ({getattr(source, 'iface', '')})"
          if getattr(source, "iface", None) else ""))
    if traffic:
        print("Generating background ping traffic to the router.")

    try:
        # ---- calibration --------------------------------------------------
        print(
            f"Calibrating for {args.calibrate:.0f} s - leave the area between this "
            "computer and the router empty and keep the computer still..."
        )
        cal: List[float] = []
        n_cal = int(args.calibrate * args.rate)
        next_t = time.monotonic()
        while len(cal) < n_cal:
            v = sample()
            if v is not None:
                cal.append(v)
            next_t += period
            time.sleep(max(0.0, next_t - time.monotonic()))
        det.calibrate(cal)
        print(
            f"Baseline {det.base_mean:.1f} dBm, motion threshold "
            f"{det.threshold:.2f} dB std-dev. Watching... (Ctrl+C to stop)"
        )
        if det.threshold > 3.0:
            print(
                "Warning: the baseline is very noisy. Results may be poor; "
                "make sure the room was empty and nothing was moving.",
                file=sys.stderr,
            )

        # ---- detection ----------------------------------------------------
        last_state = None
        start = clock_now()
        missing = 0
        while True:
            v = sample()
            t = clock_now()
            if v is None:
                missing += 1
                if missing == int(5 * args.rate):
                    disp.event(clock_str(t), "lost WiFi signal reading (disconnected?)")
            else:
                missing = 0
                state = det.update(t, v)
                if state != last_state:
                    if last_state is not None or state != EMPTY:
                        disp.event(clock_str(t), f"{disp.paint(state)} "
                                   f"(rssi {v:.0f} dBm, motion {det.score:.1f}x, "
                                   f"shift {det.shift:+.1f} dB)")
                    if args.on_change and last_state is not None:
                        run_hook(args.on_change, state, v)
                    last_state = state
                disp.status(clock_str(t), v, det)
                if writer:
                    writer.writerow([f"{t:.2f}", f"{v:.1f}", f"{det.score:.3f}",
                                     f"{det.shift:.2f}", state])
            if args.duration and t - start >= args.duration:
                break
            next_t += period
            time.sleep(max(0.0, next_t - time.monotonic()))
    except KeyboardInterrupt:
        pass
    finally:
        if disp.tty and not args.quiet:
            print()
        if traffic:
            traffic.terminate()
        if log_file:
            log_file.close()
        source.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
