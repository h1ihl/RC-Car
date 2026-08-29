"""
config.py -- every tunable number for the receiver lives here.

If you're trying to make the car feel different (snappier throttle, less
steering deadzone, whatever), this is the file to touch. Nothing outside
this file should need editing for normal tuning.
"""

# ---------------------------------------------------------------------
# pins -- matches the validated wiring from rc_bringup.py / the wiring
# pin map doc. Don't change these without updating the physical wiring.
# ---------------------------------------------------------------------
PIN_M1_E = 16
PIN_M1_M = 17
PIN_M2_E = 18
PIN_M2_M = 19
PIN_SERVO = 15
BATT_ADC_GP = 26

MOTOR_PWM_HZ = 1000

# motors mount mirrored on the chassis -- flip these if 'forward' comes
# out backwards once it's on wheels
M1_INVERT = False
M2_INVERT = False

# don't slam a spinning motor straight into reverse -- kill the enable,
# coast, then flip direction. Same value as the bench script.
REVERSE_COAST_MS = 60

# ---------------------------------------------------------------------
# throttle
# ---------------------------------------------------------------------

# small joystick movements near centre shouldn't do anything -- the
# stick's a little noisy at rest and nobody wants the car creeping
THROTTLE_DEADZONE = 0.08

# measured on the bench at 7.2V NiMH (see the logbook): duty below this
# just doesn't turn the wheels. No point letting the joystick command a
# duty that produces nothing, so the deadzone edge maps straight to
# this instead of to zero.
MOTOR_MIN_DUTY = 0.35
MOTOR_MAX_DUTY = 1.0  # no ceiling needed on the 7.2V NiMH pack

# how fast duty is allowed to change, in duty-per-second. These are a
# starting point -- tune by feel once it's actually on wheels.
THROTTLE_ACCEL_PER_S = 1.6   # 0 -> full in ~0.6s
THROTTLE_DECEL_PER_S = 2.2   # comes down a bit quicker than it goes up

# ---------------------------------------------------------------------
# steering
# ---------------------------------------------------------------------

STEERING_DEADZONE = 0.05

SERVO_HZ = 50

# true mechanical endpoints, measured by a slow sweep rather than
# commanding them directly (that's what killed the first servo). Never
# command past these -- see servo.py's HARD_MIN/MAX.
SERVO_HARD_MIN_US = 500
SERVO_HARD_MAX_US = 2500

# working range with margin off the mechanical stops -- this is what
# +/-90 degrees of raw servo travel maps onto. Matches the logbook's
# validated numbers.
SERVO_MIN_US = 550
SERVO_MAX_US = 2450

# TODO: placeholder -- this is just the pulse-width midpoint. The real
# MG90S hasn't gone on the steering linkage yet. Once it's mounted, find
# where the wheels actually point straight (bench script's 'us' command)
# and update this.
SERVO_CENTER_US = 1500

# commanded steering range -- +/- this many degrees off centre, NOT the
# servo's full mechanical sweep. Full stick = 45 degrees, not "whatever
# the servo can physically do."
STEER_LIMIT_DEG = 45.0

# degrees/second the servo is allowed to move -- steering can ramp
# faster than throttle, there's no momentum to fight against
STEERING_RAMP_DEG_PER_S = 220.0

# ---------------------------------------------------------------------
# battery sense
# ---------------------------------------------------------------------
BATT_DIV_RATIO = 4.03   # (100k + 33k) / 33k
BATT_ADC_VREF = 3.30

# ---------------------------------------------------------------------
# wireless / protocol
# ---------------------------------------------------------------------

# custom 128-bit UUIDs, randomly generated for this project -- just need
# to match between the receiver and whatever's transmitting to it
BLE_SERVICE_UUID = "c6a2f001-6b7e-4a1a-9f2e-3d4b5c6a7b8c"
BLE_CONTROL_CHAR_UUID = "c6a2f002-6b7e-4a1a-9f2e-3d4b5c6a7b8c"

BLE_DEVICE_NAME = "RCCarReceiver"

# how often we expect a packet to actually show up -- used to size the
# failsafe timeout below, and by the test transmitter's send rate
EXPECTED_PACKET_INTERVAL_MS = 20  # ~50Hz

# ---------------------------------------------------------------------
# failsafe
# ---------------------------------------------------------------------

# how long we'll go without a valid packet before killing the motors.
# ~20x the expected packet interval -- tolerates a real burst of dropped
# packets without being trigger-happy, but still trips well under half
# a second. Tune this once there's a feel for real-world drop rate.
FAILSAFE_TIMEOUT_MS = 400

# ---------------------------------------------------------------------
# main loop
# ---------------------------------------------------------------------
LOOP_INTERVAL_MS = 20   # ~50Hz control loop

# how often diagnostics prints to the REPL -- doesn't need to be fast
DIAG_INTERVAL_MS = 1000
