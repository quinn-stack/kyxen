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


_HIDPP_VENDOR_PAGE = 0xFF00   # Logitech vendor usage page carrying HID++
_HIDPP_LONG_ID     = 0x11     # HID++ long report (20 bytes)


def is_hidpp_descriptor(desc: bytes) -> bool:
    """
    Return True if a HID report descriptor declares the HID++ long report
    (report ID 0x11) on the Logitech vendor usage page 0xFF00.

    Walks the short items of the descriptor: Usage Page (global tag 0x04) and
    Report ID (global tag 0x84). Long items (prefix 0xFE) are skipped.
    """
    usage_page = 0
    i = 0
    while i < len(desc):
        prefix = desc[i]
        if prefix == 0xFE:                      # long item: FE <size> <tag> <data>
            if i + 1 >= len(desc):
                break
            i += 3 + desc[i + 1]
            continue
        size = (0, 1, 2, 4)[prefix & 0x03]
        data = desc[i + 1:i + 1 + size]
        value = int.from_bytes(data, 'little') if data else 0
        tag = prefix & 0xFC
        if tag == 0x04:
            usage_page = value
        elif tag == 0x84 and value == _HIDPP_LONG_ID and usage_page == _HIDPP_VENDOR_PAGE:
            return True
        i += 1 + size
    return False


def find_hidpp_hidraw(vendor_id: int, product_ids: list[int]) -> str | None:
    """
    Return the hidraw node that carries HID++ for the given keyboard, chosen
    by report descriptor rather than by interface order. The G815 exposes
    HID++ on USB interface 1, the G915 (wired) on interface 2.
    """
    for i in range(64):
        hidraw_path = f'/dev/hidraw{i}'
        sys_dir = Path(f'/sys/class/hidraw/hidraw{i}/device')
        if not os.path.exists(hidraw_path) or not _ids_match(sys_dir, vendor_id, product_ids):
            continue
        try:
            desc = (sys_dir / 'report_descriptor').read_bytes()
        except OSError:
            continue
        if is_hidpp_descriptor(desc):
            return hidraw_path
    return None


def _ids_match(sys_dir: Path, vendor_id: int, product_ids: list[int]) -> bool:
    try:
        for line in (sys_dir / 'uevent').read_text().splitlines():
            if line.startswith('HID_ID='):
                parts = line.split('=', 1)[1].split(':')
                return (len(parts) == 3
                        and int(parts[1], 16) == vendor_id
                        and int(parts[2], 16) in product_ids)
    except (OSError, ValueError):
        pass
    return False


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
