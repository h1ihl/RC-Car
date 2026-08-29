"""
protocol.py -- the wire format for control packets.

Fixed 8 bytes, little-endian:

    magic (1)  seq (2)  throttle (2)  steering (2)  checksum (1)

throttle/steering are signed 16-bit ints, scaled by SCALE (1000) instead
of raw floats -- one less thing that can go wrong sending values between
two different boards.

checksum is just an XOR of everything before it. Not trying to catch
sophisticated corruption -- BLE already has its own CRC at the link
layer. This is a second, cheap gate against "the bytes decoded fine but
the values are garbage" on top of what the radio already guarantees.
"""

import struct

MAGIC = 0xC5
SCALE = 1000
_STRUCT_FMT = "<BHhh"
PACKET_LEN = struct.calcsize(_STRUCT_FMT) + 1  # +1 for the checksum byte


def _checksum(payload):
    x = 0
    for b in payload:
        x ^= b
    return x


def encode(throttle, steering, seq):
    """throttle/steering: floats in [-1.0, 1.0]. seq: any int, wraps to 16 bits."""
    t = max(-SCALE, min(SCALE, int(throttle * SCALE)))
    s = max(-SCALE, min(SCALE, int(steering * SCALE)))
    body = struct.pack(_STRUCT_FMT, MAGIC, seq & 0xFFFF, t, s)
    return body + bytes([_checksum(body)])


def decode(data):
    """Returns (throttle, steering, seq) or None if the packet's no good.

    Rejects anything the wrong length, missing our magic byte, failing
    the checksum, or somehow carrying an out-of-range value. Any of
    those and we just throw it away -- better a dropped packet than
    acting on garbage.
    """
    if len(data) != PACKET_LEN:
        return None

    body, given_checksum = data[:-1], data[-1]
    if _checksum(body) != given_checksum:
        return None

    magic, seq, t, s = struct.unpack(_STRUCT_FMT, body)
    if magic != MAGIC:
        return None

    if not (-SCALE <= t <= SCALE) or not (-SCALE <= s <= SCALE):
        return None

    return (t / SCALE, s / SCALE, seq)
