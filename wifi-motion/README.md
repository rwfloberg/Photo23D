# WiFi Motion Detector

Detects movement and presence in a room using only your laptop's WiFi
connection. You don't need extra hardware.

When a person moves between your computer and the WiFi router, their body
absorbs and reflects the radio signal, so the received signal strength (RSSI)
wobbles. This script samples RSSI about 10 times a second, learns what the
empty room looks like, and reports:

| State     | Meaning |
|-----------|---------|
| `MOTION`  | The signal is fluctuating much more than in the empty room |
| `PRESENT` | Motion was seen in the last 30 s, or the average signal has shifted by 3 dB or more (someone sitting still in the signal path) |
| `EMPTY`   | The signal looks like the calibration baseline |

## Quick start

```bash
# Try it without WiFi (runs a scripted 2.5-minute story at 10x speed)
python3 wifi_motion.py --simulate --speed 10

# Real WiFi: leave the room empty for the first 20 seconds while it calibrates
python3 wifi_motion.py
```

Requirements: Python 3.8+.

| Platform | How it reads RSSI | Setup |
|----------|-------------------|-------|
| Linux    | `/proc/net/wireless` (falls back to `iw`) | none |
| macOS    | CoreWLAN | `pip3 install pyobjc-framework-CoreWLAN` (or run with `sudo` to use `wdutil`, which is slower) |
| Windows  | `netsh wlan show interfaces` | none, but the signal comes as a coarse percentage that updates slowly, so expect weak results |

The computer must be connected to a WiFi network.

## Getting good results

- **Placement matters most.** The detector senses the path between the
  laptop and the router, so put the area you want to watch on that line. A
  doorway between the two works well.
- **Keep the laptop still** and plugged in. Moving it, or letting it go to
  power-saving, changes the signal far more than a person does.
- **Calibrate in an empty room.** Use `--calibrate 60` for a steadier
  baseline.
- **Use `--traffic` on Linux and macOS.** It pings the router in the
  background, so the WiFi card receives frames more often and the reading
  refreshes faster.
- **Tune the sensitivity.** Lower `--sensitivity` (for example `2`) catches
  smaller movements but gives more false alarms. Raise it (for example `5`)
  if it triggers when nobody is there.

## Options

```
--calibrate SEC     empty-room baseline length (default 20)
--sensitivity N     motion threshold in baseline std-devs (default 3)
--window SEC        motion analysis window (default 2)
--hold SEC          stay PRESENT this long after motion stops (default 30)
--presence-db DB    mean signal shift that counts as presence (default 3)
--traffic           ping the router to get more frequent RSSI updates
--log FILE.csv      record every sample (timestamp, rssi, score, shift, state)
--on-change CMD     run a shell command on each state change
--quiet             print state changes only (good for logging/services)
--iface NAME        choose the wireless interface
--simulate          synthetic data; --speed N runs it N times faster
--duration SEC      stop after this long
```

Example: show a desktop notification when motion starts (Linux):

```bash
python3 wifi_motion.py --quiet --traffic \
  --on-change '[ "$WIFI_MOTION_STATE" = MOTION ] && notify-send "Motion detected"'
```

## How it works

1. **Calibrate.** It records RSSI for N seconds and computes the rolling
   standard deviation over 2-second windows. The motion threshold is set to
   the mean of those values plus `sensitivity` × their standard deviation,
   with a floor so that 1 dB flickers in a very quiet room don't trigger it.
2. **Motion score.** This is the standard deviation of the last 2 s of
   samples divided by the threshold. A score above 1.0 for 0.5 s starts
   `MOTION`. A score below 0.8 for 2 s ends it.
3. **Presence.** It reports `PRESENT` if there was motion within `--hold`
   seconds, or if the 10-second average has moved more than `--presence-db`
   from the baseline.
4. **Drift.** While the room is `EMPTY`, the baseline slowly follows the
   signal (5-minute time constant). This absorbs gradual changes in the
   router or the environment without absorbing a person who walked in and
   sat down.

## Limitations

This is the cheap version of WiFi sensing. The demos online that show body
outlines through walls use Channel State Information (CSI): the amplitude and
phase on dozens of subcarriers across several antennas, fed to a neural
network. RSSI is a single number per packet, rounded to 1 dB, so the
detector:

- reliably notices someone **walking through** the laptop-to-router path;
- may miss movement off to the side of that path, or in large rooms;
- can detect a **still** person only if they noticeably block the signal;
- can be fooled by microwave ovens, other traffic on the network, the router
  changing channel or power, or the laptop roaming to another access point;
- can't count people, locate them, or see poses.

If you want better sensing later, the next step is an ESP32 board with CSI
firmware (about $5-10), which gives far richer data.

## Tests

```bash
python3 -m unittest -v test_wifi_motion
```
