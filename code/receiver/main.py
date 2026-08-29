"""
main.py -- receiver entry point.

Ties everything together: BLE link in, failsafe watchdog, throttle/
steering controllers out to the motors and servo. One loop, ~50Hz,
nothing in it blocks -- there's no delay()-style wait anywhere except
the reverse-coast handling buried inside motor.py, which is a real
"physically has to happen before reversing" delay, not a busy-wait.

Flash this as main.py to have it run automatically on boot. While still
testing, run it with F5 from Thonny instead (same reasoning as the bench
script -- you want Ctrl-C to be able to kill things instantly).
"""

import time
import bluetooth

import config
from motor import Motor
from servo import Servo
from battery import Battery
from throttle import ThrottleController
from steering import SteeringController
from ble_link import BLEReceiverLink
from protocol import decode
from failsafe import Failsafe
from diagnostics import Diagnostics


def main():
    m1 = Motor(config.PIN_M1_E, config.PIN_M1_M, "M1", config.M1_INVERT)
    m2 = Motor(config.PIN_M2_E, config.PIN_M2_M, "M2", config.M2_INVERT)
    srv = Servo(config.PIN_SERVO)
    batt = Battery()

    throttle = ThrottleController(m1, m2)
    steering = SteeringController(srv)
    failsafe = Failsafe()
    diag = Diagnostics(batt)

    link = BLEReceiverLink(bluetooth.BLE())

    print("Receiver up. Waiting for a valid packet before moving.")

    last_tick = time.ticks_ms()

    try:
        while True:
            now = time.ticks_ms()
            dt_s = time.ticks_diff(now, last_tick) / 1000.0
            last_tick = now

            if link.take_disconnect_event():
                failsafe.note_disconnect()

            raw = link.poll()
            if raw is not None:
                decoded = decode(raw)
                if decoded is not None:
                    t, s, _seq = decoded
                    failsafe.note_valid_packet(now)
                    throttle.set_from_joystick(t)
                    steering.set_from_joystick(s)
                # a bad packet just gets dropped -- doesn't touch the
                # failsafe timer, doesn't touch the last commanded values

            if failsafe.update(now):
                throttle.force_stop()
                steering.force_center()

            throttle.tick(dt_s)
            steering.tick(dt_s)

            diag.tick(now, link.is_connected(), failsafe.active,
                      throttle.current_duty, steering.current_deg)

            time.sleep_ms(config.LOOP_INTERVAL_MS)

    except KeyboardInterrupt:
        print("\ninterrupted")

    finally:
        throttle.stop_immediately()
        steering.stop_immediately()
        srv.deinit()
        m1.deinit()
        m2.deinit()
        print("All outputs safe. Motors off, servo centred.")


if __name__ == "__main__":
    main()
