"""
ble_link.py -- the transmitter's side of the wireless link. Runs as a
BLE GATT *central*: scans for the receiver's advertised service,
connects, discovers its control characteristic, and exposes
write(bytes) once that handle is known.

Same no-pairing/no-bonding tradeoff as the receiver side -- fine for a
hobby RC link, flag it if this ever needs hardening.

A few things in here are deliberate, worth not "cleaning up" later:

Writes go out without waiting for a response. Control packets go out at
50Hz, and a write-WITH-response can only have one request outstanding at
a time -- firing the next one 20ms later, before the receiver's ack is
back, just errors out, so the stream died after the first packet or two.
Unacknowledged writes are also just the right shape for this data: a
control packet that doesn't make it is worthless 20ms later anyway, the
next one's already on its way, and the failsafe covers a real outage.
The receiver's characteristic advertises both WRITE and
WRITE_NO_RESPONSE so it's happy either way.

The IRQ handler doesn't touch the BLE stack -- it only records what
happened and sets _pending, and tick() is what actually calls
gap_scan/gap_connect/discovery, from the main loop. Calling back into
the stack from inside its own callback is the kind of thing that works
fine on the bench and then wedges in the field.

And every wait has a deadline now. A scan that finds nothing, a connect
that never completes, a receiver whose service doesn't have the
characteristic we want -- any of those used to just leave the
transmitter sitting there forever with its LED blinking. tick() times
each stage out and starts over instead.
"""

import time

import bluetooth
from micropython import const

import config

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

# write mode 0 = write without response. See point 1 in the docstring.
_WRITE_NO_RESPONSE = const(0)

# what tick() should do next, set by the IRQ handler
_DO_NOTHING = const(0)
_DO_SCAN = const(1)
_DO_STOP_SCAN = const(2)
_DO_CONNECT = const(3)
_DO_DISCOVER_SERVICES = const(4)
_DO_DISCOVER_CHARS = const(5)
_DO_RESTART = const(6)

# which stage we're waiting in, so tick() knows which deadline applies
_STAGE_SCANNING = "scanning"
_STAGE_CONNECTING = "connecting"
_STAGE_DISCOVERING = "discovering"
_STAGE_READY = "ready"


class TransmitterLink:
    """Finds the receiver over BLE, connects, and exposes write(bytes)
    once the control characteristic handle is known. Keeps trying to
    (re)connect on its own -- callers just pump tick() every loop and
    check ready() before writing."""

    def __init__(self, ble, scan_timeout_ms=None, connect_timeout_ms=None):
        self._ble = ble
        self._ble.active(True)
        self._ble.irq(self._irq)

        self._scan_timeout_ms = scan_timeout_ms or config.SCAN_TIMEOUT_MS
        self._connect_timeout_ms = connect_timeout_ms or config.CONNECT_TIMEOUT_MS
        self._target_service = bluetooth.UUID(config.BLE_SERVICE_UUID)
        self._target_char = bluetooth.UUID(config.BLE_CONTROL_CHAR_UUID)

        self._addr_type = None
        self._addr = None
        self._conn_handle = None
        self._service_range = None
        self._control_value_handle = None
        self._ready = False

        self._pending = _DO_SCAN
        self._stage = _STAGE_SCANNING
        self._stage_started_ms = time.ticks_ms()
        self._note = None       # message from the IRQ for tick() to print
        self._write_errors = 0

    # --- what the main loop calls ----------------------------------------

    def ready(self):
        return self._ready

    def write(self, data):
        """Fire-and-forget a control packet. Returns True if it went to
        the stack, False if there's no link or the stack refused it (its
        buffers full, or the connection dropping right now). Never
        raises -- a dropped control packet must not be able to take the
        send loop down with it."""
        if not self._ready:
            return False
        try:
            self._ble.gattc_write(self._conn_handle, self._control_value_handle,
                                  data, _WRITE_NO_RESPONSE)
            return True
        except OSError:
            # usually ENOMEM/EBUSY: the stack's outgoing buffer is
            # momentarily full. The next packet is 20ms away, so drop
            # this one and move on.
            self._write_errors += 1
            return False

    def tick(self, now_ms=None):
        """Call every main-loop iteration. Runs whatever BLE call the
        IRQ asked for, and enforces the per-stage deadlines."""
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

    # --- tick()'s internals ------------------------------------------------

    def _run(self, action, now_ms):
        try:
            if action == _DO_SCAN:
                self._enter(_STAGE_SCANNING, now_ms)
                self._addr = None
                self._addr_type = None
                print("scanning for receiver...")
                self._ble.gap_scan(self._scan_timeout_ms, 30000, 30000)

            elif action == _DO_STOP_SCAN:
                # found it -- stop early instead of burning the rest of
                # the scan window. _IRQ_SCAN_DONE follows and moves us on.
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
            # link dropped but the rescan never got picked up -- the IRQ
            # can set _pending in the window where tick() has just taken
            # it. Rare, self-inflicted, and this is the net under it.
            self._restart(now_ms)
            return

        elapsed = time.ticks_diff(now_ms, self._stage_started_ms)
        if self._stage == _STAGE_SCANNING:
            # _IRQ_SCAN_DONE normally ends a scan well before this; the
            # slack is only here to catch a scan that never reports back
            limit = self._scan_timeout_ms + 3000
        else:
            limit = self._connect_timeout_ms

        if elapsed > limit:
            print("%s timed out after %dms -- starting over" % (self._stage, elapsed))
            self._restart(now_ms)

    def _restart(self, now_ms):
        """Tear down whatever half-built link we have and go back to
        scanning. Safe to call from any stage."""
        if self._conn_handle is not None:
            try:
                self._ble.gap_disconnect(self._conn_handle)
            except (OSError, AttributeError):
                pass
        else:
            try:
                self._ble.gap_scan(None)      # stop any scan still running
            except (OSError, AttributeError):
                pass
            try:
                self._ble.gap_connect(None)   # cancel a connect in flight
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

    # --- IRQ: records state, never calls back into the BLE stack ----------

    def _irq(self, event, data):
        if event == _IRQ_SCAN_RESULT:
            addr_type, addr, adv_type, _rssi, adv_data = data
            if self._addr is None and self._looks_like_receiver(adv_type, adv_data):
                self._addr_type = addr_type
                self._addr = bytes(addr)
                self._pending = _DO_STOP_SCAN

        elif event == _IRQ_SCAN_DONE:
            if self._conn_handle is not None:
                pass  # already linked up; a stale scan-done means nothing
            elif self._addr is not None:
                self._pending = _DO_CONNECT
            else:
                self._note = "receiver not found, retrying scan..."
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
                # connected to something that isn't our receiver, or the
                # receiver came up wrong -- drop it and look again
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
        service UUID -- not trying to be a general-purpose AD parser,
        but it does have to survive a malformed payload without throwing
        (this runs inside the IRQ, where an exception goes nowhere useful
        and takes the link with it).

        The receiver puts the service UUID in the main advertising
        payload precisely so a passive scan like ours can match on it --
        its device name lives in the scan response, which we never ask
        for and don't need. See receiver/ble_link.py's docstring.
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
