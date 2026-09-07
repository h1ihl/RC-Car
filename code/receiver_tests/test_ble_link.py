"""
Only the non-radio bookkeeping in ble_link.py is testable here -- packet
buffering, connection tracking, disconnect-event latching. Actually
advertising/scanning/connecting over real Bluetooth needs real hardware
and can't be verified from a desktop Python process. That gap is called
out explicitly in the final report, not hidden.
"""

import unittest

import _mocks  # noqa: F401
import config
import protocol
from ble_link import (
    BLEReceiverLink,
    advertising_payloads,
    MAX_ADV_PAYLOAD_LEN,
    _ADV_TYPE_UUID128_COMPLETE,
    _IRQ_CENTRAL_CONNECT,
    _IRQ_CENTRAL_DISCONNECT,
    _IRQ_GATTS_WRITE,
)
import bluetooth


class BLELinkTests(unittest.TestCase):
    def setUp(self):
        self.link = BLEReceiverLink(bluetooth.BLE())

    def test_not_connected_initially(self):
        self.assertFalse(self.link.is_connected())

    def test_connect_marks_connected(self):
        self.link._irq(_IRQ_CENTRAL_CONNECT, (1, 0, b""))
        self.assertTrue(self.link.is_connected())

    def test_disconnect_clears_connected_and_latches_event(self):
        self.link._irq(_IRQ_CENTRAL_CONNECT, (1, 0, b""))
        self.link._irq(_IRQ_CENTRAL_DISCONNECT, (1, 0, b""))
        self.assertFalse(self.link.is_connected())
        self.assertTrue(self.link.take_disconnect_event())

    def test_disconnect_event_only_fires_once(self):
        self.link._irq(_IRQ_CENTRAL_CONNECT, (1, 0, b""))
        self.link._irq(_IRQ_CENTRAL_DISCONNECT, (1, 0, b""))
        self.assertTrue(self.link.take_disconnect_event())
        self.assertFalse(self.link.take_disconnect_event())

    def test_poll_returns_none_with_no_data(self):
        self.assertIsNone(self.link.poll())

    def test_write_to_control_handle_is_picked_up_by_poll(self):
        self.link._ble._last_write = b"\x01\x02\x03"
        # patch gatts_read to hand back what "arrived"
        self.link._ble.gatts_read = lambda handle: b"\x01\x02\x03"
        self.link._irq(_IRQ_GATTS_WRITE, (1, self.link._control_handle))
        self.assertEqual(self.link.poll(), b"\x01\x02\x03")

    def test_poll_only_returns_new_packet_once(self):
        self.link._ble.gatts_read = lambda handle: b"\xaa"
        self.link._irq(_IRQ_GATTS_WRITE, (1, self.link._control_handle))
        self.assertEqual(self.link.poll(), b"\xaa")
        self.assertIsNone(self.link.poll())

    def test_write_to_other_handle_is_ignored(self):
        self.link._ble.gatts_read = lambda handle: b"\xaa"
        self.link._irq(_IRQ_GATTS_WRITE, (1, self.link._control_handle + 999))
        self.assertIsNone(self.link.poll())

    def test_control_characteristic_buffer_is_sized_to_one_packet(self):
        self.assertEqual(self.link._ble.buffer_sizes[self.link._control_handle],
                         protocol.PACKET_LEN)


class AdvertisingPayloadTests(unittest.TestCase):
    """Regression tests for the bug that stopped the car being findable
    at all.

    A BLE advertising packet's payload is 31 bytes, hard limit. Flags (3)
    + a 128-bit service UUID (18) is 21 of them; the device name costs
    2 + len(name) on top, which for "RCCarReceiver" is 15 and puts the
    total at 36. MicroPython rejects an oversized payload, so
    gap_advertise() raised and the receiver never advertised -- which
    from the transmitter's side looks exactly like "the car isn't there."

    The fix is that the name moved to the scan response, which gets its
    own separate 31-byte budget. What must NOT happen is the name (or
    anything else) drifting back into the main payload, so these tests
    pin both the size and which payload the UUID has to be in.
    """

    def test_both_payloads_fit_in_a_ble_advertising_packet(self):
        adv, resp = advertising_payloads(config.BLE_DEVICE_NAME,
                                         config.BLE_SERVICE_UUID)
        self.assertLessEqual(len(adv), MAX_ADV_PAYLOAD_LEN)
        self.assertLessEqual(len(resp), MAX_ADV_PAYLOAD_LEN)

    def test_name_and_uuid_together_would_not_have_fit(self):
        """The thing being guarded against, spelled out: this is why the
        two can't share one payload."""
        combined = 3 + (2 + len(config.BLE_DEVICE_NAME)) + (2 + 16)
        self.assertGreater(combined, MAX_ADV_PAYLOAD_LEN)

    def test_service_uuid_is_in_the_main_payload_not_the_scan_response(self):
        """Both transmitters scan passively and match on the service
        UUID. A passive scan never sees a scan response, so a UUID that
        drifted into resp_data would be invisible to them."""
        adv, resp = advertising_payloads(config.BLE_DEVICE_NAME,
                                         config.BLE_SERVICE_UUID)
        uuid_bytes = bytes(bluetooth.UUID(config.BLE_SERVICE_UUID))
        self.assertIn(bytes([len(uuid_bytes) + 1, _ADV_TYPE_UUID128_COMPLETE]) + uuid_bytes,
                      adv)
        self.assertNotIn(uuid_bytes, resp)

    def test_name_is_in_the_scan_response(self):
        _adv, resp = advertising_payloads(config.BLE_DEVICE_NAME,
                                          config.BLE_SERVICE_UUID)
        self.assertIn(config.BLE_DEVICE_NAME.encode(), resp)

    def test_an_oversized_payload_is_rejected_loudly(self):
        with self.assertRaises(ValueError):
            advertising_payloads("A" * 40, config.BLE_SERVICE_UUID)

    def test_link_actually_advertises_both_payloads(self):
        link = BLEReceiverLink(bluetooth.BLE())
        self.assertIsNotNone(link._ble.adv_data)
        self.assertIsNotNone(link._ble.resp_data)
        self.assertLessEqual(len(link._ble.adv_data), MAX_ADV_PAYLOAD_LEN)
        self.assertLessEqual(len(link._ble.resp_data), MAX_ADV_PAYLOAD_LEN)

    def test_reconnect_advertising_uses_the_same_payloads(self):
        """_advertise() runs straight from the disconnect IRQ, so the
        payloads are built once up front rather than rebuilt in there."""
        link = BLEReceiverLink(bluetooth.BLE())
        first = link._ble.adv_data
        link._irq(_IRQ_CENTRAL_CONNECT, (1, 0, b""))
        link._irq(_IRQ_CENTRAL_DISCONNECT, (1, 0, b""))
        self.assertEqual(link._ble.adv_data, first)


if __name__ == "__main__":
    unittest.main()
