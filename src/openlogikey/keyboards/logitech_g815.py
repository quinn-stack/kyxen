"""Driver for the Logitech G815 RGB Mechanical Gaming Keyboard."""
from __future__ import annotations
from evdev import ecodes
import evdev as evdev_lib

from .base import LogitechKeyboard, DevicePaths


class LogitechG815(LogitechKeyboard):
    PRODUCT_IDS = [0xC33F]
    MODEL_NAME  = 'Logitech G815 RGB Mechanical Gaming Keyboard'
    GKEY_COUNT  = 5

    @classmethod
    def gkey_map(cls) -> dict[int, str]:
        return {
            ecodes.KEY_F1: 'g1',
            ecodes.KEY_F2: 'g2',
            ecodes.KEY_F3: 'g3',
            ecodes.KEY_F4: 'g4',
            ecodes.KEY_F5: 'g5',
        }

    @classmethod
    def _is_gkey_interface(cls, device: evdev_lib.InputDevice) -> bool:
        name = device.name
        return not any(name.endswith(s) for s in
                       (' Keyboard', ' Mouse', ' Consumer Control', ' System Control'))

    def apply_lighting(self, mode: str, colour: str) -> None:
        if not self.paths.hidraw:
            return
        from .. import lighting
        lighting.apply_profile(self.paths.hidraw, mode, colour)
