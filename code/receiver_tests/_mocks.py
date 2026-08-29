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
        def __init__(self, value):
            self.value = value

        def __eq__(self, other):
            return isinstance(other, _FakeUUID) and self.value == other.value

        def __hash__(self):
            return hash(self.value)

    class _FakeBLE:
        def active(self, *a, **kw):
            pass

        def irq(self, *a, **kw):
            pass

        def gatts_register_services(self, *a, **kw):
            return ((0,),)

        def gatts_read(self, *a, **kw):
            return b""

        def gap_advertise(self, *a, **kw):
            pass

    _bt.UUID = _FakeUUID
    _bt.BLE = _FakeBLE
    sys.modules["bluetooth"] = _bt

if "micropython" not in sys.modules:
    _mp = types.ModuleType("micropython")
    _mp.const = lambda x: x
    sys.modules["micropython"] = _mp
