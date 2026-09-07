"""
throttle.py -- turns a joystick value into motor duty, smoothly.

Deadzone -> map onto [MOTOR_MIN_DUTY, MOTOR_MAX_DUTY] -> ramp toward that
target over time instead of jumping straight to it. Both motors get the
same duty -- this is RWD with a fixed differential pair, not skid
steering, so there's no reason for the two sides to ever disagree.
"""

import config


def _apply_deadzone(x, deadzone):
    """Below the deadzone, treat it as dead centre. Above it, rescale so
    the remaining travel still covers the full -1..1 range -- otherwise
    there'd be a dead patch right past the deadzone edge too.

    Clamps its input first. protocol.decode() already rejects anything
    outside +/-1.0, so this can't fire on real traffic -- but if it ever
    did, an out-of-range stick would ramp current_duty up past 1.0, and
    since the motors clamp at 1.0 the car would keep going flat out for
    however long the ramp took to come back down through the range that
    does nothing. Cheap to make impossible.
    """
    x = max(-1.0, min(1.0, x))
    if abs(x) <= deadzone:
        return 0.0
    sign = 1.0 if x > 0 else -1.0
    return sign * (abs(x) - deadzone) / (1.0 - deadzone)


def _map_to_duty(x):
    """x is -1..1, post-deadzone. Maps onto +/-[MOTOR_MIN_DUTY, MAX_DUTY]
    so the joystick's usable range lines up with duty that actually
    spins the motors (measured deadband, see the logbook), instead of
    wasting the first chunk of stick travel on a duty too low to move
    anything."""
    if x == 0.0:
        return 0.0
    sign = 1.0 if x > 0 else -1.0
    span = config.MOTOR_MAX_DUTY - config.MOTOR_MIN_DUTY
    return sign * (config.MOTOR_MIN_DUTY + span * abs(x))


class ThrottleController:
    def __init__(self, motor_a, motor_b):
        self.motor_a = motor_a
        self.motor_b = motor_b
        self.target_duty = 0.0
        self.current_duty = 0.0

    def set_from_joystick(self, raw):
        """raw: -1.0 (full reverse) .. 0 .. +1.0 (full forward)."""
        x = _apply_deadzone(raw, config.THROTTLE_DEADZONE)
        self.target_duty = _map_to_duty(x)

    def force_stop(self):
        """Used by the failsafe -- bypasses the joystick entirely and
        sets the target to zero, so the normal ramp brings it down
        smoothly instead of slamming to a stop."""
        self.target_duty = 0.0

    def tick(self, dt_s):
        """Move current_duty toward target_duty at the configured rate,
        then actually drive the motors. Call this every loop iteration
        with however much time actually passed -- dt_s, not a fixed
        assumption -- so the ramp rate holds even if the loop jitters."""
        speeding_up = abs(self.target_duty) > abs(self.current_duty)
        rate = config.THROTTLE_ACCEL_PER_S if speeding_up else config.THROTTLE_DECEL_PER_S
        max_step = rate * dt_s

        diff = self.target_duty - self.current_duty
        if abs(diff) <= max_step:
            self.current_duty = self.target_duty
        else:
            self.current_duty += max_step if diff > 0 else -max_step

        self.motor_a.drive(self.current_duty)
        self.motor_b.drive(self.current_duty)

    def stop_immediately(self):
        """Hard stop, no ramp -- for shutdown, not normal operation."""
        self.target_duty = 0.0
        self.current_duty = 0.0
        self.motor_a.stop()
        self.motor_b.stop()
