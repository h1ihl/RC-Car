"""
servo.py -- steering servo, driven by raw pulse width on a 50Hz PWM
channel.

Starts detached -- no pulses go out until something explicitly commands
a position, so nothing jumps the second this loads. Angle-based helpers
(write_angle/sweep) from the bench script got dropped here on purpose:
the receiver's steering is always +/-STEER_LIMIT_DEG off a calibrated
centre, never a raw 0-180 sweep, so that mapping lives in steering.py
instead.
"""

from machine import Pin, PWM

import config


class Servo:
    # absolute guard rails -- these are the *measured* mechanical
    # endpoints (see HARDWARE.md / the logbook), not a guess. Never
    # exceeded, no matter what gets passed in.
    HARD_MIN_US = config.SERVO_HARD_MIN_US
    HARD_MAX_US = config.SERVO_HARD_MAX_US

    def __init__(self, gp):
        self.pwm = PWM(Pin(gp))
        self.pwm.freq(config.SERVO_HZ)
        self.period_us = 1_000_000 // config.SERVO_HZ
        self.us = None
        self.pwm.duty_u16(0)

    def write_us(self, us):
        """Sets a raw pulse width, returns what actually got applied."""
        us = max(self.HARD_MIN_US, min(self.HARD_MAX_US, int(us)))
        self.pwm.duty_u16(int(us * 65535 // self.period_us))
        self.us = us
        return us

    def detach(self):
        """Servo goes limp, stops buzzing/holding position."""
        self.pwm.duty_u16(0)
        self.us = None

    def deinit(self):
        self.detach()
        self.pwm.deinit()
