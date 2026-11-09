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
        from .detect import find_evdev, find_hidraw, find_hidraw_for_evdev, find_hidpp_hidraw
        evdev_path = find_evdev(cls.VENDOR_ID, cls.PRODUCT_IDS, cls._is_gkey_interface)
        if evdev_path is None:
            return None
        # hidraw paired with the G-key evdev interface (boot protocol, input0)
        gkeys_hidraw = find_hidraw_for_evdev(evdev_path) or ''
        # hidraw carrying HID++ (lighting, onboard profiles, M-keys) — picked by
        # report descriptor, falling back to "the other interface".
        hidraw_path = (find_hidpp_hidraw(cls.VENDOR_ID, cls.PRODUCT_IDS)
                       or find_hidraw(cls.VENDOR_ID, cls.PRODUCT_IDS, exclude=gkeys_hidraw)
                       or gkeys_hidraw)
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
        from .. import onboard_profiles
        return onboard_profiles.ensure_gkey_remap(
            self.paths.hidraw,
            self.feature_index(onboard_profiles.FEATURE_ONBOARD_PROFILES),
        )

    def lighting_init_packets(self) -> list[bytes]:
        # Captured from G Hub on the G815 and addressed by fixed feature index.
        # Kept unchanged for the G815; other models must not inherit them, since
        # these indices point at different features there.
        from ..lighting_engine import G815_INIT_PACKETS
        return list(G815_INIT_PACKETS)

    def get_key_ids(self) -> dict[str, int]:
        from .. import lighting
        return lighting.KEY_IDS

    def apply_lighting(self, mode: str, colour: str, active_mkey: int | None = None) -> None:
        if not self.paths.hidraw:
            return
        from .. import lighting, onboard_profiles
        lighting.apply_profile(
            self.paths.hidraw, mode, colour,
            perkey_idx=self.feature_index(onboard_profiles.FEATURE_PER_KEY_LIGHTING),
            init_packets=self.lighting_init_packets(),
        )
        lighting.apply_mkey_indicators(self.paths.hidraw, active_mkey, colour)
