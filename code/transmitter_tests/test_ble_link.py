"""
Only the non-radio bookkeeping in ble_link.py is testable here -- scan
result parsing, the connect/discover state machine, reconnect-on-drop.
Actually scanning/connecting over real Bluetooth needs real hardware
and can't be verified from a desktop Python process (same caveat as
receiver_tests/test_ble_link.py).
"""

import unittest

import _mocks  # noqa: F401
import config
from ble_link import (
    TransmitterLink,
    _IRQ_SCAN_RESULT,
    _IRQ_SCAN_DONE,
    _IRQ_PERIPHERAL_CONNECT,
    _IRQ_PERIPHERAL_DISCONNECT,
    _IRQ_GATTC_SERVICE_RESULT,
    _IRQ_GATTC_CHARACTERISTIC_RESULT,
    _IRQ_GATTC_CHARACTERISTIC_DONE,
    _ADV_IND,
)
import bluetooth

_FAKE_ADDR = b"\x01\x02\x03\x04\x05\x06"


def _advertising_payload_for(service_uuid):
    """Builds the same minimal AD structure the receiver's ble_link.py
    advertises, just enough for _looks_like_receiver to find it."""
    uuid_bytes = bytes(bluetooth.UUID(service_uuid))
    return bytes([len(uuid_bytes) + 1, 0x07]) + uuid_bytes


class BLELinkTests(unittest.TestCase):
    def setUp(self):
        self.link = TransmitterLink(bluetooth.BLE())

    def test_not_ready_initially(self):
        self.assertFalse(self.link.ready())

    def test_scan_result_for_our_service_locks_in_the_address(self):
        payload = _advertising_payload_for(config.BLE_SERVICE_UUID)
        self.link._irq(_IRQ_SCAN_RESULT, (0, _FAKE_ADDR, _ADV_IND, -50, payload))
        self.assertEqual(self.link._addr, _FAKE_ADDR)

    def test_scan_result_for_a_different_service_is_ignored(self):
        payload = _advertising_payload_for("00000000-0000-0000-0000-000000000000")
        self.link._irq(_IRQ_SCAN_RESULT, (0, _FAKE_ADDR, _ADV_IND, -50, payload))
        self.assertIsNone(self.link._addr)

    def _link_up(self):
        """Drives the link through a full connect/discover sequence."""
        payload = _advertising_payload_for(config.BLE_SERVICE_UUID)
        self.link._irq(_IRQ_SCAN_RESULT, (0, _FAKE_ADDR, _ADV_IND, -50, payload))
        self.link._irq(_IRQ_SCAN_DONE, None)
        self.link._irq(_IRQ_PERIPHERAL_CONNECT, (1, 0, _FAKE_ADDR))
        self.link._irq(_IRQ_GATTC_SERVICE_RESULT, (1, 10, 20, self.link._target_service))
        self.link._irq(
            _IRQ_GATTC_CHARACTERISTIC_RESULT,
            (1, 11, 12, 0x0C, self.link._target_char),
        )
        self.link._irq(_IRQ_GATTC_CHARACTERISTIC_DONE, (1, 0))

    def test_full_discovery_sequence_marks_ready(self):
        self._link_up()
        self.assertTrue(self.link.ready())

    def test_write_only_sends_once_ready(self):
        sent = []
        self.link._ble.gattc_write = lambda *a: sent.append(a)

        self.link.write(b"\x01")
        self.assertEqual(sent, [])

        self._link_up()
        self.link.write(b"\x01")
        self.assertEqual(len(sent), 1)

    def test_scan_done_with_nothing_found_retries_the_scan(self):
        calls = []
        self.link._ble.gap_scan = lambda *a, **kw: calls.append(a)
        self.link._irq(_IRQ_SCAN_DONE, None)  # never got a scan result
        self.assertEqual(len(calls), 1)

    def test_disconnect_clears_ready_and_rescans(self):
        self._link_up()
        self.assertTrue(self.link.ready())

        calls = []
        self.link._ble.gap_scan = lambda *a, **kw: calls.append(a)
        self.link._irq(_IRQ_PERIPHERAL_DISCONNECT, (1, 0, _FAKE_ADDR))

        self.assertFalse(self.link.ready())
        self.assertEqual(len(calls), 1)


if __name__ == "__main__":
    unittest.main()
