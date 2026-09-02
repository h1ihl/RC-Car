"""
protocol.py -- wire-format encoder for outgoing control packets.

Copy-pasted from receiver/protocol.py rather than imported -- this runs
on a physically separate Pico with its own flash (same reasoning as
test_transmitter/ble_test_tx.py). Only encode() is needed here; the
transmitter never decodes anything, it just sends.
../transmitter_tests/test_receiver_compat.py feeds this encoder's
output into the receiver's real decoder so the two copies can't
silently drift apart.

Fixed 8 bytes, little-endian:

    magic (1)  seq (2)  throttle (2)  steering (2)  checksum (1)

See receiver/protocol.py for the full format rationale (why a scaled
int instead of a float, why the checksum is just a cheap second gate on
top of BLE's own link-layer CRC).
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
