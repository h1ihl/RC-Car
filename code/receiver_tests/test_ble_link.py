"""
Only the non-radio bookkeeping in ble_link.py is testable here -- packet
buffering, connection tracking, disconnect-event latching. Actually
advertising/scanning/connecting over real Bluetooth needs real hardware
and can't be verified from a desktop Python process. That gap is called
out explicitly in the final report, not hidden.
"""

import unittest

import _mocks  # noqa: F401
from ble_link import BLEReceiverLink, _IRQ_CENTRAL_CONNECT, _IRQ_CENTRAL_DISCONNECT, _IRQ_GATTS_WRITE
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


if __name__ == "__main__":
    unittest.main()
