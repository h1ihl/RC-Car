import unittest

import _mocks  # noqa: F401
import time
import config
from failsafe import Failsafe


class FailsafeTests(unittest.TestCase):
    def test_active_at_boot(self):
        f = Failsafe()
        self.assertTrue(f.active)

    def test_clears_on_valid_packet(self):
        f = Failsafe()
        f.note_valid_packet(time.ticks_ms())
        self.assertFalse(f.active)

    def test_stays_clear_before_timeout(self):
        f = Failsafe()
        now = time.ticks_ms()
        f.note_valid_packet(now)
        later = time.ticks_add(now, config.FAILSAFE_TIMEOUT_MS - 10)
        self.assertFalse(f.update(later))

    def test_trips_after_timeout(self):
        f = Failsafe()
        now = time.ticks_ms()
        f.note_valid_packet(now)
        later = time.ticks_add(now, config.FAILSAFE_TIMEOUT_MS + 10)
        self.assertTrue(f.update(later))

    def test_disconnect_trips_immediately_even_within_timeout(self):
        f = Failsafe()
        now = time.ticks_ms()
        f.note_valid_packet(now)
        self.assertFalse(f.active)
        f.note_disconnect()
        self.assertTrue(f.active)

    def test_recovers_after_disconnect_once_valid_packet_returns(self):
        f = Failsafe()
        f.note_disconnect()
        self.assertTrue(f.active)
        f.note_valid_packet(time.ticks_ms())
        self.assertFalse(f.active)

    def test_repeated_valid_packets_keep_it_clear(self):
        f = Failsafe()
        now = time.ticks_ms()
        for i in range(10):
            now = time.ticks_add(now, config.FAILSAFE_TIMEOUT_MS - 50)
            f.note_valid_packet(now)
            self.assertFalse(f.update(now))


if __name__ == "__main__":
    unittest.main()
