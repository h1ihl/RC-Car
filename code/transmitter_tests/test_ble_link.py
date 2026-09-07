"""
Only the non-radio bookkeeping in ble_link.py is testable here -- scan
result parsing, the connect/discover state machine, the stage timeouts,
reconnect-on-drop, and how writes are issued. Actually scanning and
connecting over real Bluetooth needs real hardware and can't be verified
from a desktop Python process (same caveat as
receiver_tests/test_ble_link.py).

A bunch of these are regression tests for the reasons the link didn't
come up in the first place, so they're pinned on purpose: writes have to
go out unacknowledged (a write-with-response can only have one request
outstanding, and a 50Hz stream breaks that instantly), the IRQ handler
can never call back into the BLE stack (tick() does that from the main
loop instead), and no stage is allowed to wait forever.
"""

import unittest

import _mocks  # noqa: F401
import config
from ble_link import (
    TransmitterLink,
    _WRITE_NO_RESPONSE,
    _IRQ_SCAN_RESULT,
    _IRQ_SCAN_DONE,
    _IRQ_PERIPHERAL_CONNECT,
    _IRQ_PERIPHERAL_DISCONNECT,
    _IRQ_GATTC_SERVICE_RESULT,
    _IRQ_GATTC_SERVICE_DONE,
    _IRQ_GATTC_CHARACTERISTIC_RESULT,
    _IRQ_GATTC_CHARACTERISTIC_DONE,
    _ADV_IND,
)
import bluetooth

_FAKE_ADDR = b"\x01\x02\x03\x04\x05\x06"
_CONN = 1


def _advertising_payload_for(service_uuid):
    """Builds the same AD structure the receiver's ble_link.py puts in
    its main advertising payload, just enough for _looks_like_receiver
    to find it."""
    uuid_bytes = bytes(bluetooth.UUID(service_uuid))
    return bytes([len(uuid_bytes) + 1, 0x07]) + uuid_bytes


class _RecordingBLE(bluetooth.BLE):
    """Records every stack call so tests can assert on what was called,
    when, and with what."""

    def __init__(self):
        self.calls = []
        self.write_error = None

    def _note(self, name, args):
        self.calls.append((name, args))

    def names(self):
        return [name for name, _args in self.calls]

    def gap_scan(self, *a):
        self._note("gap_scan", a)

    def gap_connect(self, *a):
        self._note("gap_connect", a)

    def gap_disconnect(self, *a):
        self._note("gap_disconnect", a)

    def gattc_discover_services(self, *a):
        self._note("gattc_discover_services", a)

    def gattc_discover_characteristics(self, *a):
        self._note("gattc_discover_characteristics", a)

    def gattc_write(self, *a):
        if self.write_error is not None:
            raise self.write_error
        self._note("gattc_write", a)


class _LinkFixture(unittest.TestCase):
    def setUp(self):
        self.ble = _RecordingBLE()
        self.link = TransmitterLink(self.ble)
        self.now = 0

    def tick(self, advance_ms=0):
        self.now += advance_ms
        self.link.tick(self.now)

    def see_receiver(self):
        payload = _advertising_payload_for(config.BLE_SERVICE_UUID)
        self.link._irq(_IRQ_SCAN_RESULT, (0, _FAKE_ADDR, _ADV_IND, -50, payload))

    def link_up(self):
        """Drives the link through a full scan/connect/discover sequence,
        pumping tick() between steps the way the main loop does."""
        self.tick()                 # starts the scan
        self.see_receiver()
        self.tick()                 # stops the scan early
        self.link._irq(_IRQ_SCAN_DONE, None)
        self.tick()                 # connects
        self.link._irq(_IRQ_PERIPHERAL_CONNECT, (_CONN, 0, _FAKE_ADDR))
        self.tick()                 # discovers services
        self.link._irq(_IRQ_GATTC_SERVICE_RESULT,
                       (_CONN, 10, 20, self.link._target_service))
        self.link._irq(_IRQ_GATTC_SERVICE_DONE, (_CONN, 0))
        self.tick()                 # discovers characteristics
        self.link._irq(_IRQ_GATTC_CHARACTERISTIC_RESULT,
                       (_CONN, 11, 12, 0x0C, self.link._target_char))
        self.link._irq(_IRQ_GATTC_CHARACTERISTIC_DONE, (_CONN, 0))
        self.tick()


