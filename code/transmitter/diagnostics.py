"""
diagnostics.py -- onboard LED as a connection indicator.

Same "LED" board name and try/except fallback as receiver/diagnostics.py,
since the Pico W's onboard LED is wired through the wireless chip rather
than being a plain GPIO on some firmware builds -- if that name isn't
supported, skip the light instead of crashing the transmitter over it.

Blink pattern: not linked to the receiver = slow blink (same period as
the receiver's own "not connected" blink, so both boards speak the same
visual language). Linked and sending = solid on.
"""

import time

import config

try:
    from machine import Pin
    _led = Pin("LED", Pin.OUT)
except Exception:
    _led = None


class Diagnostics:
    def __init__(self):
        self._blink_state = False
        self._last_blink_ms = 0

    def _set_led(self, on):
        if _led is not None:
            _led.value(1 if on else 0)

    def tick(self, now_ms, linked):
        try:
            if linked:
                self._set_led(True)
                return

            if time.ticks_diff(now_ms, self._last_blink_ms) >= config.LED_BLINK_MS:
                self._last_blink_ms = now_ms
                self._blink_state = not self._blink_state
                self._set_led(self._blink_state)
        except Exception as e:
            print("diagnostics error (non-fatal):", e)
