"""
rc_bringup.py -- Phase 1 bench bring-up

Target  : Raspberry Pi Pico WH, MicroPython (Pico W firmware build)
Drives  : 2x TT gear motor via DFRobot MD1.3 (L298N) dual H-bridge
          1x MG90S steering servo fed from an L7805 5 V rail
Control : interactive commands typed into the USB serial REPL

Run this from Thonny (F5) rather than saving it as main.py while you are
still testing -- you want Ctrl-C to be able to kill everything instantly.
"""

from machine import Pin, PWM, ADC
import time


# =====================================================================
# CONFIGURATION  -- edit here, not in the code below
# =====================================================================

# --- MD1.3 control pins ---------------------------------------------
# E = Enable (PWM -> speed),  M = Mode (logic level -> direction)
PIN_M1_E = 16          # Pico physical pin 21  ->  MD1.3 E1
PIN_M1_M = 17          # Pico physical pin 22  ->  MD1.3 M1
PIN_M2_E = 18          # Pico physical pin 24  ->  MD1.3 E2
PIN_M2_M = 19          # Pico physical pin 25  ->  MD1.3 M2

# --- Servo -----------------------------------------------------------
PIN_SERVO = 15         # Pico physical pin 20  ->  MG90S signal (orange)

# --- Motor PWM -------------------------------------------------------
MOTOR_PWM_HZ = 1000    # 1 kHz sits comfortably inside the L298N's range

# Duty ceiling. This is what protects the 3-6 V TT motors from a 9 V pack:
#   pack ~9.0 V  -  L298N bridge drop ~2.0 V  =  ~7.0 V at the motor at 100%
#   0.75 x 7.0 V = ~5.3 V effective  ->  inside the motor's 3-6 V rating
# Raise this toward 1.0 only after moving to the 7.2 V NiMH pack.
MAX_DUTY = 0.75

# The motors mount mirrored on the chassis. Flip these until 'f' goes forward.
M1_INVERT = False
M2_INVERT = False

# Coast time forced in before any direction reversal, milliseconds.
REVERSE_COAST_MS = 60

# --- MG90S servo timing ---------------------------------------------
SERVO_HZ     = 50
SERVO_MIN_US = 1000    # deliberately narrow. Widen only after finding the
SERVO_MAX_US = 2000    # real mechanical endpoints with the 'us' command.
SERVO_CENTRE = 90

# --- Optional pack-voltage monitor (guide section 9) -----------------
BATT_ADC_GP    = None  # set to 26 once the resistor divider is fitted
BATT_DIV_RATIO = 4.03  # (100k + 33k) / 33k
BATT_ADC_VREF  = 3.30

# --- Console defaults -------------------------------------------------
DEFAULT_DUTY = 0.30
DEFAULT_SECS = 2.0


# =====================================================================
# DRIVERS
# =====================================================================

class Motor:
    """One channel of the MD1.3.

    Truth table, straight out of the MD1.3 datasheet:

        E LOW            ->  stopped (M is don't-care)
        E HIGH, M LOW    ->  forward
        E HIGH, M HIGH   ->  reverse
        E PWM            ->  speed control
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

        # Never slam a spinning motor through zero into the other direction.
        # Kill the enable, let it coast, then flip the direction line.
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
    """MG90S on a 50 Hz PWM channel.

    Starts detached -- no pulses are emitted until you explicitly command a
    position, so nothing lurches the moment the script loads.
    """

    HARD_MIN_US = 500      # absolute guard rails. Never exceeded, ever.
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
        """Command a raw pulse width. Returns the value actually applied."""
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
        """Stop pulsing. The servo goes limp and stops holding or buzzing."""
        self.pwm.duty_u16(0)
        self.angle = None
        self.us = None

    def deinit(self):
        self.detach()
        self.pwm.deinit()


class Battery:
    """Pack voltage via an external divider. Optional -- see guide section 9."""

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


# =====================================================================
# CONSOLE
# =====================================================================

HELP = """
  MOTORS
    f  [duty] [secs]   both forward        e.g.  f 0.4 3
    b  [duty] [secs]   both reverse
    1  [duty] [secs]   M1 only             e.g.  1 0.3
    2  [duty] [secs]   M2 only
    sp [duty] [secs]   counter-rotate (M1 fwd, M2 rev)
    ramp               step duty up in 0.05 increments, find the deadband
    x                  STOP motors now

  SERVO
    s <deg>            angle 0-180         e.g.  s 60
    us <microseconds>  raw pulse width     e.g.  us 1500
    c                  centre (90 deg)
    sw                 sweep 60 -> 120 -> centre
    det                detach (stop pulsing, servo goes limp)

  OTHER
    v                  read pack voltage (needs the optional divider)
    ?                  this help
    q                  stop everything and exit

  Defaults: duty %.2f, run time %.1f s.   Ctrl-C aborts at any time.
""" % (DEFAULT_DUTY, DEFAULT_SECS)


def _arg(args, i, default):
    try:
        return float(args[i])
    except (IndexError, ValueError):
        return default


def timed_drive(m1, m2, d1, d2, secs):
    """Run both channels for a fixed time, then guarantee a stop."""
    try:
        m1.drive(d1)
        m2.drive(d2)
        time.sleep(secs)
    finally:
        m1.stop()
        m2.stop()


def find_deadband(m1, m2):
    """Step the duty up slowly so you can note where each motor starts."""
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

            # ---- motors -------------------------------------------------
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

            # ---- servo --------------------------------------------------
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
                print("sweeping...")
                srv.write_angle(SERVO_CENTRE)
                time.sleep_ms(400)
                srv.sweep(SERVO_CENTRE, 60)
                time.sleep_ms(300)
                srv.sweep(60, 120)
                time.sleep_ms(300)
                srv.sweep(120, SERVO_CENTRE)
                print("sweep done, holding centre")

            elif cmd == "det":
                srv.detach()
                print("servo detached")

            # ---- misc ---------------------------------------------------
            elif cmd == "v":
                if batt is None:
                    print("no divider configured -- set BATT_ADC_GP = 26")
                else:
                    print("pack: %.2f V" % batt.volts())

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