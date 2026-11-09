"""
Driver for the Logitech G915 LIGHTSPEED keyboard, connected by USB cable.

Same key matrix, G1–G5, M1–M3 and LED addresses as the G815 (per-key lighting
confirmed on hardware), but:

- a different HID++ feature table (e.g. PerKeyLightingV2 at 0x0a instead of
  0x10, ONBOARD_PROFILES at 0x14 instead of 0x11) and HID++ on USB interface 2
  instead of 1. The G815 driver resolves both at runtime.
- no G815 lighting init packets (their fixed indices point elsewhere here).
- G-keys arrive as HID++ GKEY (0x8010) notifications once software mode is
  enabled, so no flash remap is needed: while Kyxen runs the G-keys produce no
  key codes at all, and without Kyxen they keep their onboard bindings.

Not supported: the LIGHTSPEED receiver (046d:c541). Through the receiver the
keyboard is reached with HID++ device index 0x01 instead of 0xff, which the
rest of Kyxen does not handle yet.
"""
from __future__ import annotations

from .logitech_g815 import LogitechG815


class LogitechG915(LogitechG815):
    PRODUCT_IDS = [0xC33E]   # wired (USB cable) mode
    MODEL_NAME  = 'Logitech G915 LIGHTSPEED Wireless RGB Mechanical Gaming Keyboard'

    GKEYS_VIA_HIDPP = True
    # Diverted G-keys emit no key codes; F1–F5 etc. are real keys here and
    # must reach applications.
    GKEY_SUPPRESS_CODES: frozenset[int] = frozenset()

    def ensure_gkey_remap(self) -> bool:
        return False   # G-keys are read via HID++; leave the onboard profiles alone

    def lighting_init_packets(self) -> list[bytes]:
        return []
