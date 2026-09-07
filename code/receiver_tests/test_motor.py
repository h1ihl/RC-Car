"""
Motor driver tests, with one specific bug in mind.

The two TT motors are mounted mirrored on the chassis, so driving the
car forward means running the two H-bridge channels in OPPOSITE
electrical directions -- on the bench it was the old script's 'sp'
(counter-rotate) command that moved the car forward, not 'f'.

throttle.py deliberately doesn't know that: it hands both motors the
same signed duty, because "which way is forward for this motor" is a
wiring fact, not a control-logic one. config.M2_INVERT is what turns
one into the other, so these tests check the direction pins directly --
that's the only place the mirroring is actually observable.
"""

import time
import unittest

import _mocks  # noqa: F401
import config
from motor import Motor
from throttle import ThrottleController

_FORWARD = 0   # M pin low  = forward, per the DRI0002's truth table
_REVERSE = 1   # M pin high = reverse


class MotorDirectionTests(unittest.TestCase):
    def test_invert_flips_direction_but_not_speed(self):
        plain = Motor(config.PIN_M1_E, config.PIN_M1_M, "plain", invert=False)
        flipped = Motor(config.PIN_M2_E, config.PIN_M2_M, "flipped", invert=True)

        plain.drive(0.6)
        flipped.drive(0.6)

        self.assertEqual(plain.dir.value(), _FORWARD)
        self.assertEqual(flipped.dir.value(), _REVERSE)
        # same commanded duty means the same PWM either way -- inverting
        # is about direction only, never magnitude
        self.assertEqual(plain.en.duty_u16(), flipped.en.duty_u16())

    def test_duty_clamps_to_the_physical_range(self):
        m = Motor(config.PIN_M1_E, config.PIN_M1_M, "M1")
        m.drive(5.0)
        self.assertEqual(m.duty, 1.0)
        self.assertEqual(m.en.duty_u16(), 65535)

        m.drive(-5.0)
        self.assertEqual(m.duty, -1.0)
        self.assertEqual(m.en.duty_u16(), 65535)   # magnitude, not sign

    def test_stop_kills_the_enable(self):
        m = Motor(config.PIN_M1_E, config.PIN_M1_M, "M1")
        m.drive(0.8)
        m.stop()
        self.assertEqual(m.en.duty_u16(), 0)
        self.assertEqual(m.duty, 0.0)


class MirroredMountingTests(unittest.TestCase):
    """The actual "forward means opposite" behaviour, driven the way
    main.py drives it: through ThrottleController, with the real config
    invert flags."""

    def setUp(self):
        self.m1 = Motor(config.PIN_M1_E, config.PIN_M1_M, "M1", config.M1_INVERT)
        self.m2 = Motor(config.PIN_M2_E, config.PIN_M2_M, "M2", config.M2_INVERT)
        self.throttle = ThrottleController(self.m1, self.m2)

    def _drive(self, stick):
        self.throttle.set_from_joystick(stick)
        self.throttle.tick(10.0)   # let the ramp finish

    def test_forward_stick_runs_the_two_channels_opposite_ways(self):
        self._drive(1.0)
        self.assertGreater(self.throttle.current_duty, 0.0)
        self.assertNotEqual(self.m1.dir.value(), self.m2.dir.value())

    def test_reverse_stick_runs_them_opposite_ways_too(self):
        self._drive(-1.0)
        self.assertLess(self.throttle.current_duty, 0.0)
        self.assertNotEqual(self.m1.dir.value(), self.m2.dir.value())

    def test_reverse_is_the_mirror_image_of_forward(self):
        self._drive(1.0)
        forward = (self.m1.dir.value(), self.m2.dir.value())
        self._drive(-1.0)
        reverse = (self.m1.dir.value(), self.m2.dir.value())
        self.assertEqual(reverse, (1 - forward[0], 1 - forward[1]))

    def test_both_channels_always_get_the_same_speed(self):
        for stick in (0.3, 0.7, 1.0, -0.5, -1.0):
            self._drive(stick)
            self.assertEqual(self.m1.en.duty_u16(), self.m2.en.duty_u16())


class ReverseCoastTests(unittest.TestCase):
    """The coast before a direction flip is a real mechanical delay, but
    it blocks the whole control loop -- failsafe included -- so it must
    only happen when there's actually a spinning motor to protect."""

    def setUp(self):
        self.slept = []
        self._real_sleep_ms = time.sleep_ms
        time.sleep_ms = self.slept.append
        self.m = Motor(config.PIN_M1_E, config.PIN_M1_M, "M1")

    def tearDown(self):
        time.sleep_ms = self._real_sleep_ms

    def test_reversing_a_spinning_motor_coasts_first(self):
        self.m.drive(0.9)
        self.slept.clear()
        self.m.drive(-0.9)
        self.assertEqual(self.slept, [config.REVERSE_COAST_MS])

    def test_reversing_a_barely_moving_motor_does_not_block(self):
        # this is the case the throttle ramp actually produces: duty
        # walks down through zero before it goes negative, so the
        # direction flip lands on a motor that has already stopped
        self.m.drive(config.REVERSE_COAST_MIN_DUTY / 2)
        self.slept.clear()
        self.m.drive(-config.REVERSE_COAST_MIN_DUTY / 2)
        self.assertEqual(self.slept, [])

    def test_a_full_ramp_through_zero_never_blocks(self):
        throttle = ThrottleController(
            Motor(config.PIN_M1_E, config.PIN_M1_M, "M1", config.M1_INVERT),
            Motor(config.PIN_M2_E, config.PIN_M2_M, "M2", config.M2_INVERT),
        )
        throttle.set_from_joystick(1.0)
        throttle.tick(10.0)

        self.slept.clear()
        throttle.set_from_joystick(-1.0)
        for _ in range(200):          # 20ms ticks, the real loop rate
            throttle.tick(0.02)
        self.assertLess(throttle.current_duty, 0.0)   # actually got to reverse
        self.assertEqual(self.slept, [])              # without ever blocking

    def test_same_direction_never_coasts(self):
        self.m.drive(0.9)
        self.slept.clear()
        self.m.drive(0.2)
        self.assertEqual(self.slept, [])


if __name__ == "__main__":
    unittest.main()
