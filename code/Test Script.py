"""
rc_bringup.py -- bench bring-up for phase 1

Pico WH running MicroPython, driving 2 TT gear motors through an
MD1.3 (L298N) dual H-bridge, plus an MG90S steering servo off the
5V rail. Everything's controlled by typing commands into the REPL.

Run this with F5 in Thonny instead of dropping it in as main.py while
testing -- need Ctrl-C to be able to kill things instantly.
"""

from machine import Pin, PWM, ADC
import time


# ---------------------------------------------------------------------
# config - change stuff here, not down in the code
# ---------------------------------------------------------------------

# MD1.3 pins. E = enable (PWM, speed), M = mode (direction)
PIN_M1_E = 16          # physical pin 21 -> MD1.3 E1
PIN_M1_M = 17          # physical pin 22 -> MD1.3 M1
PIN_M2_E = 18          # physical pin 24 -> MD1.3 E2
PIN_M2_M = 19          # physical pin 25 -> MD1.3 M2

PIN_SERVO = 15          # physical pin 20 -> MG90S signal (orange)

MOTOR_PWM_HZ = 1000     # 1kHz is fine for the L298N

# duty ceiling - keeps the 3-6V TT motors safe on the pack
#   7.2V pack - ~2V bridge drop = ~5.2V at the motor at full duty
#   already inside the 3-6V rating, so no ceiling needed now that
#   I'm on the 7.2V NiMH pack instead of the old 9V alkalines
MAX_DUTY = 1.0

# The motors are mounted mirrored, so "both wheels pushing the car
# forward" means the two channels run in opposite electrical directions.
# That's what M2_INVERT is doing here: without it, 'f' drove the two
# wheels against each other and it was 'sp' (counter-rotate) that
# actually moved the car. With it, 'f' is forward, 'b' is reverse, and
# 'sp' still spins the car on the spot -- every command means what it
# says. receiver/config.py carries the same flag for the same reason.
M1_INVERT = False
M2_INVERT = True

REVERSE_COAST_MS = 60

SERVO_HZ     = 50
SERVO_MIN_US = 1000     # narrow on purpose, widen after finding the
SERVO_MAX_US = 2000     # real endpoints with the 'us' command
SERVO_CENTRE = 90

# How far the steering is allowed to go once it's on the car: 45 degrees
# either side of centre, i.e. 1250us and 1750us in the mapping above.
# The 's' and 'us' commands deliberately still go anywhere inside the
# hard limits -- this is a bring-up tool and finding real endpoints is
# half its job -- but 'sw' sweeps this range, and receiver/config.py
# clamps to exactly these two numbers, so what gets swept here is what
# the car will actually do.
STEER_MIN_DEG = 45
STEER_MAX_DEG = 135

# the same two limits as pulse widths -- 1250us and 1750us
STEER_MIN_US = SERVO_MIN_US + (SERVO_MAX_US - SERVO_MIN_US) * STEER_MIN_DEG // 180
STEER_MAX_US = SERVO_MIN_US + (SERVO_MAX_US - SERVO_MIN_US) * STEER_MAX_DEG // 180

# battery voltage monitor, optional
BATT_ADC_GP    = 26     # divider's wired up on GP26
BATT_DIV_RATIO = 4.03   # (100k + 33k) / 33k
BATT_ADC_VREF  = 3.30

DEFAULT_DUTY = 0.30
DEFAULT_SECS = 2.0


# ---------------------------------------------------------------------
# drivers
# ---------------------------------------------------------------------

