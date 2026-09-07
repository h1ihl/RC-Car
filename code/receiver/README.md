# Receiver firmware

MicroPython firmware for the car-side Pico WH. See `HARDWARE.md` for the pin map, power
architecture, and calibration data this code is built around.

## Files

| File | What it does |
|---|---|
| `main.py` | Entry point -- the ~50Hz control loop. Flash this as `main.py` to run on boot. |
| `config.py` | Every tunable constant (deadzones, ramp rates, servo range, failsafe timeout, pins). |
| `protocol.py` | The BLE packet format -- encode/decode, validation. |
| `motor.py`, `servo.py`, `battery.py` | Hardware drivers, ported from the bench bring-up script. |
| `throttle.py`, `steering.py` | Deadzone + ramp + output mapping for each control axis. |
| `ble_link.py` | BLE GATT peripheral -- advertises, receives control packets. |
| `failsafe.py` | Kills the car if valid packets stop arriving or the link drops. |
| `diagnostics.py` | LED heartbeat + periodic REPL status line. |

## Flashing

1. Flash the Pico WH with MicroPython (Pico W build) if it isn't already -- see
   [micropython.org/download/RPI_PICO_W](https://micropython.org/download/RPI_PICO_W/).
2. Open Thonny, connect to the Pico.
3. Copy every `.py` file in this folder onto the Pico's filesystem (Thonny's file browser --
   right-click each file, "Upload to /").
4. `main.py` runs automatically on boot/power-up once it's on the Pico.

**While still testing/tuning**, don't rely on the auto-run -- open `main.py` in Thonny and run it
with F5 instead, same reasoning as the old bench script: you want Ctrl-C to be able to kill
everything instantly if something's not right.

## Testing without hardware

`../receiver_tests/` runs the actual control logic (packet validation, throttle/steering ramping,
failsafe timing) on a desktop Python install by mocking `machine`/`bluetooth`. From that folder:

```
python -m unittest discover -v
```

This does **not** test real BLE radio behaviour (advertising, scanning, connecting) or anything
physically hardware-dependent (real motor/servo response, actual RF range) -- those need two real
Pico Ws. See the final report for the full list of what's logic-verified vs. still needs on-car
testing.

## Testing with hardware (two Pico Ws)

1. Flash the receiver (this folder) onto the car's Pico W as above.
2. Flash `../test_transmitter/ble_test_tx.py` onto a second Pico W as its `main.py` (or run it with
   F5 from Thonny).
3. Power both up. The test transmitter scans, connects, and runs a scripted throttle/steering
   sequence, including a deliberate silence to check the receiver's failsafe actually trips.
4. Watch the receiver's REPL output (diagnostics prints pack voltage, link state, failsafe state,
   current throttle/steer once a second) and the LED heartbeat pattern.

For driving it with actual joysticks instead of the scripted sequence, flash `../transmitter/`
(the real transmitter) onto the second Pico W instead -- see its README.

## Troubleshooting: the transmitter can't find the receiver

This one already bit us once, and the cause was entirely on the receiver's side.

A BLE advertising packet's payload is **31 bytes, hard limit**. Flags (3) plus a 128-bit service
UUID (18) is already 21 of them, and the device name costs another `2 + len(name)` -- 15 bytes for
`RCCarReceiver`, which put the total at 36. MicroPython rejects an oversized payload outright, so
`gap_advertise()` raised, the receiver never advertised at all, and from the transmitter's side that
looks exactly like "the car isn't there."

The name lives in the **scan response** now, which gets its own separate 31-byte budget. Both
transmitters find the car by matching the service UUID, which stays in the main payload where a
passive scan can see it. `receiver_tests/test_ble_link.py` pins the sizes so it can't creep back
over.

If pairing fails again, check in this order:

1. **Is the receiver advertising at all?** Watch its REPL on boot -- an exception out of
   `BLEReceiverLink` means it never started. Anything that grows the advertising payload (a longer
   `BLE_DEVICE_NAME`, a second advertised UUID) is the first suspect.
2. **Do the UUIDs match?** `receiver_tests/test_tx_stub_compat.py` and
   `transmitter_tests/test_receiver_compat.py` check this, since both transmitters copy-paste them.
3. **Is something else already connected to the receiver?** It stops advertising while a central is
   connected. Power-cycle the other board.
4. **Are both boards running a Pico W build of MicroPython?** A plain Pico build has no `bluetooth`
   module and the import fails.

A phone BLE scanner app is the quickest way to settle question 1 -- the car shows up as
`RCCarReceiver` if it's advertising properly.
