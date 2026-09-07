"""
_mocks.py -- fakes just enough of `machine`/`bluetooth`/`micropython`,
and patches `time`, so the receiver's actual control-logic modules can
be imported and exercised with plain desktop Python.

There's no Pico attached to this dev machine, so this is how the
ramping/failsafe/protocol logic actually gets tested before it ever
touches real hardware. It's not a simulation of the hardware behaving
correctly -- it's just enough of a stand-in that the modules import and
the fake calls don't blow up, so the *logic* around them can be checked.

Import this before importing anything from ../receiver.
"""

import os
import sys
import time
import types

_RECEIVER_DIR = os.path.join(os.path.dirname(__file__), "..", "receiver")
if _RECEIVER_DIR not in sys.path:
    sys.path.insert(0, _RECEIVER_DIR)


# --- time.ticks_ms / ticks_diff / ticks_add -------------------------------
# MicroPython-only, not in desktop Python's time module. A plain
# millisecond counter is a fine stand-in here -- we're testing ramp and
# timeout math, not real wall-clock behaviour.

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


class _FakePWM:
    def __init__(self, pin):
        self._pin = pin
        self._duty = 0
        self._freq = 0

    def freq(self, hz=None):
        if hz is None:
            return self._freq
        self._freq = hz

    def duty_u16(self, v=None):
        if v is None:
            return self._duty
        self._duty = v

    def deinit(self):
        pass


class _FakeADC:
    def __init__(self, pin):
        self._pin = pin

    def read_u16(self):
        return 32768  # arbitrary mid-scale -- battery.py isn't under test here


if "machine" not in sys.modules:
    _machine = types.ModuleType("machine")
    _machine.Pin = _FakePin
    _machine.PWM = _FakePWM
    _machine.ADC = _FakeADC
    sys.modules["machine"] = _machine


# --- fake `bluetooth` / `micropython` --------------------------------------

if "bluetooth" not in sys.modules:
    _bt = types.ModuleType("bluetooth")

    class _FakeUUID:
        # Real bluetooth.UUID normalizes whatever it's constructed from
        # (a dashed string, or raw bytes off the air) into one canonical
        # byte form for comparison -- that's what lets a link built a
        # UUID from an advertising payload and compare it against one
        # built from config.py's string and have equality actually work.
        # Comparing .value directly would fail that exact case (str vs
        # bytes), so equality/hash go through _bytes() instead.
        def __init__(self, value):
            self.value = value

        def _bytes(self):
            # doesn't need to be spec-correct BLE wire format -- just
            # needs to behave like a fixed-length buffer so ble_link.py's
            # advertising payload builder measures the right size
            if isinstance(self.value, (bytes, bytearray)):
                return bytes(self.value).ljust(16, b"\x00")[:16]
            return str(self.value).encode().ljust(16, b"\x00")[:16]

        def __eq__(self, other):
            return isinstance(other, _FakeUUID) and self._bytes() == other._bytes()

        def __hash__(self):
            return hash(self._bytes())

        def __bytes__(self):
            return self._bytes()

    class _FakeBLE:
        def __init__(self):
            self.adv_data = None
            self.resp_data = None
            self.buffer_sizes = {}

        def active(self, *a, **kw):
            pass

        def irq(self, *a, **kw):
            pass

        def gatts_register_services(self, *a, **kw):
            return ((0,),)

        def gatts_read(self, *a, **kw):
            return b""

        def gatts_set_buffer(self, handle, size, append=False):
            self.buffer_sizes[handle] = size

        def gap_advertise(self, interval_us, adv_data=None, resp_data=None, **kw):
            # recorded so tests can check the payloads actually fit in a
            # BLE advertising packet -- see test_ble_link.py
            self.adv_data = adv_data
            self.resp_data = resp_data

        # central-role methods, used by the test transmitter stub
        def gap_scan(self, *a, **kw):
            pass

        def gap_connect(self, *a, **kw):
            pass

        def gap_disconnect(self, *a, **kw):
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
