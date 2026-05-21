#!/usr/bin/env python3
"""
G815 Lighting Probe — tests two HID++ command approaches from Wireshark captures.

Approach A (GHub-captured, 2026-05 Wireshark session):
  Set key:  11 ff 10 5e [key] [key] [R] [G] [B] 00...
  Commit:   11 ff 10 7e 00...
  Init:     09 0f (sw control) + 03 2e (sw lighting mode)

Approach B (probe_mkeys.py style, earlier research):
  Set key:  11 ff 10 1f [key] [R] [G] [B] ff 00...
  Commit:   11 ff 10 7f 00...
  Init:     08 3e + 08 1e + 0f 1e (direct mode)

Usage:
    python3 probe_lighting.py                 # auto-detect hidraw
    python3 probe_lighting.py /dev/hidraw7    # specify hidraw device
"""
from __future__ import annotations
import os
import sys
import select
import time

VENDOR  = 0x046D
PRODUCT = 0xC33F

# A small set of well-spread keys to test with — from confirmed key map
TEST_KEYS = {
    "ESC":   0x26,
    "W":     0x17,
    "A":     0x01,
    "S":     0x13,
    "D":     0x04,
    "SPACE": 0x29,
    "ENTER": 0x25,
}

COMMIT_A = bytes([0x11, 0xff, 0x10, 0x7e] + [0x00] * 16)
COMMIT_B = bytes([0x11, 0xff, 0x10, 0x7f] + [0x00] * 16)


# ── hidraw helpers ────────────────────────────────────────────────────────────

def _write(fd: int, payload: bytes) -> None:
    pkt = payload[:20] + bytes(max(0, 20 - len(payload)))
    os.write(fd, pkt)


def _send(fd: int, payload: bytes, timeout: float = 0.3) -> bytes | None:
    _write(fd, payload)
    r, _, _ = select.select([fd], [], [], timeout)
    if r:
        return os.read(fd, 64)
    return None


# ── Approach A — GHub / Wireshark captured ────────────────────────────────────

def init_a(fd: int) -> None:
    """Put keyboard into software-controlled lighting mode (GHub sequence)."""
    # Note: GHub sends a single-byte 0x01 wake on Windows via SET_REPORT.
    # On Linux hidraw, writes must be the full report size — skip the wake byte
    # and go straight to the HID++ init packets.
    _send(fd, bytes([0x11, 0xff, 0x09, 0x0f] + [0x00] * 16))  # sw control
    _send(fd, bytes([0x11, 0xff, 0x03, 0x2e] + [0x00] * 16))  # sw lighting


def set_key_a(fd: int, key_id: int, r: int, g: int, b: int) -> None:
    """Set key colour — GHub format (key repeated in bytes 4+5, RGB in 6+7+8)."""
    p = bytearray(20)
    p[0], p[1], p[2], p[3] = 0x11, 0xff, 0x10, 0x5e
    p[4] = p[5] = key_id
    p[6], p[7], p[8] = r, g, b
    _write(fd, bytes(p))


def commit_a(fd: int) -> None:
    _send(fd, COMMIT_A)


# ── Approach B — probe_mkeys / direct mode ────────────────────────────────────

def init_b(fd: int) -> None:
    """Enter direct/frame lighting mode (earlier probe_mkeys approach)."""
    _send(fd, bytes([0x11, 0xff, 0x08, 0x3e] + [0x00] * 16))
    _send(fd, bytes([0x11, 0xff, 0x08, 0x1e] + [0x00] * 16))
    _send(fd, bytes([0x11, 0xff, 0x0f, 0x1e, 0x00] + [0x00] * 14 + [0x01]))
    _send(fd, bytes([0x11, 0xff, 0x0f, 0x1e, 0x01] + [0x00] * 14 + [0x01]))


def set_key_b(fd: int, key_id: int, r: int, g: int, b: int) -> None:
    """Set key colour — direct mode format."""
    p = bytearray([0x11, 0xff, 0x10, 0x1f, key_id, r, g, b, 0xff])
    _write(fd, bytes(p))


def commit_b(fd: int) -> None:
    _send(fd, COMMIT_B)


# ── device detection ──────────────────────────────────────────────────────────

