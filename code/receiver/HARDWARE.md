# Receiver hardware — validated architecture

Pulled from the Week 1–3 engineering logbook so this lives in git and not only in a Google Doc.
If something here disagrees with the logbook, the logbook wins — this is a snapshot, not the
source of truth.

## Pin map

| Pico GPIO | Physical pin | Function | Notes |
|---|---|---|---|
| GP16 | 21 | DFRobot E1 | Motor A — PWM speed |
| GP17 | 22 | DFRobot M1 | Motor A — direction |
| GP18 | 24 | DFRobot E2 | Motor B — PWM speed |
| GP19 | 25 | DFRobot M2 | Motor B — direction |
| GP15 | 20 | Servo signal | 50Hz, steering range 1250–1750µs (±45°) |
| GP26 | 31 | Battery sense (ADC0) | Through 100kΩ/33kΩ divider, ratio 4.03 |
| VSYS | 39 | 5V logic rail in | Fed from L7805 OUT, shared with servo VCC |

None of these conflict with the Pico W's wireless-reserved pins (GP23/24/25/29 are used internally
by the CYW43439 radio).

## Motor mounting — the two channels run opposite

The motors sit mirrored on either side of the chassis, so driving the car forward means the two
H-bridge channels turn in **opposite electrical directions**. Bench-confirmed: it was the bring-up
script's `sp` (counter-rotate) command that actually drove the car forward, not `f`.

That's handled once, in `config.M2_INVERT = True`, so nothing above the driver layer has to know
about it — `throttle.py` hands both motors the same signed duty and `motor.py` turns M2's half into
the right physical direction. The bench script carries the same flag for the same reason, so `f`
means forward in both places.

If a motor ever gets rewired or remounted, `M1_INVERT`/`M2_INVERT` are the only two things to
touch. `receiver_tests/test_motor.py` pins the behaviour.

## Power architecture

Two isolated rails downstream of one master rocker switch:

- **Motor rail:** 6xAA NiMH pack (7.2V nominal) straight to the DFRobot DRI0002's VS. VD=VS jumper
  shorted (single-supply, pack is under the driver's 12V ceiling). **Do not connect anything to the
  DFRobot's onboard 5V header** — it shares a supply node with the driver's own logic, and loading it
  with the servo was root-caused as a contributor to the original MG90S failure.
- **Logic rail:** same pack → L7805 → Pico VSYS + servo VCC, single common ground bus across
  everything. This isolation is bench-confirmed (no cross-load interaction between the two rails).

**Decoupling (L7805, confirmed installed):**

| Location | Ceramic | Electrolytic |
|---|---|---|
| Input | 330nF | 100µF |
| Output | 100nF | 470µF |

**DFRobot VS–GND decoupling (100µF electrolytic + 100nF ceramic near the terminal) is only a
recommendation — not confirmed fitted.** Check before final assembly.

**Known margin, already accepted for v1:** at full duty, the pack sags to ~6.66V under load. That's
below the L7805's clean-regulation floor (~7–7.5V, 2V dropout spec) and only ~0.16V above the
DRI0002's 6.5V logic-supply minimum. No resets observed in bench testing, but it's thin. This is why
8xAA is already planned for v2 — not a new problem, just worth knowing it's there.

## Control architecture

```
BLE packet (protocol.py)
   -> decode + validate (magic byte, checksum, range)
   -> throttle.py / steering.py: deadzone -> map to output range -> non-blocking ramp
   -> motor.py / servo.py: hardware drivers
failsafe.py watches "time since last valid packet" every loop tick, overrides
throttle/steering targets to 0/centre when stale or on a BLE disconnect event.
```

One ~50Hz loop in `main.py`, nothing in it blocks. The one `time.sleep_ms` is the reverse-coast in
`motor.py`, and it now only fires for a motor that's genuinely spinning
(`REVERSE_COAST_MIN_DUTY`) — the throttle ramp walks duty through zero on its way to reverse, so
without that guard the direction flip was blocking the loop, failsafe included, to protect a motor
that had already stopped.

## Calibration data baked into `config.py`

- **Motor deadband (7.2V NiMH, measured):** ~0.35 duty is the floor of the throttle mapping
  (`MOTOR_MIN_DUTY`), so joystick input past the deadzone always produces real motion instead of a
  dead patch of "commanded but too low to move."
- **Servo hard limits:** true mechanical endpoints 500–2500µs (`SERVO_HARD_MIN/MAX_US`), measured on a
  9g plastic-gear substitute and not yet re-confirmed on the real MG90S. These are a last-ditch
  backstop inside `servo.py`, *not* the steering range — steering never goes near them.
- **Steering range: ±45° off centre, i.e. 1250–1750µs** (`SERVO_STEER_MIN/MAX_US`, derived from
  `STEER_LIMIT_DEG`). Full stick lock is 45°, not whatever the servo can physically sweep.
  `steering.py` clamps to those two pulse widths, so nothing — bad input, a config mistake, a future
  caller — can walk the linkage past its stops.
- **Degrees mean the same thing here as on the bench.** `config.SERVO_ANGLE_MIN/MAX_US` (1000µs =
  0°, 2000µs = 180°) is the identical frame the bench script's `s <deg>` command uses, so the
  steering limits are exactly its `s 45` and `s 135`. An angle found by hand on the bench transfers
  to this code with nothing to convert.
- **Servo centre (`SERVO_CENTER_US = 1500`) is a placeholder** — just the pulse-width midpoint (the
  bench script's `s 90`), not a physically-calibrated value. The real MG90S hasn't been mounted on the
  steering linkage yet. Once it is, find true centre (wheels pointed straight) with the bench script's
  `us` command and update this; the ±45° window shifts with it automatically.

## Still open / needs physical verification

- DFRobot VS–GND decoupling caps: recommended, not confirmed installed.
- Real MG90S not yet installed — servo endpoint and stall-sag numbers on file are from plastic-gear
  substitutes (DF0GMS, later SG90), not the final part.
- Battery divider resistor orientation (which resistor sits on which side) is inferred from the math,
  not continuity-checked against the physical build.
- Servo-stall + simultaneous max-duty motor load has never been tested together.
- `SERVO_CENTER_US` needs real calibration once the steering linkage is assembled.
- Whether ±45° is the right steering throw for this linkage, or whether it binds before that. The
  number comes from the design intent, not from a measured mechanical stop — sweep it with the bench
  script's `sw` command before driving it in anger.
- BLE range, packet loss rate, and how well `FAILSAFE_TIMEOUT_MS` is tuned to real-world drops. The
  link now comes up (see the receiver README's troubleshooting note) but has never been run at
  distance.
