import unittest

import _mocks  # noqa: F401
from joystick import JoystickAxis, _scale


class ScaleTests(unittest.TestCase):
    """_scale is pure -- no ADC involved -- so the boundary math gets
    tested directly here."""

    def test_at_center_is_zero(self):
        self.assertEqual(_scale(32768, center=32768), 0.0)

    def test_full_scale_high_is_one(self):
        self.assertAlmostEqual(_scale(65535, center=32768), 1.0, places=3)

    def test_full_scale_low_is_minus_one(self):
        self.assertAlmostEqual(_scale(0, center=32768), -1.0, places=3)

    def test_asymmetric_center_still_reaches_the_extremes(self):
        # a stick that rests off dead-centre should still hit +/-1.0 at
        # its physical extremes, not stop short on the shorter side
        self.assertAlmostEqual(_scale(65535, center=40000), 1.0, places=3)
        self.assertAlmostEqual(_scale(0, center=40000), -1.0, places=3)

    def test_halfway_up_the_high_side(self):
        # center=0, so raw=32768 is exactly halfway to the 65535 ceiling
        self.assertAlmostEqual(_scale(32768, center=0), 0.5, places=3)

    def test_invert_flips_sign(self):
        self.assertAlmostEqual(_scale(65535, center=32768, invert=True), -1.0, places=3)
        self.assertAlmostEqual(_scale(0, center=32768, invert=True), 1.0, places=3)

    def test_clamped_to_the_valid_range(self):
        # center at an extreme means one whole side has zero span --
        # shouldn't divide by zero or blow past +/-1.0
        self.assertEqual(_scale(0, center=65535), -1.0)
        self.assertEqual(_scale(65535, center=65535), 0.0)
        self.assertEqual(_scale(0, center=0), 0.0)
        self.assertEqual(_scale(65535, center=0), 1.0)


class JoystickAxisTests(unittest.TestCase):
    def test_default_center_before_calibration(self):
        axis = JoystickAxis(adc_gp=26)
        self.assertEqual(axis.center, 32768)

    def test_calibrate_measures_rest_position(self):
        axis = JoystickAxis(adc_gp=26)
        axis.adc._value = 30000
        axis.calibrate(samples=8)
        self.assertEqual(axis.center, 30000)

    def test_read_after_calibration_is_zero_at_rest(self):
        axis = JoystickAxis(adc_gp=26)
        axis.adc._value = 31000
        axis.calibrate(samples=8)
        self.assertEqual(axis.read(), 0.0)

    def test_read_reflects_movement_off_calibrated_center(self):
        axis = JoystickAxis(adc_gp=26)
        axis.adc._value = 30000
        axis.calibrate(samples=8)
        axis.adc._value = 65535
        self.assertAlmostEqual(axis.read(), 1.0, places=3)

    def test_invert_applies_to_live_reads(self):
        axis = JoystickAxis(adc_gp=26, invert=True)
        axis.adc._value = 32768
        axis.calibrate(samples=8)
        axis.adc._value = 65535
        self.assertAlmostEqual(axis.read(), -1.0, places=3)


if __name__ == "__main__":
    unittest.main()
