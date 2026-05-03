"""Driver for the Logitech G815 RGB Mechanical Gaming Keyboard."""
from __future__ import annotations
from evdev import ecodes
import evdev as evdev_lib

from .base import LogitechKeyboard, DevicePaths


class LogitechG815(LogitechKeyboard):
    PRODUCT_IDS        = [0xC33F]
    MODEL_NAME         = 'Logitech G815 RGB Mechanical Gaming Keyboard'
    GKEY_COUNT         = 5
    GKEYS_FEATURE_IDX  = None   # no usable HID++ G-key notifications on G815

    # ONBOARD_PROFILES feature (0x8100) — used to remap G-key codes in flash.
    # Feature index 0x11 confirmed from Windows USB capture.
    ONBOARD_PROFILES_FEATURE_IDX: int = 0x11
    ONBOARD_PROFILES_SECTOR:      int = 0x0101

    # After the one-time flash remap, G1–G5 emit F13–F17 on event12.
    # Suppress these so macros are driven by the hidraw boot-protocol reader,
    # not by evdev codes reaching the uinput passthrough.
    GKEY_SUPPRESS_CODES: frozenset[int] = frozenset({
        ecodes.KEY_F13,
        ecodes.KEY_F14,
        ecodes.KEY_F15,
        ecodes.KEY_F16,
        ecodes.KEY_F17,
    })

    @classmethod
    def detect(cls) -> 'LogitechG815 | None':
        from .detect import find_evdev, find_hidraw, find_hidraw_for_evdev
        evdev_path = find_evdev(cls.VENDOR_ID, cls.PRODUCT_IDS, cls._is_gkey_interface)
        if evdev_path is None:
            return None
        # hidraw paired with the G-key evdev interface (boot protocol, input0)
        gkeys_hidraw = find_hidraw_for_evdev(evdev_path) or ''
        # hidraw on the other interface (HID++ for lighting + software-mode notifications, input1)
        hidraw_path = find_hidraw(cls.VENDOR_ID, cls.PRODUCT_IDS, exclude=gkeys_hidraw) or gkeys_hidraw
        print(f'[kyxen] evdev:        {evdev_path}')
        print(f'[kyxen] hidraw:        {hidraw_path}')
        print(f'[kyxen] hidraw_gkeys:  {gkeys_hidraw}')
        return cls(DevicePaths(evdev=evdev_path, hidraw=hidraw_path, hidraw_gkeys=gkeys_hidraw))

    @classmethod
    def _is_gkey_interface(cls, device: evdev_lib.InputDevice) -> bool:
        name = device.name
        return not any(name.endswith(s) for s in
                       (' Keyboard', ' Mouse', ' Consumer Control', ' System Control'))

    def ensure_gkey_remap(self) -> bool:
        """Remap G1–G5 → F13–F17 in keyboard flash if not already done."""
        if not self.paths.hidraw:
            raise RuntimeError('no HID++ hidraw path available')
        from .. import onboard_profiles
        return onboard_profiles.ensure_gkey_remap(
            self.paths.hidraw,
            self.ONBOARD_PROFILES_FEATURE_IDX,
        )

    def apply_lighting(self, mode: str, colour: str, active_mkey: int | None = None) -> None:
        if not self.paths.hidraw:
            return
        from .. import lighting
        lighting.apply_profile(self.paths.hidraw, mode, colour)
        lighting.apply_mkey_indicators(self.paths.hidraw, active_mkey, colour)
