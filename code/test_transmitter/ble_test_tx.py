"""
ble_test_tx.py -- throwaway BLE test transmitter.

Runs on a SECOND Pico W (its own flash, separate device -- that's why
this file is self-contained rather than importing from ../receiver;
there's no shared filesystem between two Picos). Scans for the receiver,
connects, and pushes a scripted sequence of throttle/steering values at
it: ramp up, ramp down, reverse, steering sweep, then goes quiet on
purpose to check the receiver's failsafe actually trips, then starts
sending again to check it recovers.

This is NOT the real transmitter -- no joysticks involved, just a script
exercising the wireless path end to end. The real transmitter (reading
actual joysticks) is separate, out-of-scope work.

The BLE_SERVICE_UUID/BLE_CONTROL_CHAR_UUID/packet format below have to
match receiver/config.py and receiver/protocol.py exactly -- if either
changes on the receiver side, update the matching bits here too.
"""

import struct
import time
import bluetooth
from micropython import const

# --- must match receiver/config.py -----------------------------------
BLE_SERVICE_UUID = "c6a2f001-6b7e-4a1a-9f2e-3d4b5c6a7b8c"
BLE_CONTROL_CHAR_UUID = "c6a2f002-6b7e-4a1a-9f2e-3d4b5c6a7b8c"
SEND_INTERVAL_MS = 20  # ~50Hz, matches EXPECTED_PACKET_INTERVAL_MS

# --- must match receiver/protocol.py -----------------------------------
_MAGIC = 0xC5
_SCALE = 1000
_STRUCT_FMT = "<BHhh"


def _checksum(payload):
    x = 0
    for b in payload:
        x ^= b
    return x


def _encode(throttle, steering, seq):
    t = max(-_SCALE, min(_SCALE, int(throttle * _SCALE)))
    s = max(-_SCALE, min(_SCALE, int(steering * _SCALE)))
    body = struct.pack(_STRUCT_FMT, _MAGIC, seq & 0xFFFF, t, s)
    return body + bytes([_checksum(body)])


# --- BLE central plumbing -----------------------------------------------

_IRQ_SCAN_RESULT = const(5)
_IRQ_SCAN_DONE = const(6)
_IRQ_PERIPHERAL_CONNECT = const(7)
_IRQ_PERIPHERAL_DISCONNECT = const(8)
_IRQ_GATTC_SERVICE_RESULT = const(9)
_IRQ_GATTC_CHARACTERISTIC_RESULT = const(11)
_IRQ_GATTC_CHARACTERISTIC_DONE = const(12)

_ADV_IND = const(0x00)
_ADV_DIRECT_IND = const(0x01)
_ADV_TYPE_UUID128_COMPLETE = const(0x07)


class ReceiverLink:
    """Finds the receiver over BLE, connects, and exposes write(bytes)
    once the control characteristic handle is known."""

    def __init__(self, ble):
        self._ble = ble
        self._ble.active(True)
        self._ble.irq(self._irq)

        self._target_service = bluetooth.UUID(BLE_SERVICE_UUID)
        self._target_char = bluetooth.UUID(BLE_CONTROL_CHAR_UUID)

        self._addr_type = None
        self._addr = None
        self._conn_handle = None
        self._control_value_handle = None
        self._ready = False

    def scan_and_connect(self, timeout_ms=8000):
        print("scanning for receiver...")
        self._ble.gap_scan(timeout_ms, 30000, 30000)

    def _irq(self, event, data):
        if event == _IRQ_SCAN_RESULT:
            addr_type, addr, adv_type, rssi, adv_data = data
            if self._addr is None and self._looks_like_receiver(adv_type, adv_data):
                self._addr_type = addr_type
                self._addr = bytes(addr)
                self._ble.gap_scan(None)  # found it, stop scanning

        elif event == _IRQ_SCAN_DONE:
            if self._addr is not None and self._conn_handle is None:
                print("connecting to", ":".join("%02x" % b for b in self._addr))
                self._ble.gap_connect(self._addr_type, self._addr)
            elif self._addr is None:
                print("scan finished, receiver not found -- is it powered on and advertising?")

        elif event == _IRQ_PERIPHERAL_CONNECT:
            conn_handle, addr_type, addr = data
            self._conn_handle = conn_handle
            self._ble.gattc_discover_services(conn_handle)

        elif event == _IRQ_PERIPHERAL_DISCONNECT:
            self._ready = False
            self._conn_handle = None
            print("disconnected")

        elif event == _IRQ_GATTC_SERVICE_RESULT:
            conn_handle, start_handle, end_handle, uuid = data
            if uuid == self._target_service:
                self._ble.gattc_discover_characteristics(conn_handle, start_handle, end_handle)

        elif event == _IRQ_GATTC_CHARACTERISTIC_RESULT:
            conn_handle, def_handle, value_handle, properties, uuid = data
            if uuid == self._target_char:
                self._control_value_handle = value_handle

        elif event == _IRQ_GATTC_CHARACTERISTIC_DONE:
            if self._control_value_handle is not None:
                self._ready = True
                print("linked up, control handle ready")
            else:
                print("receiver's service didn't have the expected characteristic")

    def _looks_like_receiver(self, adv_type, adv_data):
        """Crude scan of the advertising payload's AD structures for our
        service UUID -- good enough for a bench test tool, not trying to
        be a general-purpose AD parser."""
        if adv_type not in (_ADV_IND, _ADV_DIRECT_IND):
            return False
        b = bytes(adv_data)
        i = 0
        while i < len(b):
            length = b[i]
            if length == 0:
                break
            ad_type = b[i + 1]
            value = b[i + 2:i + 1 + length]
            if ad_type == _ADV_TYPE_UUID128_COMPLETE and len(value) == 16:
                if bluetooth.UUID(value) == self._target_service:
                    return True
            i += 1 + length
        return False

    def ready(self):
        return self._ready

    def write(self, data):
        if self._ready:
            self._ble.gattc_write(self._conn_handle, self._control_value_handle, data, 1)


def _run_script(link):
    """Ramp throttle up/down/reverse, sweep steering, then go quiet to
    trigger the receiver's failsafe, then resume."""
    seq = 0

    def send(throttle, steering, hold_s):
        nonlocal seq
        end = time.ticks_add(time.ticks_ms(), int(hold_s * 1000))
        while time.ticks_diff(end, time.ticks_ms()) > 0:
            if link.ready():
                link.write(_encode(throttle, steering, seq))
                seq += 1
            time.sleep_ms(SEND_INTERVAL_MS)

    print("waiting for link...")
    while not link.ready():
        time.sleep_ms(100)

    print("linked. running test sequence.")
    send(0.0, 0.0, 1.0)     # centre first, confirm it holds still
    send(0.5, 0.0, 2.0)     # half throttle forward
    send(1.0, 0.0, 2.0)     # full throttle forward
    send(0.0, 0.0, 1.5)     # back to neutral, watch it ramp down
    send(-0.6, 0.0, 2.0)    # reverse
    send(0.0, 0.0, 1.0)

    send(0.0, -1.0, 1.5)    # full left
    send(0.0, 1.0, 1.5)     # full right
    send(0.0, 0.0, 1.0)     # back to centre

    print("going quiet for 2s -- receiver should hit failsafe and stop")
    time.sleep(2.0)

    print("resuming -- receiver should recover")
    send(0.3, 0.0, 2.0)
    send(0.0, 0.0, 1.0)

    print("test sequence done")


def main():
    link = ReceiverLink(bluetooth.BLE())
    link.scan_and_connect()
    _run_script(link)


if __name__ == "__main__":
    main()
