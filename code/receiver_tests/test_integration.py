"""
Exercises the same wiring main.py does -- BLE packet in, through
failsafe, to throttle/steering -- without calling main() itself (that's
an infinite loop, not written to be called from a test). This is the
closest thing to an end-to-end check available without real hardware:
covers "valid packets work," "stale packets trigger failsafe,"
"reconnecting resumes control safely," and "boot defaults to safe."

A recurring theme below: sending ONE packet only buys ~FAILSAFE_TIMEOUT_MS
of grace, not indefinite connection -- that's correct receiver behaviour,
not a bug, so tests that want to represent "connected and driving" send
a packet on every tick, like a real ~50Hz stream would.
"""

import unittest

import _mocks  # noqa: F401
import time
import config
from motor import Motor
from servo import Servo
from throttle import ThrottleController
from steering import SteeringController
from failsafe import Failsafe
from protocol import encode, decode


class ReceiverLoopTests(unittest.TestCase):
    def setUp(self):
        self.m1 = Motor(config.PIN_M1_E, config.PIN_M1_M, "M1")
        self.m2 = Motor(config.PIN_M2_E, config.PIN_M2_M, "M2")
        self.srv = Servo(config.PIN_SERVO)
        self.throttle = ThrottleController(self.m1, self.m2)
        self.steering = SteeringController(self.srv)
        self.failsafe = Failsafe()

    def _tick(self, now_ms, dt_s, raw_packet=None, disconnect=False):
        """One pass through the same logic main.py's loop body runs."""
        if disconnect:
            self.failsafe.note_disconnect()

        if raw_packet is not None:
            decoded = decode(raw_packet)
            if decoded is not None:
                t, s, _seq = decoded
                self.failsafe.note_valid_packet(now_ms)
                self.throttle.set_from_joystick(t)
                self.steering.set_from_joystick(s)

        if self.failsafe.update(now_ms):
            self.throttle.force_stop()
            self.steering.force_center()

        self.throttle.tick(dt_s)
        self.steering.tick(dt_s)

    def test_boots_safe_with_no_packets_ever(self):
        now = time.ticks_ms()
        self._tick(now, 0.02)
        self.assertEqual(self.throttle.current_duty, 0.0)
        self.assertEqual(self.srv.us, config.SERVO_CENTER_US)

    def test_valid_packet_stream_drives_motors_and_steering(self):
        now = time.ticks_ms()
        packet = encode(throttle=0.8, steering=0.5, seq=1)
        for _ in range(80):  # ~1.6s of a continuous ~50Hz stream
            now = time.ticks_add(now, 20)
            self._tick(now, 0.02, raw_packet=packet)
        self.assertGreater(self.throttle.current_duty, 0.5)
        self.assertGreater(self.steering.current_deg, 0.0)
        self.assertFalse(self.failsafe.active)

    def test_stale_packets_trigger_failsafe_and_stop_the_car(self):
        now = time.ticks_ms()
        packet = encode(throttle=1.0, steering=0.0, seq=1)
        self._tick(now, 0.02, raw_packet=packet)
        for _ in range(20):
            now = time.ticks_add(now, 20)
            self._tick(now, 0.02)
        self.assertGreater(self.throttle.current_duty, 0.0)  # still moving, ramping

        # let enough time pass with no new packets to trip the timeout
        now = time.ticks_add(now, config.FAILSAFE_TIMEOUT_MS + 100)
        for _ in range(100):  # let the decel ramp actually reach zero
            now = time.ticks_add(now, 20)
            self._tick(now, 0.02)
        self.assertTrue(self.failsafe.active)
        self.assertEqual(self.throttle.current_duty, 0.0)
        self.assertEqual(self.steering.current_deg, 0.0)

    def test_single_corrupt_packet_amid_a_good_stream_is_ignored(self):
        now = time.ticks_ms()
        good = encode(throttle=1.0, steering=0.0, seq=1)
        corrupt = bytearray(good)
        corrupt[-1] ^= 0xFF
        corrupt = bytes(corrupt)

        for i in range(30):  # continuous good stream, let it ramp up
            now = time.ticks_add(now, 20)
            self._tick(now, 0.02, raw_packet=good)
        moving_duty = self.throttle.current_duty
        target_before = self.throttle.target_duty
        self.assertGreater(moving_duty, 0.0)

        # one corrupt packet arrives mid-stream -- should just be
        # dropped: doesn't reset the failsafe timer, doesn't touch the
        # commanded target (current_duty is still mid-ramp toward that
        # same target either way, so it correctly keeps climbing -- the
        # thing that must NOT change is the target), and normal packets
        # right after still work
        now = time.ticks_add(now, 20)
        self._tick(now, 0.02, raw_packet=corrupt)
        self.assertFalse(self.failsafe.active)
        self.assertEqual(self.throttle.target_duty, target_before)
        self.assertGreaterEqual(self.throttle.current_duty, moving_duty)  # kept climbing, didn't reset

        now = time.ticks_add(now, 20)
        self._tick(now, 0.02, raw_packet=good)
        self.assertFalse(self.failsafe.active)

    def test_disconnect_stops_immediately_even_within_timeout_window(self):
        now = time.ticks_ms()
        packet = encode(throttle=1.0, steering=1.0, seq=1)
        for _ in range(50):  # continuous stream, well connected
            now = time.ticks_add(now, 20)
            self._tick(now, 0.02, raw_packet=packet)
        self.assertGreater(self.throttle.current_duty, 0.0)
        self.assertFalse(self.failsafe.active)

        # disconnect fires well inside FAILSAFE_TIMEOUT_MS of the last
        # good packet -- should still trip immediately, not wait it out
        now = time.ticks_add(now, 20)
        self._tick(now, 0.02, disconnect=True)
        self.assertTrue(self.failsafe.active)

    def test_reconnect_with_valid_packet_resumes_control(self):
        now = time.ticks_ms()
        self._tick(now, 0.02, disconnect=True)
        self.assertTrue(self.failsafe.active)

        now = time.ticks_add(now, 20)
        packet = encode(throttle=0.6, steering=0.0, seq=2)
        # a fresh continuous stream after reconnecting
        for _ in range(30):
            now = time.ticks_add(now, 20)
            self._tick(now, 0.02, raw_packet=packet)
        self.assertFalse(self.failsafe.active)
        self.assertGreater(self.throttle.current_duty, 0.0)


if __name__ == "__main__":
    unittest.main()
