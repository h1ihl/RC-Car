"""
config.py -- every tunable number for the transmitter lives here, same
split as the receiver's config.py: touch this file for tuning, not the
code around it.

The BLE UUIDs and packet format below are copy-pasted from
receiver/config.py and receiver/protocol.py rather than imported -- this
runs on a second, physically separate Pico with its own flash, so
there's no shared filesystem to import across (same reasoning as
test_transmitter/ble_test_tx.py's docstring). ../transmitter_tests/
test_receiver_compat.py checks these against the receiver's real config
so the two copies can't silently drift apart.
"""

# ---------------------------------------------------------------------
# pins -- picked fresh for this board, NOT yet wired or confirmed on
# real hardware (no bench logbook entry for the transmitter box yet,
# unlike the receiver's HARDWARE.md). Update once it's actually built.
# ---------------------------------------------------------------------
PIN_THROTTLE_ADC = 26   # ADC0 -- joystick Y axis (forward/back)
PIN_STEERING_ADC = 27   # ADC1 -- joystick X axis (left/right)

# flip either of these if a physical joystick ends up wired mirrored
THROTTLE_INVERT = False
STEERING_INVERT = False

# ---------------------------------------------------------------------
# joystick calibration
# ---------------------------------------------------------------------

# cheap analog joysticks rarely sit exactly at mid-scale (32767) at
# rest, and the two halves of travel aren't guaranteed symmetric either
# -- so centre gets measured at boot (see joystick.py) instead of
# hardcoded. This just controls how many samples that boot measurement
# averages over.
JOYSTICK_CALIBRATION_SAMPLES = 64

# ---------------------------------------------------------------------
# wireless / protocol -- MUST match receiver/config.py and
# receiver/protocol.py exactly
# ---------------------------------------------------------------------
BLE_SERVICE_UUID = "c6a2f001-6b7e-4a1a-9f2e-3d4b5c6a7b8c"
BLE_CONTROL_CHAR_UUID = "c6a2f002-6b7e-4a1a-9f2e-3d4b5c6a7b8c"

SEND_INTERVAL_MS = 20    # ~50Hz, matches receiver's EXPECTED_PACKET_INTERVAL_MS
SCAN_TIMEOUT_MS = 8000   # how long one scan attempt runs before it's retried

# ---------------------------------------------------------------------
# main loop
# ---------------------------------------------------------------------
LOOP_INTERVAL_MS = 20    # ~50Hz send loop, matches SEND_INTERVAL_MS

# LED blink period while not yet linked to the receiver -- same period
# as the receiver's own "not connected" blink, so both boards speak the
# same visual language
LED_BLINK_MS = 1000
