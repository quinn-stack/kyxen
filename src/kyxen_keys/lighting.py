"""
Logitech G815 keyboard lighting via HID++ 2.0 / hidraw.

Confirmed protocol (Wireshark captures + physical probe, May 2026):
  Init:    11 ff 09 0f 00... (software control mode)
           11 ff 03 2e 00... (software lighting mode)
  Set key: 11 ff 10 5e [key_id][key_id][R][G][B] 00...
  Commit:  11 ff 10 7e 00...

M-key indicators (M1/M2/M3) use a separate command:
  11 ff 0f 5e 01 03 [bitmask] 00...  (bit0=M1, bit1=M2, bit2=M3)
"""
from __future__ import annotations
import os
import select

# Key IDs — Logitech's internal LED matrix addresses (NOT USB HID scan codes).
# Letters are alphabetical: A=0x01 ... Z=0x1a
# Digits follow: 1=0x1b ... 0=0x24
# Source: g815_keymap.json (physical key-press confirmed via probe_mkeys.py)
KEY_IDS: dict[str, int] = {
    "ILLUMINATION":  0x99,
    "ESC":           0x26,
    "F1":  0x37, "F2":  0x38, "F3":  0x39, "F4":  0x3a,
    "F5":  0x3b, "F6":  0x3c, "F7":  0x3d, "F8":  0x3e,
    "F9":  0x3f, "F10": 0x40, "F11": 0x41, "F12": 0x42,
    "PRINT_SCREEN":  0x43,
    "SCROLL_LOCK":   0x44,
    "PAUSE":         0x45,
    "MEDIA_PREV":    0x9e,
    "PLAY_PAUSE":    0x9b,
    "MEDIA_NEXT":    0x9d,
    "MUTE":          0x9c,
    "G1": 0xb4, "G2": 0xb5, "G3": 0xb6, "G4": 0xb7, "G5": 0xb8,
    "BACKTICK":      0x32,
    "1":  0x1b, "2":  0x1c, "3":  0x1d, "4":  0x1e, "5":  0x1f,
    "6":  0x20, "7":  0x21, "8":  0x22, "9":  0x23, "0":  0x24,
    "MINUS":         0x2a,
    "EQUALS":        0x2b,
    "BACKSPACE":     0x27,
    "INSERT":        0x46,
    "HOME":          0x47,
    "PAGE_UP":       0x48,
    "NUM_LOCK":      0x50,
    "NUM_SLASH":     0x51,
    "NUM_STAR":      0x52,
    "NUM_MINUS":     0x53,
    "TAB":           0x28,
    "Q":  0x11, "W":  0x17, "E":  0x05, "R":  0x12, "T":  0x14,
    "Y":  0x19, "U":  0x15, "I":  0x09, "O":  0x0f, "P":  0x10,
    "L_BRACKET":     0x2c,
    "R_BRACKET":     0x2d,
    "RETURN":        0x25,
    "DELETE":        0x49,
    "END":           0x4a,
    "PAGE_DOWN":     0x4b,
    "NUM_7": 0x5c, "NUM_8": 0x5d, "NUM_9": 0x5e, "NUM_PLUS": 0x54,
    "CAPS_LOCK":     0x36,
    "A":  0x01, "S":  0x13, "D":  0x04, "F":  0x06, "G":  0x07,
    "H":  0x08, "J":  0x0a, "K":  0x0b, "L":  0x0c,
    "SEMICOLON":     0x30,
    "APOSTROPHE":    0x31,
    "HASH":          0x2f,
    "NUM_4": 0x59, "NUM_5": 0x5a, "NUM_6": 0x5b,
    "L_SHIFT":       0x69,
    "BACKSLASH":     0x61,
    "Z":  0x1a, "X":  0x18, "C":  0x03, "V":  0x16, "B":  0x02,
    "N":  0x0e, "M":  0x0d,
    "COMMA":         0x33,
    "PERIOD":        0x34,
    "R_SLASH":       0x35,
    "R_SHIFT":       0x6d,
    "UP":            0x4f,
    "NUM_1": 0x56, "NUM_2": 0x57, "NUM_3": 0x58, "NUM_ENTER": 0x55,
    "L_CTRL":        0x68,
    "L_SUPER":       0x6b,
    "L_ALT":         0x6a,
    "SPACE":         0x29,
    "R_ALT":         0x6e,
    "R_SUPER":       0x6f,
    "CONTEXT":       0x62,
    "R_CTRL":        0x6c,
    "LEFT":          0x4d,
    "DOWN":          0x4e,
    "RIGHT":         0x4c,
    "NUM_0":         0x5f,
    "NUM_PERIOD":    0x60,
    "LOGO":          0xd2,  # Logitech logo LED (NOT the MR key body — MR uses 0c 0e)
}

