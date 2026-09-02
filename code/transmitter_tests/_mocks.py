"""
_mocks.py -- fakes just enough of `machine`/`bluetooth`/`micropython`,
and patches `time`, so the transmitter's actual control-logic modules
can be imported and exercised with plain desktop Python.

Same approach and same reasoning as receiver_tests/_mocks.py -- there's
no Pico attached to this dev machine, so this is how the joystick-
scaling and BLE-central bookkeeping logic gets tested before it ever
touches real hardware.

Import this before importing anything from ../transmitter.
"""

import os
import sys
import time
import types

_TRANSMITTER_DIR = os.path.join(os.path.dirname(__file__), "..", "transmitter")
if _TRANSMITTER_DIR not in sys.path:
    sys.path.insert(0, _TRANSMITTER_DIR)


# --- time.ticks_ms / ticks_diff / ticks_add -------------------------------
# MicroPython-only, not in desktop Python's time module.

if not hasattr(time, "ticks_ms"):
    time.ticks_ms = lambda: int(time.time() * 1000)
    time.ticks_diff = lambda a, b: a - b
    time.ticks_add = lambda a, b: a + b
    time.sleep_ms = lambda ms: None  # tests shouldn't actually block
    time.sleep_us = lambda us: None


# --- fake `machine` --------------------------------------------------------

class _FakePin:
    OUT = "OUT"

    def __init__(self, *a, **kw):
        self._value = kw.get("value", 0)

    def value(self, v=None):
        if v is None:
            return self._value
        self._value = v


class _FakeADC:
    def __init__(self, pin):
        self._pin = pin
        self._value = 32768  # arbitrary mid-scale default, overridable per test

    def read_u16(self):
        return self._value


if "machine" not in sys.modules:
    _machine = types.ModuleType("machine")
    _machine.Pin = _FakePin
    _machine.ADC = _FakeADC
    sys.modules["machine"] = _machine


# --- fake `bluetooth` / `micropython` --------------------------------------

if "bluetooth" not in sys.modules:
    _bt = types.ModuleType("bluetooth")

    class _FakeUUID:
        # Real bluetooth.UUID normalizes whatever it's constructed from
        # (a dashed string, or raw bytes off the air) into one canonical
        # byte form for comparison -- that's what lets ble_link.py build
        # a UUID from an advertising payload and compare it against one
        # built from config.py's string and have equality actually work.
        # Comparing .value directly would fail that exact case (str vs
        # bytes), so equality/hash go through _bytes() instead.
        def __init__(self, value):
            self.value = value

        def _bytes(self):
            if isinstance(self.value, (bytes, bytearray)):
                return bytes(self.value).ljust(16, b"\x00")[:16]
            return str(self.value).encode().ljust(16, b"\x00")[:16]

        def __eq__(self, other):
            return isinstance(other, _FakeUUID) and self._bytes() == other._bytes()

        def __hash__(self):
            return hash(self._bytes())

        def __bytes__(self):
            # doesn't need to be spec-correct BLE wire format -- just
            # needs to behave like a fixed-length buffer
            return self._bytes()

    class _FakeBLE:
        def active(self, *a, **kw):
            pass

        def irq(self, *a, **kw):
            pass

        # central-role methods, used by the transmitter's ble_link
        def gap_scan(self, *a, **kw):
            pass

        def gap_connect(self, *a, **kw):
            pass

        def gattc_discover_services(self, *a, **kw):
            pass

        def gattc_discover_characteristics(self, *a, **kw):
            pass

        def gattc_write(self, *a, **kw):
            pass

    _bt.UUID = _FakeUUID
    _bt.BLE = _FakeBLE
    sys.modules["bluetooth"] = _bt

if "micropython" not in sys.modules:
    _mp = types.ModuleType("micropython")
    _mp.const = lambda x: x
    sys.modules["micropython"] = _mp
