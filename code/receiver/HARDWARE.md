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
| GP15 | 20 | Servo signal | 50Hz, working range 550–2450µs |
| GP26 | 31 | Battery sense (ADC0) | Through 100kΩ/33kΩ divider, ratio 4.03 |
| VSYS | 39 | 5V logic rail in | Fed from L7805 OUT, shared with servo VCC |

None of these conflict with the Pico W's wireless-reserved pins (GP23/24/25/29 are used internally
by the CYW43439 radio).

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

One ~50Hz loop in `main.py`, nothing in it blocks (`time.sleep_ms` only inside the
reverse-coast handling in `motor.py`, ported unchanged from the validated bench script).

## Calibration data baked into `config.py`

- **Motor deadband (7.2V NiMH, measured):** ~0.35 duty is the floor of the throttle mapping
  (`MOTOR_MIN_DUTY`), so joystick input past the deadzone always produces real motion instead of a
  dead patch of "commanded but too low to move."
- **Servo range:** true mechanical endpoints 500–2500µs (`SERVO_HARD_MIN/MAX_US`), working range
  550–2450µs (`SERVO_MIN/MAX_US`). Measured on a 9g plastic-gear substitute, not yet re-confirmed on
  the real MG90S once it's installed.
- **Servo centre (`SERVO_CENTER_US = 1500`) is a placeholder** — just the pulse-width midpoint, not a
  physically-calibrated value. The real MG90S hasn't been mounted on the steering linkage yet. Once it
  is, find true centre (wheels pointed straight) with the bench script's `us` command and update this.

## Still open / needs physical verification

- DFRobot VS–GND decoupling caps: recommended, not confirmed installed.
- Real MG90S not yet installed — servo endpoint and stall-sag numbers on file are from plastic-gear
  substitutes (DF0GMS, later SG90), not the final part.
- Battery divider resistor orientation (which resistor sits on which side) is inferred from the math,
  not continuity-checked against the physical build.
- Servo-stall + simultaneous max-duty motor load has never been tested together.
- `SERVO_CENTER_US` needs real calibration once the steering linkage is assembled.
