"""
diagnostics.py -- onboard LED status + a periodic line on the USB REPL.

Nothing here is allowed to be load-bearing for safety. If something in
here breaks it should never be able to take the control loop down with
it, hence the broad except in tick().
"""

import time

import config

try:
    from machine import Pin
    _led = Pin("LED", Pin.OUT)
except Exception:
    # Pico W's onboard LED is wired through the wireless chip rather
    # than being a plain GPIO -- if this board/firmware build doesn't
    # support the "LED" name for some reason, just skip the light
    # instead of crashing the whole thing over it.
    _led = None


class Diagnostics:
    """Blink pattern: not linked = slow blink. Linked but in failsafe =
    fast blink (something's wrong even though we're paired). Linked and
    driving normally = solid on."""

    def __init__(self, battery):
        self.battery = battery
        self._last_print_ms = 0
        self._blink_state = False
        self._last_blink_ms = 0

    def _set_led(self, on):
        if _led is not None:
            _led.value(1 if on else 0)

    def _heartbeat(self, now_ms, link_connected, failsafe_active):
        if not link_connected:
            period = 1000
        elif failsafe_active:
            period = 150
        else:
            self._set_led(True)
            return

        if time.ticks_diff(now_ms, self._last_blink_ms) >= period:
            self._last_blink_ms = now_ms
            self._blink_state = not self._blink_state
            self._set_led(self._blink_state)

    def tick(self, now_ms, link_connected, failsafe_active, throttle_duty, steer_deg):
        try:
            self._heartbeat(now_ms, link_connected, failsafe_active)

            if time.ticks_diff(now_ms, self._last_print_ms) >= config.DIAG_INTERVAL_MS:
                self._last_print_ms = now_ms
                v = self.battery.volts() if self.battery is not None else float("nan")
                print("pack %.2fV  link=%s  failsafe=%s  duty=%.2f  steer=%.1f" % (
                    v, link_connected, failsafe_active, throttle_duty, steer_deg,
                ))
        except Exception as e:
            print("diagnostics error (non-fatal):", e)