# Deduplicated LED addresses for full-keyboard sweeps (LOGO/MR share 0xd2)
_ALL_LEDS: tuple[int, ...] = tuple(dict.fromkeys(KEY_IDS.values()))


# ── HID++ transport ───────────────────────────────────────────────────────────

def _write(fd: int, data: bytes) -> None:
    os.write(fd, data + bytes(max(0, 20 - len(data))))


def _send(fd: int, data: bytes, timeout: float = 0.3) -> bytes | None:
    _write(fd, data)
    r, _, _ = select.select([fd], [], [], timeout)
    return os.read(fd, 64) if r else None


# ── Lighting primitives ───────────────────────────────────────────────────────

def _init_sw_mode(fd: int) -> None:
    _send(fd, bytes([0x11, 0xff, 0x09, 0x0f] + [0x00] * 16))  # software control
    _send(fd, bytes([0x11, 0xff, 0x03, 0x2e] + [0x00] * 16))  # software lighting mode


def _set_key(fd: int, key_id: int, r: int, g: int, b: int) -> None:
    p = bytearray(20)
    p[0], p[1], p[2], p[3] = 0x11, 0xff, 0x10, 0x5e
    p[4] = p[5] = key_id
    p[6], p[7], p[8] = r, g, b
    _write(fd, bytes(p))


def _commit(fd: int) -> None:
    _send(fd, bytes([0x11, 0xff, 0x10, 0x7e] + [0x00] * 16))


# ── Public API ────────────────────────────────────────────────────────────────

def apply_profile(hidraw_path: str, mode: str, colour: str) -> None:
    """Set all keys to a single colour. mode='off' forces black."""
    try:
        fd = os.open(hidraw_path, os.O_RDWR)
    except OSError as e:
        print(f'[lighting] cannot open {hidraw_path}: {e}')
        return
    try:
        r, g, b = _hex_to_rgb(colour)
        if mode == 'off':
            r = g = b = 0
        _init_sw_mode(fd)
        for key_id in _ALL_LEDS:
            _set_key(fd, key_id, r, g, b)
        _commit(fd)
    finally:
        os.close(fd)


def set_keys_colour(fd: int, key_colours: list[tuple[int, int, int, int]]) -> None:
    """Set per-key colours on an already-open fd. Call _commit(fd) after."""
    for key_id, r, g, b in key_colours:
        _set_key(fd, key_id, r, g, b)


def apply_mkey_indicators(hidraw_path: str, active_mkey: int | None,
                           colour: str = '') -> None:
    """
    Light the active M-key indicator LED (M1/M2/M3).
    active_mkey: 0-indexed (0=M1, 1=M2, 2=M3), or None to turn all off.
    colour is unused — M-key indicators are single-colour hardware LEDs.

    NOT IMPLEMENTED: Feature 0x8071 (M-key LED engine, HID++ idx 0x0f) requires
    a 60+ packet capability enumeration sequence (0f 0e queries) that GHub runs
    at connection time before the 0f 5e bitmask command has any effect. Without
    replicating that full init the command is silently ignored by the firmware.
    The keyboard auto-manages M-key LEDs based on physical key presses.
    """
    # No-op until the full 0x8071 capability init is implemented.


def _hex_to_rgb(hex_colour: str) -> tuple[int, int, int]:
    h = hex_colour.lstrip('#')
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