class Motor:
    """One channel of the MD1.3.

    E LOW          -> stopped (M doesn't matter)
    E HIGH, M LOW  -> forward
    E HIGH, M HIGH -> reverse
    E PWM          -> speed control
    """

    def __init__(self, en_gp, dir_gp, name, invert=False):
        self.name = name
        self.invert = invert
        self.en = PWM(Pin(en_gp))
        self.en.freq(MOTOR_PWM_HZ)
        self.en.duty_u16(0)
        self.dir = Pin(dir_gp, Pin.OUT, value=0)
        self.duty = 0.0

    def drive(self, duty):
        """duty: -1.0 (full reverse) .. 0 .. +1.0 (full forward)."""
        duty = max(-1.0, min(1.0, duty))
        cmd = -duty if self.invert else duty
        want_dir = 0 if cmd >= 0 else 1

        # don't slam a spinning motor straight into reverse - kill the
        # enable, coast for a bit, then flip direction
        if want_dir != self.dir.value() and self.duty != 0.0:
            self.en.duty_u16(0)
            time.sleep_ms(REVERSE_COAST_MS)

        self.dir.value(want_dir)
        self.en.duty_u16(int(abs(cmd) * MAX_DUTY * 65535))
        self.duty = duty

    def stop(self):
        self.en.duty_u16(0)
        self.duty = 0.0

    def deinit(self):
        self.stop()
        self.en.deinit()