def find_g815_hidraw() -> list[str]:
    results = []
    for name in sorted(os.listdir('/sys/class/hidraw')):
        uevent = f'/sys/class/hidraw/{name}/device/uevent'
        try:
            text = open(uevent).read()
        except OSError:
            continue
        if f'{VENDOR:04X}'.upper() in text.upper() and f'{PRODUCT:04X}'.upper() in text.upper():
            results.append(f'/dev/{name}')
    return results


def hidraw_interface(path: str) -> str:
    """Return the USB interface string like '1-6:1.1' for a hidraw device."""
    import re
    name = os.path.basename(path)
    intf_link = f'/sys/class/hidraw/{name}/device'
    try:
        real = os.path.realpath(intf_link)
        # USB interface nodes look like "1-6:1.1" — digit(s)-digit(s):digit.digit
        for part in real.split('/'):
            if re.match(r'^\d+-[\d.]+:\d+\.\d+$', part):
                return part
    except Exception:
        pass
    return '?'


# ── probe runner ──────────────────────────────────────────────────────────────

def run_approach(label: str, hidraw: str, init_fn, set_fn, commit_fn) -> bool:
    print(f'\n── Approach {label} on {hidraw} ──')
    try:
        fd = os.open(hidraw, os.O_RDWR)
    except PermissionError:
        print(f'  Permission denied — run as root or add udev rule for {hidraw}')
        return False
    except OSError as e:
        print(f'  Cannot open: {e}')
        return False

    colors = {
        "W":     (255, 0,   0),
        "A":     (255, 0,   0),
        "S":     (255, 0,   0),
        "D":     (255, 0,   0),
        "ESC":   (0,   0,   255),
        "SPACE": (0,   255, 0),
        "ENTER": (255, 255, 255),
    }
    try:
        print('  Sending init...')
        init_fn(fd)

        print('  Lighting test keys (WASD=red, ESC=blue, SPACE=green, ENTER=white)...')
        for name, (r, g, b) in colors.items():
            set_fn(fd, TEST_KEYS[name], r, g, b)
        commit_fn(fd)

        answer = input('  Do you see the keys lit? (y/n/skip): ').strip().lower()
        if answer == 'y':
            print('  ✓ Approach works!')
            return True
        elif answer == 'skip':
            return False
        else:
            print('  ✗ No visible lighting.')
            return False
    finally:
        # Turn off all test keys before closing
        for name in colors:
            set_fn(fd, TEST_KEYS[name], 0, 0, 0)
        commit_fn(fd)
        time.sleep(0.1)
        os.close(fd)


def main() -> None:
    if len(sys.argv) > 1:
        hidraw_devices = [sys.argv[1]]
    else:
        hidraw_devices = find_g815_hidraw()

    if not hidraw_devices:
        print('No G815 hidraw devices found.')
        sys.exit(1)

    print('Found G815 hidraw devices:')
    for h in hidraw_devices:
        intf = hidraw_interface(h)
        print(f'  {h}  (USB interface {intf})')

    # Prefer interface X.1 (HID++ interface) — that's where M-key notifications come from
    # Interface X.0 is the boot/G-key protocol interface
    preferred = [h for h in hidraw_devices if hidraw_interface(h).endswith(':1.1')]
    fallback   = [h for h in hidraw_devices if h not in preferred]

    print(f'\nWill try interface 1.1 (HID++) first: {preferred}')
    print(f'Fallback interface 1.0:               {fallback}')
    print('\nMake sure no other software (G Hub, kyxend) is using the keyboard.')
    input('Press Enter to begin...')

    working = []
    for hidraw in preferred + fallback:
        intf = hidraw_interface(hidraw)
        for label, init_fn, set_fn, commit_fn in [
            ('A (GHub/Wireshark)', init_a, set_key_a, commit_a),
            ('B (direct mode)',    init_b, set_key_b, commit_b),
        ]:
            ok = run_approach(f'{label} [{intf}]', hidraw, init_fn, set_fn, commit_fn)
            if ok:
                working.append((hidraw, label))

    print('\n── Results ──')
    if working:
        for hidraw, label in working:
            print(f'  ✓ {hidraw}  Approach {label}')
        h, l = working[0]
        print(f'\nRecommended: use {h} with approach {l}')
        print(f'  (hidraw interface: {hidraw_interface(h)})')
    else:
        print('  No approach worked.')
        print('  Check: is kyxend running? try stopping it first.')
        print('  Check: udev permissions — ls -la /dev/hidraw5 /dev/hidraw7')


if __name__ == '__main__':
    main()
