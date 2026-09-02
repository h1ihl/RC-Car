"""
joystick.py -- reads the throttle/steering potentiometers and turns raw
ADC counts into calibrated -1.0..1.0 values.

Deadzone and output mapping are deliberately NOT done here -- that's
the receiver's job (throttle.py/steering.py), same one-source-of-truth
split as receiver/motor.py moving its duty ceiling out to throttle.py.
This module's only job is "turn a raw ADC reading into an honest -1..1
float," the same narrow scope as receiver/battery.py just being a
volts() function.
"""

from machine import Pin, ADC

import config


def _scale(raw, center, invert=False):
    """raw/center: 0..65535 ADC counts. Scales independently above and
    below centre since the two halves of a cheap joystick's travel
    aren't guaranteed symmetric. Pure function, no ADC touched, so it's
    testable without hardware."""
    if raw >= center:
        span = 65535 - center
        x = 0.0 if span <= 0 else (raw - center) / span
    else:
        span = center
        x = 0.0 if span <= 0 else (raw - center) / span

    x = max(-1.0, min(1.0, x))
    return -x if invert else x


class JoystickAxis:
    """One potentiometer. Calibrates its own rest position at boot
    instead of assuming mid-scale (32767), since cheap joysticks rarely
    sit there exactly."""

    def __init__(self, adc_gp, invert=False):
        self.adc = ADC(Pin(adc_gp))
        self.invert = invert
        self.center = 32768

    def calibrate(self, samples=None):
        """Call once at boot with the stick released -- measures rest
        position so 'centred' means whatever this stick actually reads
        at rest, not a theoretical midpoint."""
        samples = samples or config.JOYSTICK_CALIBRATION_SAMPLES
        total = 0
        for _ in range(samples):
            total += self.adc.read_u16()
        self.center = total // samples

    def read(self):
        """Returns -1.0 (one extreme) .. 0 .. +1.0 (other extreme)."""
        return _scale(self.adc.read_u16(), self.center, self.invert)
