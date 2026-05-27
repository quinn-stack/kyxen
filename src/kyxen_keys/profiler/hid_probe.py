"""
Low-level HID++ helpers for the keyboard profiler.

These functions talk directly to a hidraw device to light individual LEDs
so the user can identify which LED address corresponds to which physical key.

Must be run with the kyxen-daemon stopped (otherwise it holds the hidraw
device in software-control mode and this probe can't reliably take over).
"""
from __future__ import annotations
import glob
import os
import re
import select


def find_logitech_hidraw() -> list[tuple[str, int, int]]:
    """Return (path, vid, pid) for every Logitech hidraw device found."""
    results: list[tuple[str, int, int]] = []
    for path in sorted(glob.glob('/dev/hidraw*')):
        try:
            name = os.path.basename(path)
            uevent = f'/sys/class/hidraw/{name}/device/uevent'
            with open(uevent) as f:
                text = f.read()
            m = re.search(r'HID_ID=\w+:(\w+):(\w+)', text)
            if not m:
                continue
            vid = int(m.group(1), 16)
            pid = int(m.group(2), 16)
            if vid == 0x046D:   # Logitech
                results.append((path, vid, pid))
        except Exception:
            pass
    return results


def open_hidraw(path: str) -> int:
    return os.open(path, os.O_RDWR | os.O_NONBLOCK)


def _write20(fd: int, data: bytes) -> None:
    os.write(fd, data + bytes(max(0, 20 - len(data))))


def drain(fd: int, timeout: float = 0.15) -> None:
    while True:
        r, _, _ = select.select([fd], [], [], timeout)
        if not r:
            break
        os.read(fd, 64)


def init_software_mode(fd: int) -> None:
    """Put keyboard in per-key software lighting mode."""
    _write20(fd, bytes([0x11, 0xff, 0x09, 0x0f]))
    drain(fd)
    _write20(fd, bytes([0x11, 0xff, 0x03, 0x2e]))
    drain(fd)


_COMMIT = bytes([0x11, 0xff, 0x10, 0x7e]) + bytes(16)


def set_all_black(fd: int) -> None:
    """Write black to all possible LED IDs 0x01-0xFF and commit."""
    p = bytearray(20)
    p[0], p[1], p[2], p[3] = 0x11, 0xff, 0x10, 0x5e
    for base in range(0x01, 0x100, 3):
        p[4:20] = b'\x00' * 16
        for slot, led_id in enumerate(range(base, min(base + 3, 0x100))):
            off = 4 + slot * 5
            p[off] = p[off + 1] = led_id
            # r, g, b = 0, 0, 0 (already zero from memset above)
        os.write(fd, bytes(p))
    os.write(fd, _COMMIT)


def light_single_led(
    fd: int,
    led_id: int,
    r: int = 255,
    g: int = 255,
    b: int = 255,
) -> None:
    """Set one LED to (r, g, b) and commit. Other LEDs are not changed."""
    p = bytearray(20)
    p[0], p[1], p[2], p[3] = 0x11, 0xff, 0x10, 0x5e
    p[4] = p[5] = led_id
    p[6], p[7], p[8] = r, g, b
    os.write(fd, bytes(p))
    os.write(fd, _COMMIT)
