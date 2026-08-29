"""
ble_link.py -- the receiver's side of the wireless link. Runs as a BLE
GATT *peripheral*: advertises a custom service, waits for a central (the
test transmitter, or eventually the real one) to connect and write
control packets to one characteristic.

Uses the raw `bluetooth` module rather than aioble -- it's built into
every Pico W MicroPython build (aioble sometimes needs a separate
install via mip), and the plain IRQ-callback style fits a synchronous
control loop better than pulling in an asyncio event loop for something
this safety-sensitive.

No pairing/bonding -- just a plain connection to a custom-UUID service.
Fine for a hobby RC project; flag it if this ever needs hardening.

The advertising payload builder below follows the standard pattern from
MicroPython's own BLE examples (name + a list of service UUIDs), trimmed
down to just the two AD types this project actually needs.
"""

import struct

import bluetooth
from micropython import const

import config

_IRQ_CENTRAL_CONNECT = const(1)
_IRQ_CENTRAL_DISCONNECT = const(2)
_IRQ_GATTS_WRITE = const(3)

_FLAG_WRITE = const(0x0008)
_FLAG_WRITE_NO_RESPONSE = const(0x0004)

_ADV_TYPE_FLAGS = const(0x01)
_ADV_TYPE_NAME = const(0x09)
_ADV_TYPE_UUID128_COMPLETE = const(0x07)


def _advertising_payload(name, service_uuid):
    """Minimal BLE advertising payload: flags + device name + one
    128-bit service UUID. That's all this project ever needs to
    advertise."""
    payload = bytearray()

    def _add(ad_type, value):
        payload.extend(struct.pack("BB", len(value) + 1, ad_type) + value)

    _add(_ADV_TYPE_FLAGS, struct.pack("B", 0x06))  # general discoverable, no BR/EDR
    _add(_ADV_TYPE_NAME, name.encode())
    _add(_ADV_TYPE_UUID128_COMPLETE, bytes(bluetooth.UUID(service_uuid)))

    return payload


class BLEReceiverLink:
    def __init__(self, ble, name=config.BLE_DEVICE_NAME):
        self._ble = ble
        self._ble.active(True)
        self._ble.irq(self._irq)

        service_uuid = bluetooth.UUID(config.BLE_SERVICE_UUID)
        char_uuid = bluetooth.UUID(config.BLE_CONTROL_CHAR_UUID)
        control_char = (char_uuid, _FLAG_WRITE | _FLAG_WRITE_NO_RESPONSE)
        service = (service_uuid, (control_char,))
        ((self._control_handle,),) = self._ble.gatts_register_services((service,))

        self._connections = set()
        self._latest_packet = None
        self._has_new_packet = False
        self._disconnected_flag = False

        self._name = name
        self._advertise()

    def _irq(self, event, data):
        if event == _IRQ_CENTRAL_CONNECT:
            conn_handle, _, _ = data
            self._connections.add(conn_handle)

        elif event == _IRQ_CENTRAL_DISCONNECT:
            conn_handle, _, _ = data
            self._connections.discard(conn_handle)
            self._disconnected_flag = True
            self._advertise()  # keep advertising so a reconnect is possible

        elif event == _IRQ_GATTS_WRITE:
            conn_handle, attr_handle = data
            if attr_handle == self._control_handle:
                self._latest_packet = self._ble.gatts_read(self._control_handle)
                self._has_new_packet = True

    def _advertise(self, interval_us=100_000):
        payload = _advertising_payload(self._name, config.BLE_SERVICE_UUID)
        self._ble.gap_advertise(interval_us, adv_data=payload)

    def poll(self):
        """Call once per main-loop tick. Returns the raw bytes of a new
        packet if one showed up since the last call, else None. Doesn't
        decode/validate -- that's protocol.py's job."""
        if self._has_new_packet:
            self._has_new_packet = False
            return self._latest_packet
        return None

    def take_disconnect_event(self):
        """Returns True exactly once per disconnect, then clears itself
        -- so main.py can react to it without double-triggering."""
        if self._disconnected_flag:
            self._disconnected_flag = False
            return True
        return False

    def is_connected(self):
        return len(self._connections) > 0
