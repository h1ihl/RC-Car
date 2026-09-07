"""
main.py -- transmitter entry point.

Calibrates the joysticks, then loops at ~50Hz reading them, encoding a
control packet, and sending it to the receiver over BLE. Also drives
the onboard LED so it's obvious at a glance whether this thing is
actually linked up: slow blink while scanning/reconnecting, solid once
it's linked and sending.

Flash this as main.py to have it run automatically on boot. While still
testing, run it with F5 from Thonny instead -- same reasoning as the
receiver side, you want Ctrl-C to be able to kill things instantly.
"""

import time
import bluetooth

import config
from joystick import JoystickAxis
from protocol import encode
from ble_link import TransmitterLink
from diagnostics import Diagnostics


def main():
    throttle_axis = JoystickAxis(config.PIN_THROTTLE_ADC, config.THROTTLE_INVERT)
    steering_axis = JoystickAxis(config.PIN_STEERING_ADC, config.STEERING_INVERT)

    print("Calibrating joysticks -- leave both sticks released...")
    throttle_axis.calibrate()
    steering_axis.calibrate()
    print("Calibrated. throttle centre=%d steering centre=%d" %
          (throttle_axis.center, steering_axis.center))

    link = TransmitterLink(bluetooth.BLE())
    diag = Diagnostics()

    seq = 0
    print("Transmitter up. Scanning for receiver.")

    try:
        while True:
            now = time.ticks_ms()

            # link.tick() is where the BLE stack actually gets driven --
            # scanning, connecting, discovery, and the timeouts that
            # restart any of those if they wedge. The IRQ only ever
            # records what happened; this is what acts on it.
            link.tick(now)

            if link.ready():
                packet = encode(throttle_axis.read(), steering_axis.read(), seq)
                # write() returns False if the packet didn't make it out.
                # Nothing to do about that here -- the next one is 20ms
                # away, and a stale control packet is worth less than the
                # fresh one behind it.
                link.write(packet)
                seq = (seq + 1) & 0xFFFF   # matches the protocol's 16-bit field

            diag.tick(now, link.ready())

            time.sleep_ms(config.LOOP_INTERVAL_MS)

    except KeyboardInterrupt:
        print("\ninterrupted")


if __name__ == "__main__":
    main()
