"""Driver for the Logitech G15 Gaming Keyboard (v1, 2005)."""
from __future__ import annotations
import evdev as evdev_lib
from evdev import ecodes

from .base import LogitechKeyboard, DevicePaths


class LogitechG15(LogitechKeyboard):
    PRODUCT_IDS = [0xc221, 0xC222]
    MODEL_NAME = 'Logitech G15 Gaming Keyboard'
    GKEY_COUNT = 18

    # G1–G18 emit KEY_MACRO1 (656) – KEY_MACRO18 (673) directly as evdev events.
    # No hidraw boot-protocol reading or onboard profile remap required.
    EVDEV_GKEY_MAP: dict[int, str] = {167 + i: f'g{i + 1}' for i in range(18)}

    @classmethod
    def detect(cls) -> 'LogitechG15 | None':
        import evdev
        # g15daemon creates a virtual device called "G15 Extra Keys"
        for path in evdev.list_devices():
            try:
                dev = evdev.InputDevice(path)
                if dev.name == 'G15 Extra Keys':
                    print(f'[kyxen] found g15daemon virtual device: {path}')
                    return cls(DevicePaths(evdev=path, hidraw=''))
            except Exception:
                continue
        return None

    @classmethod
    def _is_gkey_interface(cls, device: evdev_lib.InputDevice) -> bool:
        return device.name == 'G15 Extra Keys'


    def apply_lighting(self, mode: str, colour: str, active_mkey: int | None = None) -> None:
        # G15 v1 uses a single-colour amber backlight; no programmatic RGB control.
        pass
