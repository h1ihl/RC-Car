"""
The test transmitter stub is self-contained (runs on a separate physical
Pico, no shared filesystem with the receiver -- see the comment at the
top of ble_test_tx.py), which means its BLE UUIDs and packet encoder are
copy-pasted rather than imported from receiver/. That's a real place for
the two to silently drift apart. This test is the guard against that:
it checks the stub's constants against the receiver's real config, and
feeds the stub's encoder output into the receiver's real decoder.

Doesn't test actual radio behaviour -- see test_ble_link.py's docstring
for that same caveat.
"""

import os
import sys
import unittest

import _mocks  # noqa: F401

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "test_transmitter"))

import bluetooth
import config
import protocol
import ble_test_tx


class TxStubCompatTests(unittest.TestCase):
    def test_uuids_match_receiver_config(self):
        self.assertEqual(ble_test_tx.BLE_SERVICE_UUID, config.BLE_SERVICE_UUID)
        self.assertEqual(ble_test_tx.BLE_CONTROL_CHAR_UUID, config.BLE_CONTROL_CHAR_UUID)

    def test_stub_encoded_packet_decodes_correctly_on_the_receiver_side(self):
        cases = [(0.0, 0.0, 0), (1.0, -1.0, 1), (-1.0, 1.0, 65535), (0.42, -0.77, 99)]
        for throttle, steering, seq in cases:
            packet = ble_test_tx._encode(throttle, steering, seq)
            decoded = protocol.decode(packet)
            self.assertIsNotNone(decoded, "receiver rejected a packet the tx stub encoded")
            t, s, decoded_seq = decoded
            self.assertAlmostEqual(t, throttle, places=2)
            self.assertAlmostEqual(s, steering, places=2)
            self.assertEqual(decoded_seq, seq & 0xFFFF)

    def test_receiver_link_constructs_without_error(self):
        link = ble_test_tx.ReceiverLink(bluetooth.BLE())
        link.scan_and_connect()
        self.assertFalse(link.ready())


if __name__ == "__main__":
    unittest.main()