class ScanAndConnectTests(_LinkFixture):
    def test_not_ready_initially(self):
        self.assertFalse(self.link.ready())

    def test_construction_does_not_touch_the_radio(self):
        """Everything the link does to the stack happens from tick(), so
        a caller always gets to decide when that starts."""
        self.assertEqual(self.ble.names(), [])

    def test_first_tick_starts_the_scan(self):
        self.tick()
        self.assertEqual(self.ble.names(), ["gap_scan"])

    def test_scan_result_for_our_service_locks_in_the_address(self):
        self.tick()
        self.see_receiver()
        self.assertEqual(self.link._addr, _FAKE_ADDR)

    def test_scan_result_for_a_different_service_is_ignored(self):
        self.tick()
        payload = _advertising_payload_for("00000000-0000-0000-0000-000000000000")
        self.link._irq(_IRQ_SCAN_RESULT, (0, _FAKE_ADDR, _ADV_IND, -50, payload))
        self.assertIsNone(self.link._addr)

    def test_malformed_advertising_payload_does_not_throw(self):
        """This runs inside the IRQ, where an exception goes nowhere
        useful and takes the link down with it."""
        self.tick()
        for junk in (b"", b"\x05", b"\x20\x07\x01", b"\xff" * 3, b"\x00\x00"):
            self.link._irq(_IRQ_SCAN_RESULT, (0, _FAKE_ADDR, _ADV_IND, -50, junk))
        self.assertIsNone(self.link._addr)

    def test_full_discovery_sequence_marks_ready(self):
        self.link_up()
        self.assertTrue(self.link.ready())

    def test_discovery_targets_the_range_the_service_was_found_in(self):
        self.link_up()
        discover = dict(self.ble.calls)["gattc_discover_characteristics"]
        self.assertEqual(discover, (_CONN, 10, 20))

    def test_scan_done_with_nothing_found_retries_the_scan(self):
        self.tick()
        self.ble.calls.clear()
        self.link._irq(_IRQ_SCAN_DONE, None)
        self.tick()
        self.assertEqual(self.ble.names(), ["gap_scan"])

    def test_disconnect_clears_ready_and_rescans(self):
        self.link_up()
        self.assertTrue(self.link.ready())

        self.ble.calls.clear()
        self.link._irq(_IRQ_PERIPHERAL_DISCONNECT, (_CONN, 0, _FAKE_ADDR))
        self.assertFalse(self.link.ready())

        self.tick()
        self.assertEqual(self.ble.names(), ["gap_scan"])

    def test_stale_scan_done_while_linked_is_ignored(self):
        self.link_up()
        self.ble.calls.clear()
        self.link._irq(_IRQ_SCAN_DONE, None)
        self.tick()
        self.assertTrue(self.link.ready())
        self.assertEqual(self.ble.names(), [])


class IrqDisciplineTests(_LinkFixture):
    """The IRQ handler records what happened and nothing else. Calling
    back into the BLE stack from inside its own callback is the kind of
    thing that works on the bench and then wedges in the field."""

    def test_no_irq_event_calls_into_the_stack(self):
        self.tick()
        payload = _advertising_payload_for(config.BLE_SERVICE_UUID)
        events = [
            (_IRQ_SCAN_RESULT, (0, _FAKE_ADDR, _ADV_IND, -50, payload)),
            (_IRQ_SCAN_DONE, None),
            (_IRQ_PERIPHERAL_CONNECT, (_CONN, 0, _FAKE_ADDR)),
            (_IRQ_GATTC_SERVICE_RESULT, (_CONN, 10, 20, self.link._target_service)),
            (_IRQ_GATTC_SERVICE_DONE, (_CONN, 0)),
            (_IRQ_GATTC_CHARACTERISTIC_RESULT,
             (_CONN, 11, 12, 0x0C, self.link._target_char)),
            (_IRQ_GATTC_CHARACTERISTIC_DONE, (_CONN, 0)),
            (_IRQ_PERIPHERAL_DISCONNECT, (_CONN, 0, _FAKE_ADDR)),
        ]
        for event, data in events:
            self.ble.calls.clear()
            self.link._irq(event, data)
            self.assertEqual(self.ble.names(), [],
                             "IRQ %d called into the BLE stack" % event)


