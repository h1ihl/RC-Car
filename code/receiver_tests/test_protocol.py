import unittest

import _mocks  # noqa: F401
import protocol


class ProtocolTests(unittest.TestCase):
    def test_round_trip(self):
        packet = protocol.encode(0.5, -0.25, seq=7)
        self.assertEqual(len(packet), protocol.PACKET_LEN)
        t, s, seq = protocol.decode(packet)
        self.assertAlmostEqual(t, 0.5, places=3)
        self.assertAlmostEqual(s, -0.25, places=3)
        self.assertEqual(seq, 7)

    def test_extremes_round_trip(self):
        for throttle, steering in ((1.0, 1.0), (-1.0, -1.0), (0.0, 0.0)):
            t, s, _ = protocol.decode(protocol.encode(throttle, steering, seq=1))
            self.assertAlmostEqual(t, throttle, places=3)
            self.assertAlmostEqual(s, steering, places=3)

    def test_clamps_out_of_range_input_on_encode(self):
        packet = protocol.encode(2.0, -5.0, seq=0)
        t, s, _ = protocol.decode(packet)
        self.assertEqual(t, 1.0)
        self.assertEqual(s, -1.0)

    def test_rejects_wrong_length(self):
        self.assertIsNone(protocol.decode(b"\x00\x01\x02"))
        self.assertIsNone(protocol.decode(b""))

    def test_rejects_bad_checksum(self):
        packet = bytearray(protocol.encode(0.0, 0.0, seq=1))
        packet[-1] ^= 0xFF
        self.assertIsNone(protocol.decode(bytes(packet)))

    def test_single_flipped_byte_anywhere_is_caught(self):
        original = protocol.encode(0.3, -0.3, seq=42)
        for i in range(len(original)):
            corrupted = bytearray(original)
            corrupted[i] ^= 0x01
            self.assertIsNone(
                protocol.decode(bytes(corrupted)),
                "byte %d flip wasn't caught" % i,
            )

    def test_seq_wraps_to_16_bits(self):
        packet = protocol.encode(0.0, 0.0, seq=70000)  # > 65535
        _, _, seq = protocol.decode(packet)
        self.assertEqual(seq, 70000 & 0xFFFF)


if __name__ == "__main__":
    unittest.main()
