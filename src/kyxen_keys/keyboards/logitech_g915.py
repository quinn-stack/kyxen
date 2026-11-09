"""
Driver for the Logitech G915 LIGHTSPEED keyboard, connected by USB cable.

Same key matrix, G1–G5 and M1–M3 as the G815 (LED addresses are expected to
match, as Logitech uses the same zone IDs across this family), but a different
HID++ feature table (e.g. PerKeyLightingV2 at 0x0b instead of 0x10,
ONBOARD_PROFILES at 0x15 instead of 0x11) and HID++ on USB interface 2
instead of 1. The G815 driver resolves both at runtime, so this driver only
differs in its IDs and in not sending the G815-specific lighting init.

Not supported: the LIGHTSPEED receiver (046d:c541). Through the receiver the
keyboard is reached with HID++ device index 0x01 instead of 0xff, which the
rest of Kyxen does not handle yet.
"""
from __future__ import annotations

from .logitech_g815 import LogitechG815


class LogitechG915(LogitechG815):
    PRODUCT_IDS = [0xC33E]   # wired (USB cable) mode
    MODEL_NAME  = 'Logitech G915 LIGHTSPEED Wireless RGB Mechanical Gaming Keyboard'

    def lighting_init_packets(self) -> list[bytes]:
        return []
