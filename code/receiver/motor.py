"""
motor.py -- one channel of the DFRobot DRI0002 (the "MD1.3" dual
H-bridge).

    E LOW          -> stopped (M doesn't matter)
    E HIGH, M LOW  -> forward
    E HIGH, M HIGH -> reverse
    E PWM          -> speed control

Lifted straight from the bench bring-up script -- this part's already
validated on the bench, no reason to rewrite it. The one real change:
the old script baked its MAX_DUTY ceiling in here, but that's really a
throttle-curve decision, not a hardware one, so it's moved up into
throttle.py and this class just clamps to the physical +/-1.0 range as
a hardware-level backstop.
"""

from machine import Pin, PWM
import time

import config


class Motor:
    def __init__(self, en_gp, dir_gp, name, invert=False):
        self.name = name
        self.invert = invert
        self.en = PWM(Pin(en_gp))
        self.en.freq(config.MOTOR_PWM_HZ)
        self.en.duty_u16(0)
        self.dir = Pin(dir_gp, Pin.OUT, value=0)
        self.duty = 0.0

    def drive(self, duty):
        """duty: -1.0 (full reverse) .. 0 .. +1.0 (full forward)."""
        duty = max(-1.0, min(1.0, duty))
        cmd = -duty if self.invert else duty
        want_dir = 0 if cmd >= 0 else 1

        # don't slam a spinning motor straight into reverse - kill the
        # enable, coast for a bit, then flip direction
        if want_dir != self.dir.value() and self.duty != 0.0:
            self.en.duty_u16(0)
            time.sleep_ms(config.REVERSE_COAST_MS)

        self.dir.value(want_dir)
        self.en.duty_u16(int(abs(cmd) * 65535))
        self.duty = duty

    def stop(self):
        self.en.duty_u16(0)
        self.duty = 0.0

    def deinit(self):
        self.stop()
        self.en.deinit()
