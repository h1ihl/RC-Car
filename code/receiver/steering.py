"""
steering.py -- turns a joystick value into a servo pulse width, smoothly.

Deadzone -> +/-STEER_LIMIT_DEG off centre (NOT the servo's full sweep) ->
ramp toward that target -> drive the servo.
"""

import config


def _apply_deadzone(x, deadzone):
    """Same shape as throttle.py's, including the input clamp -- see
    there for why an out-of-range stick value must not survive this."""
    x = max(-1.0, min(1.0, x))
    if abs(x) <= deadzone:
        return 0.0
    sign = 1.0 if x > 0 else -1.0
    return sign * (abs(x) - deadzone) / (1.0 - deadzone)


class SteeringController:
    def __init__(self, servo):
        self.servo = servo
        # degrees off centre, not raw microseconds, so the ramp rate
        # (deg/s) means the same thing no matter what the calibrated
        # pulse-width span happens to be
        self.target_deg = 0.0
        self.current_deg = 0.0

    def set_from_joystick(self, raw):
        """raw: -1.0 (full left) .. 0 .. +1.0 (full right)."""
        x = _apply_deadzone(raw, config.STEERING_DEADZONE)
        self.target_deg = x * config.STEER_LIMIT_DEG

    def force_center(self):
        """Used by the failsafe."""
        self.target_deg = 0.0

    def _deg_to_us(self, deg):
        """Degrees off centre -> pulse width, in the same angle frame as
        the bench script (see config.SERVO_US_PER_DEG).

        Clamped to the +/-STEER_LIMIT_DEG window, not just to the servo's
        hard mechanical stops. Servo.write_us() also clamps, but that
        backstop sits at the 500-2500us stops -- way past where this
        linkage can actually go. This is the clamp that keeps the wheels
        inside 45 degrees each way even if the ramp, the config, or a
        future caller gets something wrong.
        """
        us = config.SERVO_CENTER_US + deg * config.SERVO_US_PER_DEG
        return max(config.SERVO_STEER_MIN_US, min(config.SERVO_STEER_MAX_US, us))

    def tick(self, dt_s):
        max_step = config.STEERING_RAMP_DEG_PER_S * dt_s
        diff = self.target_deg - self.current_deg
        if abs(diff) <= max_step:
            self.current_deg = self.target_deg
        else:
            self.current_deg += max_step if diff > 0 else -max_step

        self.servo.write_us(self._deg_to_us(self.current_deg))

    def stop_immediately(self):
        """No ramp -- snaps back to centre. For shutdown, not normal use."""
        self.target_deg = 0.0
        self.current_deg = 0.0
        self.servo.write_us(self._deg_to_us(0.0))