class WriteTests(_LinkFixture):
    def test_write_before_ready_sends_nothing(self):
        self.assertFalse(self.link.write(b"\x01"))
        self.assertNotIn("gattc_write", self.ble.names())

    def test_write_once_ready_goes_out_unacknowledged(self):
        self.link_up()
        self.ble.calls.clear()

        self.assertTrue(self.link.write(b"\x01"))
        (name, args), = self.ble.calls
        self.assertEqual(name, "gattc_write")
        conn, value_handle, data, mode = args
        self.assertEqual(conn, _CONN)
        self.assertEqual(value_handle, 12)
        self.assertEqual(data, b"\x01")
        self.assertEqual(mode, _WRITE_NO_RESPONSE)

    def test_a_stream_of_writes_all_go_out(self):
        """The old write-with-response mode could only have one request
        outstanding, so a 50Hz stream died after the first packet."""
        self.link_up()
        self.ble.calls.clear()
        for _ in range(50):
            self.assertTrue(self.link.write(b"\x01"))
        self.assertEqual(len(self.ble.calls), 50)

    def test_a_refused_write_is_swallowed_not_raised(self):
        """A full stack buffer must not be able to kill the send loop --
        the next packet is 20ms away."""
        self.link_up()
        self.ble.write_error = OSError(12)  # ENOMEM
        self.assertFalse(self.link.write(b"\x01"))
        self.assertTrue(self.link.ready())  # still linked, just dropped one


class TimeoutTests(_LinkFixture):
    """Every wait has a deadline. Before, a connect that never completed
    or a receiver missing the control characteristic left the
    transmitter blinking at nothing forever."""

    def test_a_connect_that_never_completes_starts_over(self):
        self.tick()
        self.see_receiver()
        self.tick()
        self.link._irq(_IRQ_SCAN_DONE, None)
        self.tick()                      # gap_connect issued
        self.assertIn("gap_connect", self.ble.names())

        self.ble.calls.clear()
        self.tick(config.CONNECT_TIMEOUT_MS + 1)   # ...and never connects
        self.tick()
        self.assertIn("gap_scan", self.ble.names())
        self.assertFalse(self.link.ready())

    def test_a_scan_that_never_reports_back_starts_over(self):
        self.tick()
        self.ble.calls.clear()
        self.tick(config.SCAN_TIMEOUT_MS + 3001)
        self.tick()
        self.assertIn("gap_scan", self.ble.names())

    def test_wrong_device_without_our_service_is_dropped(self):
        self.tick()
        self.see_receiver()
        self.tick()
        self.link._irq(_IRQ_SCAN_DONE, None)
        self.tick()
        self.link._irq(_IRQ_PERIPHERAL_CONNECT, (_CONN, 0, _FAKE_ADDR))
        self.tick()

        self.ble.calls.clear()
        self.link._irq(_IRQ_GATTC_SERVICE_DONE, (_CONN, 0))  # no service result first
        self.tick()
        self.assertIn("gap_disconnect", self.ble.names())
        self.assertFalse(self.link.ready())

        self.tick()
        self.assertIn("gap_scan", self.ble.names())

    def test_missing_control_characteristic_is_dropped(self):
        self.tick()
        self.see_receiver()
        self.tick()
        self.link._irq(_IRQ_SCAN_DONE, None)
        self.tick()
        self.link._irq(_IRQ_PERIPHERAL_CONNECT, (_CONN, 0, _FAKE_ADDR))
        self.tick()
        self.link._irq(_IRQ_GATTC_SERVICE_RESULT,
                       (_CONN, 10, 20, self.link._target_service))
        self.link._irq(_IRQ_GATTC_SERVICE_DONE, (_CONN, 0))
        self.tick()

        self.ble.calls.clear()
        self.link._irq(_IRQ_GATTC_CHARACTERISTIC_DONE, (_CONN, 0))  # never found it
        self.tick()
        self.assertFalse(self.link.ready())
        self.assertIn("gap_disconnect", self.ble.names())

    def test_a_ready_link_is_never_timed_out(self):
        self.link_up()
        self.ble.calls.clear()
        self.tick(config.CONNECT_TIMEOUT_MS * 100)
        self.assertTrue(self.link.ready())
        self.assertEqual(self.ble.names(), [])

    def test_a_dropped_link_recovers_even_if_the_rescan_request_is_lost(self):
        """The IRQ can set _pending in the narrow window where tick() has
        just taken it, which would swallow the rescan. Simulated here by
        clearing _pending straight after the disconnect."""
        self.link_up()
        self.link._irq(_IRQ_PERIPHERAL_DISCONNECT, (_CONN, 0, _FAKE_ADDR))
        self.link._pending = 0        # the lost request

        self.ble.calls.clear()
        self.tick()
        self.tick()
        self.assertIn("gap_scan", self.ble.names())


if __name__ == "__main__":
    unittest.main()
