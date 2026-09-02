"""
ble_link.py -- the transmitter's side of the wireless link. Runs as a
BLE GATT *central*: scans for the receiver's advertised service,
connects, discovers its control characteristic, and exposes
write(bytes) once that handle is known.

Ported from test_transmitter/ble_test_tx.py's ReceiverLink, with one
real behavioural change: that stub only ever connects once and just
prints "disconnected" if the link drops. This is meant to run
unattended on a real transmitter, so it re-scans automatically both
after a disconnect and after a scan that didn't find anything -- the
car might get powered on after the controller, or the link might drop
mid-drive and needs to come back without someone power-cycling the
transmitter. Re-scanning straight from the disconnect IRQ mirrors the
receiver's own ble_link.py, which re-advertises straight from ITS
disconnect IRQ for the same reason.

Same no-pairing/no-bonding tradeoff as the receiver side -- fine for a
hobby RC link, flag it if this ever needs hardening.
"""

import bluetooth
from micropython import const

import config

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


class TransmitterLink:
    """Finds the receiver over BLE, connects, and exposes write(bytes)
    once the control characteristic handle is known. Keeps trying to
    (re)connect on its own -- ready() is the only thing callers need to
    check before writing."""

    def __init__(self, ble, scan_timeout_ms=None):
        self._ble = ble
        self._ble.active(True)
        self._ble.irq(self._irq)

        self._scan_timeout_ms = scan_timeout_ms or config.SCAN_TIMEOUT_MS
        self._target_service = bluetooth.UUID(config.BLE_SERVICE_UUID)
        self._target_char = bluetooth.UUID(config.BLE_CONTROL_CHAR_UUID)

        self._addr_type = None
        self._addr = None
        self._conn_handle = None
        self._control_value_handle = None
        self._ready = False

        self._scan()

    def _scan(self):
        self._addr_type = None
        self._addr = None
        print("scanning for receiver...")
        self._ble.gap_scan(self._scan_timeout_ms, 30000, 30000)

    def _irq(self, event, data):
        if event == _IRQ_SCAN_RESULT:
            addr_type, addr, adv_type, rssi, adv_data = data
            if self._addr is None and self._looks_like_receiver(adv_type, adv_data):
                self._addr_type = addr_type
                self._addr = bytes(addr)
                self._ble.gap_scan(None)  # found it, stop scanning early

        elif event == _IRQ_SCAN_DONE:
            if self._addr is not None and self._conn_handle is None:
                print("connecting to", ":".join("%02x" % b for b in self._addr))
                self._ble.gap_connect(self._addr_type, self._addr)
            elif self._conn_handle is None:
                print("receiver not found, retrying scan...")
                self._scan()

        elif event == _IRQ_PERIPHERAL_CONNECT:
            conn_handle, _addr_type, _addr = data
            self._conn_handle = conn_handle
            self._ble.gattc_discover_services(conn_handle)

        elif event == _IRQ_PERIPHERAL_DISCONNECT:
            self._ready = False
            self._conn_handle = None
            self._control_value_handle = None
            print("disconnected -- rescanning")
            self._scan()

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
        service UUID -- matches the parsing in ble_test_tx.py, not
        trying to be a general-purpose AD parser."""
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
