"""Auto-detection helpers — find evdev and hidraw paths for a keyboard model."""
from __future__ import annotations
import os
from pathlib import Path
from typing import Callable

import evdev


def find_hidraw_for_evdev(evdev_path: str) -> str | None:
    """
    Find the hidraw device that shares the same HID interface as an evdev
    device by walking up the sysfs tree. Avoids returning a hidraw from a
    different USB interface on the same keyboard (e.g. main vs G-key).
    """
    event_name = os.path.basename(evdev_path)
    event_link = Path(f'/sys/class/input/{event_name}')
    if not event_link.exists():
        return None
    try:
        real_path = event_link.resolve()
    except Exception:
        return None
    current = real_path.parent
    while current != current.parent:
        hidraw_dir = current / 'hidraw'
        if hidraw_dir.exists():
            entries = sorted(hidraw_dir.iterdir())
            if entries:
                return f'/dev/{entries[0].name}'
        current = current.parent
    return None


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


def find_hidraw(vendor_id: int, product_ids: list[int], exclude: str = '') -> str | None:
    """
    Scan /dev/hidraw* and return the path whose sysfs uevent matches
    the given vendor/product IDs. Skips `exclude` if provided, so callers
    can request the *second* matching interface (e.g. HID++ vs boot protocol).
    Format in uevent:  HID_ID=0003:0000046D:0000C33F
    """
    for i in range(32):
        hidraw_path = f'/dev/hidraw{i}'
        if not os.path.exists(hidraw_path):
            continue
        if hidraw_path == exclude:
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
