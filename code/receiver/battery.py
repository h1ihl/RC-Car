"""
battery.py -- pack voltage through the external divider on GP26.

Lifted from the bench bring-up script, unchanged.
"""

from machine import Pin, ADC
import time

import config


class Battery:
    def __init__(self, gp=None, ratio=None, vref=None):
        self.adc = ADC(Pin(gp if gp is not None else config.BATT_ADC_GP))
        self.ratio = ratio if ratio is not None else config.BATT_DIV_RATIO
        self.vref = vref if vref is not None else config.BATT_ADC_VREF

    def volts(self, samples=32):
        total = 0
        for _ in range(samples):
            total += self.adc.read_u16()
            time.sleep_us(200)
        return (total / samples) * self.vref / 65535.0 * self.ratio
