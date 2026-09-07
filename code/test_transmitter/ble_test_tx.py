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
actual joysticks) lives in ../transmitter/.

The BLE_SERVICE_UUID/BLE_CONTROL_CHAR_UUID/packet format below have to
match receiver/config.py and receiver/protocol.py exactly -- if either
changes on the receiver side, update the matching bits here too.
../receiver_tests/test_tx_stub_compat.py is the guard against that
drifting silently.

The BLE plumbing here mirrors ../transmitter/ble_link.py, including the
three things that file's docstring calls out: writes go out
unacknowledged (a 50Hz stream can't wait for an ack per packet), the IRQ
handler never calls back into the BLE stack (tick() does that from the
main loop), and every wait has a deadline so a failed scan or a
half-finished connect can't leave this thing hung forever.
"""

import struct
import time
import bluetooth
from micropython import const

# --- must match receiver/config.py -----------------------------------
BLE_SERVICE_UUID = "c6a2f001-6b7e-4a1a-9f2e-3d4b5c6a7b8c"
BLE_CONTROL_CHAR_UUID = "c6a2f002-6b7e-4a1a-9f2e-3d4b5c6a7b8c"
SEND_INTERVAL_MS = 20    # ~50Hz, matches EXPECTED_PACKET_INTERVAL_MS
SCAN_TIMEOUT_MS = 8000
CONNECT_TIMEOUT_MS = 5000

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
_IRQ_GATTC_SERVICE_DONE = const(10)
_IRQ_GATTC_CHARACTERISTIC_RESULT = const(11)
_IRQ_GATTC_CHARACTERISTIC_DONE = const(12)

_ADV_IND = const(0x00)
_ADV_DIRECT_IND = const(0x01)
_ADV_TYPE_UUID128_COMPLETE = const(0x07)

_WRITE_NO_RESPONSE = const(0)

_DO_NOTHING = const(0)
_DO_SCAN = const(1)
_DO_STOP_SCAN = const(2)
_DO_CONNECT = const(3)
_DO_DISCOVER_SERVICES = const(4)
_DO_DISCOVER_CHARS = const(5)
_DO_RESTART = const(6)

_STAGE_SCANNING = "scanning"
_STAGE_CONNECTING = "connecting"
_STAGE_DISCOVERING = "discovering"
_STAGE_READY = "ready"


class ReceiverLink:
    """Finds the receiver over BLE, connects, and exposes write(bytes)
    once the control characteristic handle is known. Pump tick() from
    whatever loop you're in; check ready() before writing."""

    def __init__(self, ble):
        self._ble = ble
        self._ble.active(True)
        self._ble.irq(self._irq)

        self._target_service = bluetooth.UUID(BLE_SERVICE_UUID)
        self._target_char = bluetooth.UUID(BLE_CONTROL_CHAR_UUID)

        self._addr_type = None
        self._addr = None
        self._conn_handle = None
        self._service_range = None
        self._control_value_handle = None
        self._ready = False

        self._pending = _DO_SCAN
        self._stage = _STAGE_SCANNING
        self._stage_started_ms = time.ticks_ms()
        self._note = None

    def scan_and_connect(self):
        """Kick the state machine off. tick() does the rest."""
        self._pending = _DO_SCAN
        self.tick()

    def ready(self):
        return self._ready

    def write(self, data):
        if not self._ready:
            return False
        try:
            self._ble.gattc_write(self._conn_handle, self._control_value_handle,
                                  data, _WRITE_NO_RESPONSE)
            return True
        except OSError:
            return False   # stack buffer momentarily full; next packet is 20ms out

    def tick(self, now_ms=None):
        if now_ms is None:
            now_ms = time.ticks_ms()

        if self._note is not None:
            print(self._note)
            self._note = None

        pending, self._pending = self._pending, _DO_NOTHING
        if pending != _DO_NOTHING:
            self._run(pending, now_ms)
            return

        self._check_deadline(now_ms)

    def _run(self, action, now_ms):
        try:
            if action == _DO_SCAN:
                self._enter(_STAGE_SCANNING, now_ms)
                self._addr = None
                self._addr_type = None
                print("scanning for receiver...")
                self._ble.gap_scan(SCAN_TIMEOUT_MS, 30000, 30000)

            elif action == _DO_STOP_SCAN:
                self._ble.gap_scan(None)

            elif action == _DO_CONNECT:
                self._enter(_STAGE_CONNECTING, now_ms)
                print("connecting to", ":".join("%02x" % b for b in self._addr))
                self._ble.gap_connect(self._addr_type, self._addr)

            elif action == _DO_DISCOVER_SERVICES:
                self._enter(_STAGE_DISCOVERING, now_ms)
                self._ble.gattc_discover_services(self._conn_handle)

            elif action == _DO_DISCOVER_CHARS:
                self._enter(_STAGE_DISCOVERING, now_ms)
                start, end = self._service_range
                self._ble.gattc_discover_characteristics(self._conn_handle, start, end)

            elif action == _DO_RESTART:
                self._restart(now_ms)

        except OSError as e:
            print("BLE call failed (%s) -- starting over" % e)
            self._restart(now_ms)

    def _check_deadline(self, now_ms):
        if self._stage == _STAGE_READY:
            if self._ready:
                return
            self._restart(now_ms)   # dropped but the rescan got lost
            return
        elapsed = time.ticks_diff(now_ms, self._stage_started_ms)
        limit = SCAN_TIMEOUT_MS + 3000 if self._stage == _STAGE_SCANNING else CONNECT_TIMEOUT_MS
        if elapsed > limit:
            print("%s timed out after %dms -- starting over" % (self._stage, elapsed))
            self._restart(now_ms)

    def _restart(self, now_ms):
        if self._conn_handle is not None:
            try:
                self._ble.gap_disconnect(self._conn_handle)
            except (OSError, AttributeError):
                pass
        else:
            try:
                self._ble.gap_scan(None)
            except (OSError, AttributeError):
                pass
            try:
                self._ble.gap_connect(None)
            except (OSError, AttributeError, TypeError):
                pass

        self._forget_connection()
        self._pending = _DO_SCAN
        self._enter(_STAGE_SCANNING, now_ms)

    def _forget_connection(self):
        self._ready = False
        self._conn_handle = None
        self._service_range = None
        self._control_value_handle = None
        self._addr = None
        self._addr_type = None

    def _enter(self, stage, now_ms):
        self._stage = stage
        self._stage_started_ms = now_ms

    def _irq(self, event, data):
        if event == _IRQ_SCAN_RESULT:
            addr_type, addr, adv_type, _rssi, adv_data = data
            if self._addr is None and self._looks_like_receiver(adv_type, adv_data):
                self._addr_type = addr_type
                self._addr = bytes(addr)
                self._pending = _DO_STOP_SCAN

        elif event == _IRQ_SCAN_DONE:
            if self._conn_handle is not None:
                pass
            elif self._addr is not None:
                self._pending = _DO_CONNECT
            else:
                self._note = "receiver not found -- is it powered on and advertising?"
                self._pending = _DO_SCAN

        elif event == _IRQ_PERIPHERAL_CONNECT:
            conn_handle, _addr_type, _addr = data
            self._conn_handle = conn_handle
            self._pending = _DO_DISCOVER_SERVICES

        elif event == _IRQ_PERIPHERAL_DISCONNECT:
            self._forget_connection()
            self._note = "disconnected -- rescanning"
            self._pending = _DO_SCAN

        elif event == _IRQ_GATTC_SERVICE_RESULT:
            _conn_handle, start_handle, end_handle, uuid = data
            if uuid == self._target_service:
                self._service_range = (start_handle, end_handle)

        elif event == _IRQ_GATTC_SERVICE_DONE:
            if self._service_range is not None:
                self._pending = _DO_DISCOVER_CHARS
            else:
                self._note = "connected device has no RC service -- starting over"
                self._pending = _DO_RESTART

        elif event == _IRQ_GATTC_CHARACTERISTIC_RESULT:
            _conn_handle, _def_handle, value_handle, _properties, uuid = data
            if uuid == self._target_char:
                self._control_value_handle = value_handle

        elif event == _IRQ_GATTC_CHARACTERISTIC_DONE:
            if self._control_value_handle is not None:
                self._ready = True
                self._stage = _STAGE_READY
                self._note = "linked up, control handle ready"
            else:
                self._note = "receiver's service didn't have the expected characteristic"
                self._pending = _DO_RESTART

    def _looks_like_receiver(self, adv_type, adv_data):
        """Crude scan of the advertising payload's AD structures for our
        service UUID -- good enough for a bench test tool, not trying to
        be a general-purpose AD parser, but bounds-checked so a
        malformed payload can't throw inside the IRQ.

        Matches on the UUID, which the receiver keeps in its main
        advertising payload; its name is in the scan response, which a
        passive scan like this one never sees.
        """
        if adv_type not in (_ADV_IND, _ADV_DIRECT_IND):
            return False
        b = bytes(adv_data)
        i = 0
        while i + 1 < len(b):
            length = b[i]
            if length == 0 or i + 1 + length > len(b):
                break
            ad_type = b[i + 1]
            value = b[i + 2:i + 1 + length]
            if ad_type == _ADV_TYPE_UUID128_COMPLETE and len(value) == 16:
                if bluetooth.UUID(value) == self._target_service:
                    return True
            i += 1 + length
        return False


def _run_script(link):
    """Ramp throttle up/down/reverse, sweep steering, then go quiet to
    trigger the receiver's failsafe, then resume."""
    seq = 0

    def send(throttle, steering, hold_s):
        """Streams one throttle/steering value for hold_s seconds. Keeps
        pumping link.tick() throughout, so a drop mid-sequence gets
        noticed and reconnected instead of quietly sending nothing."""
        nonlocal seq
        end = time.ticks_add(time.ticks_ms(), int(hold_s * 1000))
        while time.ticks_diff(end, time.ticks_ms()) > 0:
            link.tick()
            if link.ready():
                link.write(_encode(throttle, steering, seq))
                seq = (seq + 1) & 0xFFFF
            time.sleep_ms(SEND_INTERVAL_MS)

    def quiet(hold_s):
        """Deliberate silence -- still pumps tick() (so the link stays
        up) but sends nothing, which is exactly what the receiver's
        failsafe is supposed to catch."""
        end = time.ticks_add(time.ticks_ms(), int(hold_s * 1000))
        while time.ticks_diff(end, time.ticks_ms()) > 0:
            link.tick()
            time.sleep_ms(SEND_INTERVAL_MS)

    print("waiting for link...")
    while not link.ready():
        link.tick()
        time.sleep_ms(SEND_INTERVAL_MS)

    print("linked. running test sequence.")
    send(0.0, 0.0, 1.0)     # centre first, confirm it holds still
    send(0.5, 0.0, 2.0)     # half throttle forward
    send(1.0, 0.0, 2.0)     # full throttle forward
    send(0.0, 0.0, 1.5)     # back to neutral, watch it ramp down
    send(-0.6, 0.0, 2.0)    # reverse
    send(0.0, 0.0, 1.0)

    send(0.0, -1.0, 1.5)    # full left  -- receiver should sit at 1250us
    send(0.0, 1.0, 1.5)     # full right -- receiver should sit at 1750us
    send(0.0, 0.0, 1.0)     # back to centre

    print("going quiet for 2s -- receiver should hit failsafe and stop")
    quiet(2.0)

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
