import os
import random
import subprocess
import tempfile
import unittest
from unittest import mock

import wifi_motion as wm

PROC_SAMPLE = """Inter-| sta-|   Quality        |   Discarded packets               | Missed | WE
 face | tus | link level noise |  nwid  crypt   frag  retry   misc | beacon | 22
 wlp2s0: 0000   54.  -56.  -256        0      0      0      0     12        0
"""


class ProcParserTest(unittest.TestCase):
    def _source(self, text, iface=None):
        fd, path = tempfile.mkstemp()
        with os.fdopen(fd, "w") as f:
            f.write(text)
        self.addCleanup(os.remove, path)
        with mock.patch.object(wm.LinuxProcSource, "PATH", path):
            src = wm.LinuxProcSource(iface)
        src.PATH = path
        return src

    def test_reads_dbm(self):
        src = self._source(PROC_SAMPLE)
        self.assertEqual(src.read(), -56.0)
        self.assertEqual(src.iface, "wlp2s0")

    def test_legacy_unsigned_level(self):
        src = self._source(PROC_SAMPLE.replace("-56.", "200."))
        self.assertEqual(src.read(), -56.0)

    def test_disconnected_raises(self):
        with self.assertRaises(wm.SourceError):
            self._source(PROC_SAMPLE.replace("-56.", "0."))

    def test_wrong_iface_raises(self):
        with self.assertRaises(wm.SourceError):
            self._source(PROC_SAMPLE, iface="wlan9")


class CommandParserTest(unittest.TestCase):
    def _run(self, stdout):
        return mock.patch.object(
            wm.subprocess, "run",
            return_value=subprocess.CompletedProcess([], 0, stdout=stdout),
        )

    def test_iw(self):
        src = wm.LinuxIwSource.__new__(wm.LinuxIwSource)
        src.iface = "wlan0"
        with self._run("Connected to aa:bb\n\tsignal: -61 dBm\n"):
            self.assertEqual(src.read(), -61.0)

    def test_netsh(self):
        src = wm.WindowsNetshSource.__new__(wm.WindowsNetshSource)
        src.iface = None
        with self._run("    Name : Wi-Fi\n    Signal : 80%\n"):
            self.assertEqual(src.read(), -60.0)


def run_detector(samples, rate=10.0, **kw):
    det = wm.Detector(rate=rate, **kw)
    cal_n = int(20 * rate)
    det.calibrate(samples[:cal_n])
    states = []
    for i, v in enumerate(samples[cal_n:], start=cal_n):
        states.append(det.update(i / rate, v))
    return det, states


class DetectorTest(unittest.TestCase):
    def test_quiet_room_stays_empty(self):
        rng = random.Random(0)
        samples = [round(-50 + rng.gauss(0, 0.6)) for _ in range(10 * 120)]
        _, states = run_detector(samples)
        self.assertEqual(set(states), {wm.EMPTY})

    def test_perfectly_flat_baseline_does_not_trigger_on_flicker(self):
        samples = [-50.0] * 300
        samples[250] = -51.0  # single 1 dB flicker
        _, states = run_detector(samples)
        self.assertNotIn(wm.MOTION, states)

    def test_simulated_story(self):
        src = wm.SimulatedSource(rate=10.0)
        samples = [src.read() for _ in range(10 * 150)]
        _, states = run_detector(samples)
        at = lambda sec: states[int((sec - 20) * 10)]
        self.assertEqual(at(40), wm.EMPTY)
        self.assertEqual(at(52), wm.MOTION)
        self.assertEqual(at(80), wm.PRESENT)   # still person (mean shift)
        self.assertEqual(at(105), wm.MOTION)
        self.assertEqual(at(125), wm.PRESENT)  # hold after leaving
        self.assertEqual(at(148), wm.EMPTY)

    def test_requires_enough_calibration(self):
        with self.assertRaises(ValueError):
            wm.Detector(rate=10).calibrate([-50.0] * 5)

    def test_baseline_adapts_to_slow_drift_when_empty(self):
        rng = random.Random(2)
        # Signal drifts 4 dB over 20 minutes (e.g. router power change).
        samples = [round(-50 - 4 * i / 12000 + rng.gauss(0, 0.5)) for i in range(12200)]
        det, states = run_detector(samples, adapt_tau=120)
        self.assertEqual(states[-1], wm.EMPTY)
        self.assertLess(abs(det.shift), 3.0)


if __name__ == "__main__":
    unittest.main()
