"""
failsafe.py -- kills the car if we stop hearing from the transmitter.

Starts already "expired" the moment it's constructed, so nothing moves
until a real valid packet shows up. That one trick covers Pico boot,
BLE bring-up, and the transmitter not being on yet, all with the same
piece of logic instead of a pile of separate special cases.
"""

import time

import config


class Failsafe:
    def __init__(self):
        # backdating last-valid puts us straight into failsafe right
        # away -- no separate "haven't heard anything yet" flag needed
        self._last_valid_ms = time.ticks_add(
            time.ticks_ms(), -(config.FAILSAFE_TIMEOUT_MS + 1)
        )
        self.active = True

    def note_valid_packet(self, now_ms):
        self._last_valid_ms = now_ms
        self.active = False

    def note_disconnect(self):
        """BLE told us the link dropped -- don't wait for the timeout
        to catch up, react now."""
        self.active = True

    def update(self, now_ms):
        """Call every loop tick. Re-checks whether we've gone stale.
        Returns the current active state."""
        if not self.active:
            elapsed = time.ticks_diff(now_ms, self._last_valid_ms)
            if elapsed > config.FAILSAFE_TIMEOUT_MS:
                self.active = True
        return self.active
