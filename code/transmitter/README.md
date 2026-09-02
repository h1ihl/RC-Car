# Transmitter firmware

MicroPython firmware for the handheld Pico W: reads the throttle/steering
joysticks and sends control packets to the car's receiver over BLE.

This is the **real** transmitter -- for the scripted, no-joysticks bench
tool that exercises the wireless path without a controller, see
`../test_transmitter/ble_test_tx.py` instead. That stub stays useful for
testing the receiver in isolation; this is what actually flies.

## Files

| File | What it does |
|---|---|
| `main.py` | Entry point -- calibrates the sticks, then the ~50Hz send loop. Flash this as `main.py` to run on boot. |
| `config.py` | Every tunable constant (pins, invert flags, send rate) -- BLE UUIDs/protocol here must match `../receiver/config.py`. |
| `protocol.py` | The BLE packet encoder -- copy of `../receiver/protocol.py`'s format (separate Pico, separate flash, no shared import). |
| `joystick.py` | Reads the two analog axes, calibrates their rest position at boot, scales to -1..1. |
| `ble_link.py` | BLE GATT central -- scans for the receiver, connects, writes control packets, auto-reconnects. |
| `diagnostics.py` | Onboard LED connection indicator. |

## Pin map (placeholder -- not yet wired/confirmed on real hardware)

| Pico GPIO | Function |
|---|---|
| GP26 (ADC0) | Throttle joystick axis |
| GP27 (ADC1) | Steering joystick axis |

Unlike the receiver's `HARDWARE.md`, there's no bench logbook backing these
yet -- update `config.py`'s `PIN_THROTTLE_ADC`/`PIN_STEERING_ADC` once the
controller enclosure is actually built, and flip `THROTTLE_INVERT`/
`STEERING_INVERT` if an axis comes out backwards.

## Connection LED

- **Slow blink** -- scanning for the receiver, or reconnecting after a drop.
- **Solid on** -- linked up and sending control packets.

Matches the receiver's own LED language (`../receiver/diagnostics.py`): not
connected = slow blink there too, so both boards read the same way.

## Calibration

The joysticks' rest position is measured at boot, not hardcoded -- `main.py`
calibrates both axes on startup, so **leave both sticks released while it's
powering on**. Recalibration just means power-cycling (or re-running from
Thonny) with the sticks at rest.

## Flashing

1. Flash the Pico W with MicroPython if it isn't already.
2. Open Thonny, connect to the Pico.
3. Copy every `.py` file in this folder onto the Pico's filesystem.
4. `main.py` runs automatically on boot/power-up once it's on the Pico.

**While still testing/tuning**, run `main.py` with F5 from Thonny instead of
relying on auto-run, same reasoning as the receiver side.

## Testing without hardware

`../transmitter_tests/` runs the joystick scaling math and BLE central
bookkeeping (not the real radio) on a desktop Python install, same mocking
approach as `../receiver_tests/`. From that folder:

```
python -m unittest discover -v
```

## Testing with hardware

Flash this onto one Pico W and the receiver onto another, power both up, and
move the sticks -- watch this board's LED go solid once it links, and the
receiver's REPL output / LED for the resulting throttle/steering. See
`../receiver/README.md`'s hardware-testing section for the receiver side of
this.
