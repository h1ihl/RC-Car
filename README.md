# RC-Car

A BLE-controlled RC car built on two Raspberry Pi Pico W boards running MicroPython: a handheld
**transmitter** (joysticks) and a car-side **receiver** (motors, steering servo, battery sensing,
failsafe).

## How it works

```
[ joysticks ] -> Transmitter Pico W --BLE--> Receiver Pico W -> [ motors + steering servo ]
                  (BLE central)               (BLE peripheral)
```

- The transmitter calibrates the joystick rest position at boot, then sends a control packet
  (throttle + steering) at ~50 Hz over BLE.
- The receiver validates each packet, applies deadzones and throttle ramping, and drives the
  motors and steering servo.
- If valid packets stop arriving or the link drops, the receiver's failsafe stops the car.

## Repository layout

| Path | What's in it |
|---|---|
| [`code/receiver/`](code/receiver) | Car-side firmware. See its [README](code/receiver/README.md) and [HARDWARE.md](code/receiver/HARDWARE.md) (pin map, power architecture, calibration). |
| [`code/transmitter/`](code/transmitter) | Handheld controller firmware. See its [README](code/transmitter/README.md). |
| [`code/test_transmitter/`](code/test_transmitter) | Scripted BLE test transmitter (no joysticks) for exercising the receiver on its own. |
| [`code/receiver_tests/`](code/receiver_tests), [`code/transmitter_tests/`](code/transmitter_tests) | Desktop unit tests, run with mocked `machine`/`bluetooth`. |
| `code/Test Script.py` | Phase 1 bench bring-up script used to validate the hardware. |

## Getting started

1. Flash the Pico W build of [MicroPython](https://micropython.org/download/RPI_PICO_W/) onto both
   boards.
2. Copy the files from `code/receiver/` onto the car's Pico W and `code/transmitter/` onto the
   handheld Pico W (Thonny works well). Each folder's `main.py` runs on boot.
3. Power both boards. The transmitter's LED blinks slowly while scanning and goes solid once it
   links to the car.

Detailed flashing, testing and troubleshooting steps are in the receiver and transmitter READMEs.

## Running the tests

The control logic (packet validation, throttle/steering ramping, failsafe timing, joystick scaling)
is tested on a desktop Python install:

```
cd code/receiver_tests
python -m unittest discover -v
```

```
cd code/transmitter_tests
python -m unittest discover -v
```

These do not cover the real BLE radio or physical motor/servo response; those need real hardware.
