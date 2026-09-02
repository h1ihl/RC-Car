"""
Only encode() lives in the transmitter -- it never decodes anything.
Round-trip correctness against the receiver's real decoder is checked
in test_receiver_compat.py, not here.
"""

import struct
import unittest

import _mocks  # noqa: F401
import protocol


class ProtocolEncodeTests(unittest.TestCase):
    def test_encodes_to_the_fixed_packet_length(self):
        packet = protocol.encode(0.5, -0.25, seq=7)
        self.assertEqual(len(packet), protocol.PACKET_LEN)

    def test_clamps_out_of_range_input(self):
        packet = protocol.encode(2.0, -5.0, seq=0)
        _magic, _seq, t, s = struct.unpack("<BHhh", packet[:-1])
        self.assertEqual(t, protocol.SCALE)
        self.assertEqual(s, -protocol.SCALE)

    def test_seq_wraps_to_16_bits(self):
        packet = protocol.encode(0.0, 0.0, seq=70000)  # > 65535
        _magic, seq, _t, _s = struct.unpack("<BHhh", packet[:-1])
        self.assertEqual(seq, 70000 & 0xFFFF)

    def test_leads_with_the_magic_byte(self):
        packet = protocol.encode(0.0, 0.0, seq=0)
        self.assertEqual(packet[0], protocol.MAGIC)


if __name__ == "__main__":
    unittest.main()
