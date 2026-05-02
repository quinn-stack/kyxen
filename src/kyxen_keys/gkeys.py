"""
G-key event reader via USB HID boot-protocol reports.

The Logitech G-key hidraw interface sends standard 8-byte USB HID keyboard
reports. After the one-time onboard-profile remap written by onboard_profiles.py,
G1–G5 appear as HID usage codes 0x68–0x6c (F13–F17) — keys that do not exist
on the physical keyboard and cannot collide with any real key press.

Report format: [modifier, reserved, key1, key2, key3, key4, key5, key6]
Press = non-zero key slot. Release = all key slots 0x00.
"""
from __future__ import annotations
import os
import select
from collections.abc import Callable

_HID_TO_GKEY = {
    0x68: 'g1',
    0x69: 'g2',
    0x6a: 'g3',
    0x6b: 'g4',
    0x6c: 'g5',
}


def run_gkey_listener(
    hidraw_path: str,
    on_press: Callable[[str], None],
    stop_flag: Callable[[], bool],
    on_release: Callable[[str], None] | None = None,
) -> None:
    """
    Block until stop_flag() is True, calling on_press/on_release for each
    G-key event. Designed to run in a daemon thread.
    """
    try:
        fd = os.open(hidraw_path, os.O_RDWR | os.O_NONBLOCK)
    except OSError as e:
        print(f'[gkeys] cannot open {hidraw_path}: {e}')
        return

    prev_keys: set[int] = set()
    try:
        while not stop_flag():
            ready, _, _ = select.select([fd], [], [], 0.5)
            if not ready:
                continue
            try:
                data = os.read(fd, 64)
            except OSError:
                break
            if len(data) < 3:
                continue
            curr_keys = {b for b in data[2:8] if b != 0x00}
            for code in curr_keys - prev_keys:
                if code in _HID_TO_GKEY:
                    on_press(_HID_TO_GKEY[code])
            if on_release:
                for code in prev_keys - curr_keys:
                    if code in _HID_TO_GKEY:
                        on_release(_HID_TO_GKEY[code])
            prev_keys = curr_keys
    finally:
        os.close(fd)
