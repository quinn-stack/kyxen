"""Auto-detection helpers — find evdev and hidraw paths for a keyboard model."""
from __future__ import annotations
import os
from pathlib import Path
from typing import Callable

import evdev


def find_evdev(
    vendor_id:  int,
    product_ids: list[int],
    is_right_interface: Callable[[evdev.InputDevice], bool],
) -> str | None:
    """
    Scan all /dev/input/event* devices and return the path of the one that
    matches vendor/product AND passes the is_right_interface check.
    """
    try:
        paths = evdev.list_devices()
    except Exception:
        return None

    for path in paths:
        try:
            dev = evdev.InputDevice(path)
        except Exception:
            continue
        if dev.info.vendor == vendor_id and dev.info.product in product_ids:
            if is_right_interface(dev):
                return path
    return None


def find_hidraw(vendor_id: int, product_ids: list[int]) -> str | None:
    """
    Scan /dev/hidraw* and return the path whose sysfs uevent matches
    the given vendor/product IDs.
    Format in uevent:  HID_ID=0003:0000046D:0000C33F
    """
    for i in range(32):
        hidraw_path = f'/dev/hidraw{i}'
        if not os.path.exists(hidraw_path):
            continue
        uevent = Path(f'/sys/class/hidraw/hidraw{i}/device/uevent')
        if not uevent.exists():
            continue
        try:
            for line in uevent.read_text().splitlines():
                if not line.startswith('HID_ID='):
                    continue
                parts = line.split('=', 1)[1].split(':')
                if len(parts) == 3:
                    vid = int(parts[1], 16)
                    pid = int(parts[2], 16)
                    if vid == vendor_id and pid in product_ids:
                        return hidraw_path
        except Exception:
            continue
    return None
