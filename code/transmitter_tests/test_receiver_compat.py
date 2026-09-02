"""
The transmitter's config.py/protocol.py are copy-pasted from the
receiver's rather than imported (separate Pico, separate flash -- see
either file's docstring). That's a real place for the two to silently
drift apart. This test is the guard against that, same idea as
receiver_tests/test_tx_stub_compat.py but for the real transmitter
instead of the throwaway bench-test stub: it checks the transmitter's
UUIDs against the receiver's real config, and feeds the transmitter's
encoder output into the receiver's real decoder.

The receiver's config.py/protocol.py get loaded under aliased module
names via importlib rather than a plain `import config` -- this suite's
own _mocks.py already put ../transmitter first on sys.path, so a plain
`import config`/`import protocol` here would just hand back the
already-imported transmitter modules instead of the receiver's.
"""

import importlib.util
import os
import unittest

import _mocks  # noqa: F401 -- transmitter dir onto sys.path, fakes machine/bluetooth
import config     # transmitter's config.py
import protocol   # transmitter's protocol.py

_RECEIVER_DIR = os.path.join(os.path.dirname(__file__), "..", "receiver")


def _load(name, filename):
    spec = importlib.util.spec_from_file_location(name, os.path.join(_RECEIVER_DIR, filename))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


rx_config = _load("rx_config", "config.py")
rx_protocol = _load("rx_protocol", "protocol.py")


class ReceiverCompatTests(unittest.TestCase):
    def test_uuids_match_receiver_config(self):
        self.assertEqual(config.BLE_SERVICE_UUID, rx_config.BLE_SERVICE_UUID)
        self.assertEqual(config.BLE_CONTROL_CHAR_UUID, rx_config.BLE_CONTROL_CHAR_UUID)

    def test_protocol_constants_match(self):
        self.assertEqual(protocol.MAGIC, rx_protocol.MAGIC)
        self.assertEqual(protocol.SCALE, rx_protocol.SCALE)
        self.assertEqual(protocol.PACKET_LEN, rx_protocol.PACKET_LEN)

    def test_transmitter_encoded_packet_decodes_correctly_on_the_receiver_side(self):
        cases = [(0.0, 0.0, 0), (1.0, -1.0, 1), (-1.0, 1.0, 65535), (0.42, -0.77, 99)]
        for throttle, steering, seq in cases:
            packet = protocol.encode(throttle, steering, seq)
            decoded = rx_protocol.decode(packet)
            self.assertIsNotNone(decoded, "receiver rejected a packet the transmitter encoded")
            t, s, decoded_seq = decoded
            self.assertAlmostEqual(t, throttle, places=2)
            self.assertAlmostEqual(s, steering, places=2)
            self.assertEqual(decoded_seq, seq & 0xFFFF)


if __name__ == "__main__":
    unittest.main()
