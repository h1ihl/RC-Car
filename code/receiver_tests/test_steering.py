import unittest

import _mocks  # noqa: F401
import config
from steering import SteeringController


class _FakeServo:
    def __init__(self):
        self.us = None

    def write_us(self, us):
        # mirrors the real Servo's hard clamp
        self.us = max(config.SERVO_HARD_MIN_US, min(config.SERVO_HARD_MAX_US, int(us)))
        return self.us


class SteeringTests(unittest.TestCase):
    def setUp(self):
        self.servo = _FakeServo()
        self.s = SteeringController(self.servo)

    def test_center_holds_center_us(self):
        self.s.set_from_joystick(0.0)
        self.s.tick(10.0)
        self.assertEqual(self.servo.us, config.SERVO_CENTER_US)

    def test_within_deadzone_is_zero(self):
        self.s.set_from_joystick(config.STEERING_DEADZONE * 0.5)
        self.s.tick(10.0)
        self.assertEqual(self.s.current_deg, 0.0)

    def test_full_right_reaches_limit_not_more(self):
        self.s.set_from_joystick(1.0)
        self.s.tick(10.0)  # fully ramped
        self.assertAlmostEqual(self.s.current_deg, config.STEER_LIMIT_DEG, places=3)

    def test_full_left_reaches_limit_not_more(self):
        self.s.set_from_joystick(-1.0)
        self.s.tick(10.0)
        self.assertAlmostEqual(self.s.current_deg, -config.STEER_LIMIT_DEG, places=3)

    def test_never_exceeds_limit_even_mid_ramp(self):
        self.s.set_from_joystick(1.0)
        for _ in range(50):
            self.s.tick(0.005)
            self.assertLessEqual(abs(self.s.current_deg), config.STEER_LIMIT_DEG + 1e-9)

    def test_pulse_width_stays_inside_the_45_degree_window(self):
        self.s.set_from_joystick(1.0)
        self.s.tick(10.0)
        self.assertLessEqual(self.servo.us, config.SERVO_STEER_MAX_US)
        self.assertGreaterEqual(self.servo.us, config.SERVO_STEER_MIN_US)

        self.s.set_from_joystick(-1.0)
        self.s.tick(10.0)
        self.assertLessEqual(self.servo.us, config.SERVO_STEER_MAX_US)
        self.assertGreaterEqual(self.servo.us, config.SERVO_STEER_MIN_US)

    def test_full_lock_lands_on_the_bench_scripts_45_and_135_degrees(self):
        """The steering endpoints have to be the same two pulse widths
        the bench script's 's 45' and 's 135' produce -- 1250us and
        1750us. That's the whole point of sharing an angle frame with it:
        an endpoint found by hand on the bench means the same thing to
        the receiver, with nothing to convert in between."""
        self.s.set_from_joystick(-1.0)
        self.s.tick(10.0)
        self.assertEqual(self.servo.us, 1250)

        self.s.set_from_joystick(1.0)
        self.s.tick(10.0)
        self.assertEqual(self.servo.us, 1750)

    def test_never_commands_past_the_window_even_with_absurd_input(self):
        """The joystick should never hand us anything outside -1..1, but
        if a decode bug or a future caller ever did, the steering clamp
        -- not the servo's 500-2500us mechanical backstop -- is what has
        to catch it. The mechanical stops are nowhere near 45 degrees."""
        for absurd in (5.0, -5.0, 1000.0, -1000.0):
            self.s.set_from_joystick(absurd)
            self.s.tick(10.0)
            self.assertLessEqual(self.servo.us, config.SERVO_STEER_MAX_US)
            self.assertGreaterEqual(self.servo.us, config.SERVO_STEER_MIN_US)

    def test_ramps_not_instant(self):
        self.s.set_from_joystick(1.0)
        self.s.tick(0.01)
        self.assertGreater(self.s.current_deg, 0.0)
        self.assertLess(self.s.current_deg, config.STEER_LIMIT_DEG)

    def test_force_center_ramps_back(self):
        self.s.set_from_joystick(1.0)
        self.s.tick(10.0)
        self.assertGreater(self.s.current_deg, 0.0)

        self.s.force_center()
        self.s.tick(10.0)
        self.assertEqual(self.s.current_deg, 0.0)
        self.assertEqual(self.servo.us, config.SERVO_CENTER_US)


if __name__ == "__main__":
    unittest.main()
