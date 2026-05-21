"""
G-key and M-key event readers.

G-key reader (run_gkey_listener)
---------------------------------
Reads from the G-key hidraw interface (USB interface 0, boot protocol, 8-byte
reports). After the one-time onboard-profile remap written by onboard_profiles.py,
G1–G5 appear as HID usage codes 0x68–0x6c (F13–F17) — keys that do not exist
on the physical keyboard and cannot collide with physical F-key presses.

Report format: [modifier, reserved, key1, key2, key3, key4, key5, key6]
Press = non-zero key slot. Release = all key slots 0x00.

M-key listener (run_mkey_listener)
------------------------------------
Reads from the HID++ hidraw interface (USB interface 1, hidraw9 on G815).
M-key presses arrive as HID++ LONG reports (20 bytes, report ID 0x11) on
feature 0x8020 (runtime index 0x0b on G815).

To receive notifications the keyboard must be put into software mode first.
This requires two HID++ commands sent on the SAME fd that will listen — the
keyboard tracks software mode per-connection and reverts when the fd closes:
  1. Feature 0x8010 (UUID), func=2, SW_ID=0xe, param=0x01
  2. Feature 0x8020 (UUID), func=1, SW_ID=0xe, param=0x01

Notification format:
  11 ff [feat_8020_idx] 00 [bitmask] 00 00 ... (20 bytes)
  bitmask: M1=0x01  M2=0x02  M3=0x04  release=0x00

Feature indices are runtime values looked up via get_feature_index() in
onboard_profiles.py. On the G815 they are 0x0a (0x8010) and 0x0b (0x8020)
but must not be hardcoded.
"""
from __future__ import annotations
import os
import queue as _queue_mod
import select
import time as _time
from collections.abc import Callable

_MKEY_BITMASK_TO_IDX   = {0x01: 0, 0x02: 1, 0x04: 2}
_BITMASK_TO_PROFILE_NUM = {0x01: 1, 0x02: 2, 0x04: 3}

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
        print(f'[gkeys] cannot open {hidraw_path} for G-key listener: {e}')
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


def run_mkey_listener(
    hidraw_path: str,
    feat_8010_idx: int,
    feat_8020_idx: int,
    feat_profiles_idx: int,
    on_mkey: Callable[[int], None],
    stop_flag: Callable[[], bool],
    led_queue: '_queue_mod.SimpleQueue[int] | None' = None,
) -> None:
    """
    Listen for M-key profile switch notifications on the HID++ interface.
    Calls on_mkey(0-based index) when M1/M2/M3 is pressed.
    Notification format: 11 ff [feat_8020_idx] 00 [bitmask] 00... — M1=0x01, M2=0x02, M3=0x04.
    Designed to run in a daemon thread.

    Startup sequence (confirmed May 2026):
      1. feat_profiles (0x8100) func=1: activate onboard profile 1 — required before SW enable.
      2. feat_8010 (0x8010) func=2: enable software mode for M-key notifications.
      3. led_queue: bitmask values (0x00=off, 0x01=M1, 0x02=M2, 0x04=M3) applied
         each loop iteration. Each LED change sends a profile activate (profile N for MN)
         followed 50ms later by 0b 1e [bitmask]. Both are required — 0b 1e alone does
         nothing unless the corresponding profile was just activated.
    """
    try:
        fd = os.open(hidraw_path, os.O_RDWR | os.O_NONBLOCK)
    except OSError as e:
        print(f'[gkeys] cannot open {hidraw_path} for M-key listener: {e}')
        return

    def _drain(timeout: float) -> None:
        while True:
            r, _, _ = select.select([fd], [], [], timeout)
            if not r:
                break
            os.read(fd, 64)

    try:
        # Activate onboard profile — unlocks M-key indicator LED control via 0x8020.
        os.write(fd, bytes([0x11, 0xff, feat_profiles_idx, 0x1e, 0x01]) + b'\x00' * 15)
        _drain(0.3)
        # Enable software mode so M-key presses generate 0x8020 notifications.
        os.write(fd, bytes([0x11, 0xff, feat_8010_idx, 0x2e, 0x01]) + b'\x00' * 15)
        _drain(0.4)

        while not stop_flag():
            # Drain LED queue — keep only the latest bitmask and apply it.
            if led_queue is not None:
                pending: int | None = None
                try:
                    while True:
                        pending = led_queue.get_nowait()
                except _queue_mod.Empty:
                    pass
                if pending is not None:
                    bitmask = pending  # 0x00=off, 0x01=M1, 0x02=M2, 0x04=M3
                    # Profile activate must precede 0b 1e for the indicator to switch.
                    # A different profile must be activated to trigger the hardware change;
                    # the profile number maps directly to the M-key slot (1=M1, 2=M2, 3=M3).
                    profile_num = _BITMASK_TO_PROFILE_NUM.get(bitmask, 1)
                    os.write(fd, bytes([0x11, 0xff, feat_profiles_idx, 0x1e, profile_num])
                             + b'\x00' * 15)
                    _time.sleep(0.05)
                    os.write(fd, bytes([0x11, 0xff, feat_8020_idx, 0x1e, bitmask])
                             + b'\x00' * 15)
                    print(f'[gkeys] M-key LED → bitmask=0x{bitmask:02x} profile={profile_num}')

            ready, _, _ = select.select([fd], [], [], 0.5)
            if not ready:
                continue
            try:
                data = os.read(fd, 64)
            except OSError:
                break
            if (len(data) >= 5
                    and data[0] == 0x11
                    and data[2] == feat_8020_idx
                    and data[3] == 0x00):
                bitmask = data[4]
                if bitmask in _MKEY_BITMASK_TO_IDX:
                    on_mkey(_MKEY_BITMASK_TO_IDX[bitmask])
    finally:
        os.close(fd)
