"""
ble_link.py -- the receiver's side of the wireless link. Runs as a BLE
GATT *peripheral*: advertises a custom service, waits for a central (the
test transmitter, or the real one) to connect and write control packets
to one characteristic.

Uses the raw `bluetooth` module rather than aioble -- it's built into
every Pico W MicroPython build (aioble sometimes needs a separate
install via mip), and the plain IRQ-callback style fits a synchronous
control loop better than pulling in an asyncio event loop for something
this safety-sensitive.

No pairing/bonding -- just a plain connection to a custom-UUID service.
Fine for a hobby RC project; flag it if this ever needs hardening.

The thing that actually bit us: a BLE advertising packet's payload is 31
bytes, hard limit. Flags (3) + a 128-bit service UUID (18) is already 21
of those, and the device name costs another 2 + len(name) -- 15 for
"RCCarReceiver", which puts the total at 36 and over the line.
MicroPython just rejects an oversized payload outright, so
gap_advertise() raised and the receiver never advertised at all, which
from the transmitter's side looks exactly like "the car isn't there."
The name lives in the scan response now, which gets its own separate
31-byte budget -- nothing scanning for us needs the name to find us
anyway, both transmitters match on the service UUID, and that stays in
the main payload where a passive scan actually sees it.
"""

import struct

import bluetooth
from micropython import const

import config
import protocol

_IRQ_CENTRAL_CONNECT = const(1)
_IRQ_CENTRAL_DISCONNECT = const(2)
_IRQ_GATTS_WRITE = const(3)

_FLAG_WRITE = const(0x0008)
_FLAG_WRITE_NO_RESPONSE = const(0x0004)

_ADV_TYPE_FLAGS = const(0x01)
_ADV_TYPE_NAME = const(0x09)
_ADV_TYPE_UUID128_COMPLETE = const(0x07)

# one BLE advertising payload, and separately one scan response, may
# each carry at most this many bytes
MAX_ADV_PAYLOAD_LEN = const(31)


def _pack_ad(*structures):
    """Packs (ad_type, value) pairs into an AD-structure payload:
    length byte, type byte, value -- repeated."""
    payload = bytearray()
    for ad_type, value in structures:
        payload.extend(struct.pack("BB", len(value) + 1, ad_type))
        payload.extend(value)
    if len(payload) > MAX_ADV_PAYLOAD_LEN:
        raise ValueError("BLE advertising payload is %d bytes, max is %d"
                         % (len(payload), MAX_ADV_PAYLOAD_LEN))
    return bytes(payload)


def advertising_payloads(name, service_uuid):
    """Returns (adv_data, resp_data).

    adv_data carries the flags and the 128-bit service UUID -- that's
    what a scanner filters on, so it has to be in the main payload.
    resp_data carries the human-readable name, which is only ever for
    someone poking at the car with a phone BLE scanner. See this
    module's docstring for why the name can't ride along in adv_data.
    """
    adv = _pack_ad(
        (_ADV_TYPE_FLAGS, struct.pack("B", 0x06)),  # general discoverable, no BR/EDR
        (_ADV_TYPE_UUID128_COMPLETE, bytes(bluetooth.UUID(service_uuid))),
    )
    resp = _pack_ad((_ADV_TYPE_NAME, name.encode()))
    return adv, resp


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

        # size the characteristic's value buffer to exactly one packet,
        # and don't append -- a fresh write replaces the old value
        # rather than queueing behind it. Stale control input is worse
        # than no control input.
        try:
            self._ble.gatts_set_buffer(self._control_handle, protocol.PACKET_LEN, False)
        except AttributeError:
            pass  # older firmware without gatts_set_buffer -- default buffer is fine

        self._connections = set()
        self._latest_packet = None
        self._has_new_packet = False
        self._disconnected_flag = False

        # built once here rather than per-advertise: _advertise() gets
        # called straight from the disconnect IRQ, and an IRQ handler is
        # no place to be allocating bytearrays and packing structs
        self._adv_data, self._resp_data = advertising_payloads(
            name, config.BLE_SERVICE_UUID)

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
        self._ble.gap_advertise(interval_us,
                                adv_data=self._adv_data,
                                resp_data=self._resp_data)

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
