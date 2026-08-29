import unittest

import _mocks  # noqa: F401 -- sets up sys.path + fakes before importing receiver code
import config
from throttle import ThrottleController


class _FakeMotor:
    def __init__(self):
        self.duty = None

    def drive(self, duty):
        self.duty = duty

    def stop(self):
        self.duty = 0.0


class ThrottleTests(unittest.TestCase):
    def setUp(self):
        self.m1 = _FakeMotor()
        self.m2 = _FakeMotor()
        self.t = ThrottleController(self.m1, self.m2)

    def test_center_is_zero(self):
        self.t.set_from_joystick(0.0)
        self.t.tick(1.0)
        self.assertEqual(self.t.current_duty, 0.0)

    def test_within_deadzone_is_zero(self):
        self.t.set_from_joystick(config.THROTTLE_DEADZONE * 0.5)
        self.t.tick(1.0)
        self.assertEqual(self.t.current_duty, 0.0)

    def test_full_forward_ramps_not_instant(self):
        self.t.set_from_joystick(1.0)
        self.t.tick(0.01)  # one tiny step
        self.assertGreater(self.t.current_duty, 0.0)
        self.assertLess(self.t.current_duty, config.MOTOR_MAX_DUTY)

        seconds_needed = config.MOTOR_MAX_DUTY / config.THROTTLE_ACCEL_PER_S
        self.t.tick(seconds_needed + 1.0)  # let it fully ramp
        self.assertAlmostEqual(self.t.current_duty, config.MOTOR_MAX_DUTY, places=3)

    def test_small_stick_input_maps_above_deadband_floor(self):
        # just past the deadzone -- should map close to MOTOR_MIN_DUTY,
        # not to some tiny duty that won't actually turn the motor
        just_past = config.THROTTLE_DEADZONE + 0.01
        self.t.set_from_joystick(just_past)
        self.t.tick(10.0)  # let it fully ramp
        self.assertGreaterEqual(self.t.current_duty, config.MOTOR_MIN_DUTY - 0.02)
        self.assertLess(self.t.current_duty, config.MOTOR_MIN_DUTY + 0.05)

    def test_reverse_is_negative_and_bounded(self):
        self.t.set_from_joystick(-1.0)
        self.t.tick(10.0)
        self.assertAlmostEqual(self.t.current_duty, -config.MOTOR_MAX_DUTY, places=3)

    def test_both_motors_get_same_duty(self):
        self.t.set_from_joystick(0.6)
        self.t.tick(10.0)
        self.assertEqual(self.m1.duty, self.m2.duty)
        self.assertEqual(self.m1.duty, self.t.current_duty)

    def test_force_stop_ramps_down_not_instant(self):
        self.t.set_from_joystick(1.0)
        self.t.tick(10.0)
        self.assertGreater(self.t.current_duty, 0.0)

        self.t.force_stop()
        self.t.tick(0.01)
        self.assertGreater(self.t.current_duty, 0.0)  # started coming down, not there yet
        self.t.tick(10.0)
        self.assertEqual(self.t.current_duty, 0.0)

    def test_stop_immediately_is_instant(self):
        self.t.set_from_joystick(1.0)
        self.t.tick(10.0)
        self.t.stop_immediately()
        self.assertEqual(self.t.current_duty, 0.0)
        self.assertEqual(self.m1.duty, 0.0)
        self.assertEqual(self.m2.duty, 0.0)


if __name__ == "__main__":
    unittest.main()
