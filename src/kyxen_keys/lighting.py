"""
Native G815 lighting control via hidraw.
Protocol reverse-engineered from OpenRGB source (GPL-2.0).

Zones:  keyboard=0x00  logo=0x01  media=0x02  gkeys=0x03  modifiers=0x04
Effects: off=0x00  static=0x01  breathing=0x02  cycle=0x03  wave=0x04  direct=0x05
"""
from __future__ import annotations
import os
import select

ZONE_ALL = (0x00, 0x01, 0x02, 0x03, 0x04)

MODE_MAP = {
    'off':       0x00,
    'static':    0x01,
    'breathing': 0x02,
    'cycle':     0x03,
    'wave':      0x04,
}


def _send(fd: int, data: bytes) -> bytes | None:
    pkt = data + bytes(20 - len(data))
    os.write(fd, pkt)
    r, _, _ = select.select([fd], [], [], 0.3)
    return os.read(fd, 64) if r else None


def apply_profile(hidraw_path: str, mode: str, colour: str) -> None:
    """Top-level call: open device, push colour/effect, close."""
    try:
        fd = os.open(hidraw_path, os.O_RDWR)
    except OSError as e:
        print(f'[lighting] cannot open {hidraw_path}: {e}')
        return
    try:
        r, g, b = _hex_to_rgb(colour)
        mode_id = MODE_MAP.get(mode, 0x01)
        for zone in ZONE_ALL:
            _set_zone_effect(fd, zone, mode_id, r, g, b)
    finally:
        os.close(fd)


def _set_zone_effect(fd: int, zone: int, mode: int,
                     r: int, g: int, b: int, speed: int = 0x32) -> None:
    _send(fd, bytes([
        0x11, 0xff, 0x0d, 0x3d,
        zone, mode, r, g, b,
        0x00, 0x00, (speed >> 8) & 0xff, speed & 0xff, 0x64,
        0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    ]))


def enter_direct_mode(fd: int) -> None:
    _send(fd, bytes([0x11, 0xff, 0x08, 0x3e]))
    _send(fd, bytes([0x11, 0xff, 0x08, 0x1e]))
    _send(fd, bytes([0x11, 0xff, 0x0f, 0x1e, 0x00, 0x00, 0x00, 0x00,
                     0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x01]))
    _send(fd, bytes([0x11, 0xff, 0x0f, 0x1e, 0x01, 0x00, 0x00, 0x00,
                     0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x01]))


def commit(fd: int) -> None:
    _send(fd, bytes([0x11, 0xff, 0x10, 0x7f]))


def set_keys_colour(fd: int, key_colours: list[tuple[int, int, int, int]]) -> None:
    """Per-key RGB in direct mode. key_colours: list of (keycode, r, g, b)."""
    from collections import defaultdict
    by_colour: dict[tuple, list[int]] = defaultdict(list)
    for kc, r, g, b in key_colours:
        by_colour[(r, g, b)].append(kc)

    for (r, g, b), keys in by_colour.items():
        for i in range(0, len(keys), 13):
            chunk = keys[i:i + 13]
            if len(chunk) > 4:
                pkt = bytearray([0x11, 0xff, 0x10, 0x6f, r, g, b])
                pkt.extend(chunk)
                if len(chunk) < 13:
                    pkt.append(0xff)
                _send(fd, bytes(pkt))
            else:
                pkt = bytearray([0x11, 0xff, 0x10, 0x1f])
                for kc in chunk:
                    pkt.extend([kc, r, g, b])
                if len(chunk) < 4:
                    pkt.append(0xff)
                _send(fd, bytes(pkt))


def _hex_to_rgb(hex_colour: str) -> tuple[int, int, int]:
    h = hex_colour.lstrip('#')
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