class Servo:
    """MG90S on a 50Hz PWM channel.

    Starts detached - no pulses go out until I actually tell it to move,
    so it doesn't jump the second the script loads.
    """

    HARD_MIN_US = 500      # never go past these, no matter what
    HARD_MAX_US = 2500

    def __init__(self, gp, min_us=SERVO_MIN_US, max_us=SERVO_MAX_US):
        self.pwm = PWM(Pin(gp))
        self.pwm.freq(SERVO_HZ)
        self.period_us = 1000000 // SERVO_HZ
        self.min_us = min_us
        self.max_us = max_us
        self.angle = None
        self.us = None
        self.pwm.duty_u16(0)

    def write_us(self, us):
        """Sets a raw pulse width, returns what actually got applied."""
        us = max(self.HARD_MIN_US, min(self.HARD_MAX_US, int(us)))
        self.pwm.duty_u16(int(us * 65535 // self.period_us))
        self.us = us
        return us

    def write_angle(self, deg):
        deg = max(0.0, min(180.0, float(deg)))
        span = self.max_us - self.min_us
        us = self.min_us + span * deg / 180.0
        self.write_us(us)
        self.angle = deg
        return self.us

    def sweep(self, a, b, step=2, dwell_ms=15):
        a, b, step = int(a), int(b), int(step)
        rng = range(a, b + 1, step) if b >= a else range(a, b - 1, -step)
        for d in rng:
            self.write_angle(d)
            time.sleep_ms(dwell_ms)

    def detach(self):
        """Servo goes limp, stops buzzing/holding position."""
        self.pwm.duty_u16(0)
        self.angle = None
        self.us = None

    def deinit(self):
        self.detach()
        self.pwm.deinit()


class Battery:
    """Pack voltage through an external divider. Optional."""

    def __init__(self, gp, ratio, vref=BATT_ADC_VREF):
        self.adc = ADC(Pin(gp))
        self.ratio = ratio
        self.vref = vref

    def volts(self, samples=32):
        total = 0
        for _ in range(samples):
            total += self.adc.read_u16()
            time.sleep_us(200)
        return (total / samples) * self.vref / 65535.0 * self.ratio


# ---------------------------------------------------------------------
# console
# ---------------------------------------------------------------------

HELP = """
  MOTORS
    f  [duty] [secs]   both forward        e.g.  f 0.4 3
    b  [duty] [secs]   both reverse
    1  [duty] [secs]   M1 only             e.g.  1 0.3
    2  [duty] [secs]   M2 only
    sp [duty] [secs]   spin on the spot (counter-rotate the wheels)
    ramp               step duty up in 0.05 increments, find the deadband
    x                  STOP motors now
                       (motors mount mirrored -- M2_INVERT handles it,
                        so 'f' really is forward)

  SERVO
    s <deg>            angle 0-180         e.g.  s 60
    us <microseconds>  raw pulse width     e.g.  us 1500
    c                  centre (90 deg)
    sw                 sweep the steering limits, %(smin)d -> %(smax)d -> centre
    det                detach (stop pulsing, servo goes limp)
    sstall <us> [ms]   hold servo at a pulse width and log rail sag
                        (use just past your measured endpoint to stall it
                        deliberately - short holds only, servo already
                        died once to this)

  OTHER
    v                  read pack voltage (needs the optional divider)
    sag [duty] [secs]  drive both motors and log the voltage dip under load
    ?                  this help
    q                  stop everything and exit

  Defaults: duty %(duty).2f, run time %(secs).1f s.  Ctrl-C aborts anytime.
  Steering limits: %(smin)d-%(smax)d deg = %(umin)d-%(umax)d us, which is
  what the car itself is clamped to. 's' and 'us' are deliberately NOT
  limited to that -- they go anywhere inside the 500-2500us hard stops,
  since finding real endpoints by hand is half the point of this tool.
""" % {
    "duty": DEFAULT_DUTY,
    "secs": DEFAULT_SECS,
    "smin": STEER_MIN_DEG,
    "smax": STEER_MAX_DEG,
    "umin": STEER_MIN_US,
    "umax": STEER_MAX_US,
}


def _arg(args, i, default):
    try:
        return float(args[i])
    except (IndexError, ValueError):
        return default


def timed_drive(m1, m2, d1, d2, secs):
    """Runs both motors for a set time, always stops after even on error."""
    try:
        m1.drive(d1)
        m2.drive(d2)
        time.sleep(secs)
    finally:
        m1.stop()
        m2.stop()


def find_deadband(m1, m2):
    """Ramps duty up slowly - watch for where each motor actually starts."""
    print("Ramping. Note the duty at which each motor actually begins to turn.")
    d = 0.05
    try:
        while d <= 1.001:
            print("  duty %.2f  (~%.2f after the %.2f ceiling)" %
                  (d, d * MAX_DUTY, MAX_DUTY))
            m1.drive(d)
            m2.drive(d)
            time.sleep(1.2)
            d += 0.05
    finally:
        m1.stop()
        m2.stop()
        print("Ramp finished, motors stopped.")


def track_sag(m1, m2, batt, duty=DEFAULT_DUTY, secs=DEFAULT_SECS, sample_interval_ms=20):
    """Drives both motors and watches pack voltage the whole time, reports the worst dip."""
    idle_v = batt.volts()
    print("idle: %.2f V" % idle_v)

    min_v = idle_v
    samples = max(1, int(secs * 1000 / sample_interval_ms))
    try:
        m1.drive(duty)
        m2.drive(duty)
        for _ in range(samples):
            v = batt.volts(samples=4)
            if v < min_v:
                min_v = v
            time.sleep_ms(sample_interval_ms)
    finally:
        m1.stop()
        m2.stop()

    sag = idle_v - min_v
    print("min under load: %.2f V" % min_v)
    print("sag: %.2f V" % sag)
    return idle_v, min_v, sag


def track_servo_sag(srv, batt, target_us, hold_ms=250, sample_ms=5):
    """Commands the servo hard (ideally against a stall) and watches the
    rail for the duration of the hold. Not fast enough to catch the initial
    current transient (~ms timescale) - that needs a scope. What this does
    catch is sustained stall draw, which is what actually matters for
    verifying the cap fix holds under a fault condition.

    Detaches the servo immediately after regardless of outcome. Don't run
    this many times in a row - a couple of short holds is enough, then
    let the servo cool and feel for heat.
    """
    idle_v = batt.volts()
    print("idle: %.2f V" % idle_v)

    min_v = idle_v
    t0 = time.ticks_ms()
    srv.write_us(target_us)
    try:
        while time.ticks_diff(time.ticks_ms(), t0) < hold_ms:
            v = batt.volts(samples=2)
            if v < min_v:
                min_v = v
            time.sleep_ms(sample_ms)
    finally:
        srv.detach()

    sag = idle_v - min_v
    print("min under stall: %.2f V" % min_v)
    print("sag: %.2f V" % sag)
    return idle_v, min_v, sag


def main():
    m1 = Motor(PIN_M1_E, PIN_M1_M, "M1", M1_INVERT)
    m2 = Motor(PIN_M2_E, PIN_M2_M, "M2", M2_INVERT)
    srv = Servo(PIN_SERVO)
    batt = Battery(BATT_ADC_GP, BATT_DIV_RATIO) if BATT_ADC_GP is not None else None

    print("Bring-up console ready.")
    print("Motors idle, servo detached, duty ceiling %.2f." % MAX_DUTY)
    print(HELP)

    try:
        while True:
            try:
                raw = input("> ").strip().lower()
            except EOFError:
                break
            if not raw:
                continue

            parts = raw.split()
            cmd, args = parts[0], parts[1:]

            # motors
            if cmd == "x":
                m1.stop()
                m2.stop()
                print("motors stopped")

            elif cmd in ("f", "b"):
                d = _arg(args, 0, DEFAULT_DUTY) * (1 if cmd == "f" else -1)
                t = _arg(args, 1, DEFAULT_SECS)
                print("both motors %s, duty %.2f, %.1f s" %
                      ("forward" if cmd == "f" else "reverse", abs(d), t))
                timed_drive(m1, m2, d, d, t)
                print("stopped")

            elif cmd in ("1", "2"):
                d = _arg(args, 0, DEFAULT_DUTY)
                t = _arg(args, 1, DEFAULT_SECS)
                print("M%s forward, duty %.2f, %.1f s" % (cmd, d, t))
                if cmd == "1":
                    timed_drive(m1, m2, d, 0.0, t)
                else:
                    timed_drive(m1, m2, 0.0, d, t)
                print("stopped")

            elif cmd == "sp":
                d = _arg(args, 0, DEFAULT_DUTY)
                t = _arg(args, 1, DEFAULT_SECS)
                print("counter-rotate, duty %.2f, %.1f s" % (d, t))
                timed_drive(m1, m2, d, -d, t)
                print("stopped")

            elif cmd == "ramp":
                find_deadband(m1, m2)

            # servo
            elif cmd == "s":
                deg = _arg(args, 0, SERVO_CENTRE)
                us = srv.write_angle(deg)
                print("servo -> %.0f deg  (%d us)" % (deg, us))

            elif cmd == "us":
                us = srv.write_us(_arg(args, 0, 1500))
                print("servo -> %d us raw" % us)

            elif cmd == "c":
                us = srv.write_angle(SERVO_CENTRE)
                print("servo -> centre (%d us)" % us)

            elif cmd == "sw":
                # sweeps the real steering limits, not an arbitrary
                # narrower range -- the point of this command is seeing
                # exactly how far the linkage travels in service
                print("sweeping %d -> %d deg (%d -> %d us)..." %
                      (STEER_MIN_DEG, STEER_MAX_DEG, STEER_MIN_US, STEER_MAX_US))
                srv.write_angle(SERVO_CENTRE)
                time.sleep_ms(400)
                srv.sweep(SERVO_CENTRE, STEER_MIN_DEG)
                time.sleep_ms(300)
                srv.sweep(STEER_MIN_DEG, STEER_MAX_DEG)
                time.sleep_ms(300)
                srv.sweep(STEER_MAX_DEG, SERVO_CENTRE)
                print("sweep done, holding centre")

            elif cmd == "det":
                srv.detach()
                print("servo detached")

            elif cmd == "sstall":
                if batt is None:
                    print("no divider configured -- set BATT_ADC_GP = 26")
                elif not args:
                    print("need a pulse width, e.g. sstall 2400")
                else:
                    us = _arg(args, 0, srv.us if srv.us else SERVO_MIN_US)
                    ms = _arg(args, 1, 250)
                    print("holding servo at %d us for %d ms" % (int(us), int(ms)))
                    track_servo_sag(srv, batt, int(us), hold_ms=int(ms))

            # misc
            elif cmd == "v":
                if batt is None:
                    print("no divider configured -- set BATT_ADC_GP = 26")
                else:
                    print("pack: %.2f V" % batt.volts())

            elif cmd == "sag":
                if batt is None:
                    print("no divider configured -- set BATT_ADC_GP = 26")
                else:
                    d = _arg(args, 0, DEFAULT_DUTY)
                    t = _arg(args, 1, DEFAULT_SECS)
                    track_sag(m1, m2, batt, d, t)

            elif cmd == "?":
                print(HELP)

            elif cmd == "q":
                break

            else:
                print("unknown command '%s'  --  type ? for help" % cmd)

    except KeyboardInterrupt:
        print("\ninterrupted")

    finally:
        m1.deinit()
        m2.deinit()
        srv.deinit()
        print("All outputs safe. Motors off, servo detached.")


if __name__ == "__main__":
    main()