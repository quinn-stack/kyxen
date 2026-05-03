"""
HID++ feature utilities and ONBOARD_PROFILES (0x8100) sector access.

Feature index lookup
---------------------
get_feature_index(hidraw_path, uuid) looks up the runtime index for any
HID++ 2.0 feature UUID via the ROOT feature (index 0x00, func=0 getFeature).
Feature indices are NOT fixed — always look them up rather than hardcoding.

Known G815 feature UUIDs relevant to Kyxen:
  0x8010 — idx 0x0a — must be enabled before M-key notifications work
  0x8020 — idx 0x0b — M-key profile switch (notifications + activation)
  0x8100 — idx 0x11 — ONBOARD_PROFILES (sector read/write)

These are separate features. 0x8020 handles profile switching; 0x8100
handles raw sector access only.

ONBOARD_PROFILES sector access
--------------------------------
Used once at daemon startup to remap G1–G5 from F1–F5 (HID 0x3a–0x3e)
to F13–F17 (HID 0x68–0x6c) in keyboard flash, so evdev G-key events are
unambiguous and never collide with physical F-key presses.

Sectors:
  ROM   0x0101–0x0103 — factory defaults, read-only
  User  0x0001–0x0003 — writable flash (one per M-key profile slot)

Write protocol (confirmed from libratbag source + Solaar source + USB capture):
  func=5  readData(sector, offset)       → 16 bytes  (LONG report 0x11)
  func=6  writeStart(sector, 0, 256)     → ack       (LONG report 0x11)
  func=7  writeData(16 bytes) × 16       → ack       (LONG report 0x11)
  func=8  writeEnd()                     → ack       (SHORT report 0x10)
  CRC-CCITT (poly=0x1021, init=0xFFFF) over bytes[0:254], stored BE at [254:256]

_send() robustness note
------------------------
The HID++ hidraw interface also carries non-HID++ reports (media keys, boot
reports with IDs 0x01/0x02/0x03). _send() discards any packet whose first byte
is not 0x10/0x11/0x12 and retries within the timeout, so stale buffered reports
do not corrupt HID++ request/response pairing.
"""
from __future__ import annotations
import os
import select
import struct
import time

_LONG  = 0x11   # 20-byte HID++ long report ID
_SHORT = 0x10   # 7-byte HID++ short report ID

SECTOR_ROM_1  = 0x0101   # profile 1 ROM sector — factory defaults, read-only
SECTOR_ROM_2  = 0x0102   # profile 2 ROM sector
SECTOR_ROM_3  = 0x0103   # profile 3 ROM sector
SECTOR_USER_1 = 0x0001   # profile 1 user sector — writable flash
SECTOR_USER_2 = 0x0002   # profile 2 user sector — writable flash
SECTOR_USER_3 = 0x0003   # profile 3 user sector — writable flash

SECTOR_SIZE       = 0x0100   # 256 bytes per sector
GKEY_BLOCK_OFFSET = 0x0020   # offset of first G-key entry in the sector

_PROFILE_SECTORS = [
    (SECTOR_ROM_1, SECTOR_USER_1),
    (SECTOR_ROM_2, SECTOR_USER_2),
    (SECTOR_ROM_3, SECTOR_USER_3),
]

# HID keyboard usages: current (F1–F5) and target (F13–F17)
_F1_F5   = bytes([0x3a, 0x3b, 0x3c, 0x3d, 0x3e])
_F13_F17 = bytes([0x68, 0x69, 0x6a, 0x6b, 0x6c])


# ── CRC ───────────────────────────────────────────────────────────────────────

def _crc_ccitt(data: bytes) -> int:
    """CRC-CCITT (poly=0x1021, init=0xFFFF) over data, returns 16-bit result."""
    crc = 0xFFFF
    for b in data:
        crc ^= b << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) if (crc & 0x8000) else (crc << 1)
            crc &= 0xFFFF
    return crc


# ── HID++ packet builders ─────────────────────────────────────────────────────

def _long(feat: int, func: int, params: bytes = b'') -> bytes:
    pkt = bytes([_LONG, 0xff, feat, func << 4]) + params
    return pkt.ljust(20, b'\x00')[:20]


def _short(feat: int, func: int) -> bytes:
    return bytes([_SHORT, 0xff, feat, func << 4, 0x00, 0x00, 0x00])


# ── low-level I/O ─────────────────────────────────────────────────────────────

def _send(fd: int, pkt: bytes, timeout: float = 3.0) -> bytes:
    os.write(fd, pkt)
    deadline = time.monotonic() + timeout
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError('no response from keyboard')
        r, _, _ = select.select([fd], [], [], remaining)
        if not r:
            raise TimeoutError('no response from keyboard')
        resp = os.read(fd, 64)
        # Discard non-HID++ packets (e.g. buffered media key / boot-protocol reports)
        if not resp or resp[0] not in (0x10, 0x11, 0x12):
            continue
        # HID++ 2.0 error: SHORT report, feature index 0x8f
        if resp[0] == 0x10 and len(resp) >= 3 and resp[2] == 0x8f:
            raise RuntimeError(f'HID++ error: {resp.hex()}')
        return resp


# ── sector operations ─────────────────────────────────────────────────────────

def _read_full_sector(fd: int, feat: int, sector: int) -> bytearray:
    """Read all 256 bytes of sector via 16 successive readData (func=5) calls."""
    data = bytearray()
    for offset in range(0, SECTOR_SIZE, 16):
        params = struct.pack('>HH', sector, offset)
        resp = _send(fd, _long(feat, 5, params))
        chunk = resp[4:20]
        if len(chunk) < 16:
            raise RuntimeError(
                f'sector 0x{sector:04x} offset 0x{offset:02x}: '
                f'short response ({len(resp)} bytes): {resp.hex()}'
            )
        data.extend(chunk)
    return data


def _write_full_sector(fd: int, feat: int, sector: int, data: bytes) -> None:
    """
    Write 256-byte sector via 3-step write protocol (libratbag/Solaar confirmed):
      writeStart(sector, sub_addr=0, count=256)
      writeData(16 bytes) × 16
      writeEnd() — SHORT report
    """
    # write_start (func=6): sector, sub_address=0, byte_count=256
    params = struct.pack('>HHH', sector, 0, SECTOR_SIZE)
    _send(fd, _long(feat, 6, params))

    # write_data (func=7): 16 bytes per call
    for off in range(0, SECTOR_SIZE, 16):
        _send(fd, _long(feat, 7, bytes(data[off:off + 16])))

    # write_end (func=8): SHORT report
    _send(fd, _short(feat, 8), timeout=5.0)


def _set_current_profile(fd: int, feat: int, profile_idx: int) -> None:
    """Activate a profile by index (0-based) using setCurrentProfile (func=3, SHORT)."""
    pkt = bytes([_SHORT, 0xff, feat, 0x30, 0x00, profile_idx + 1, 0x00])
    _send(fd, pkt)


def _patch_gkeys(data: bytearray) -> None:
    """Replace G1–G5 HID keycodes (F1–F5) with F13–F17 in-place."""
    for i in range(5):
        base = GKEY_BLOCK_OFFSET + i * 4
        data[base + 3] = _F13_F17[i]


def _apply_crc(data: bytearray) -> None:
    """Compute CRC-CCITT over first 254 bytes and store BE in last 2 bytes."""
    crc = _crc_ccitt(bytes(data[:SECTOR_SIZE - 2]))
    struct.pack_into('>H', data, SECTOR_SIZE - 2, crc)


def _is_remapped(data: bytearray) -> bool:
    """Return True if G1 entry already targets F13 (0x68)."""
    return data[GKEY_BLOCK_OFFSET + 3] == _F13_F17[0]


def _crc_valid(data: bytearray) -> bool:
    """Return True if the sector's stored CRC matches its content (rules out uninitialised flash)."""
    expected = _crc_ccitt(bytes(data[:SECTOR_SIZE - 2]))
    stored   = struct.unpack_from('>H', data, SECTOR_SIZE - 2)[0]
    return expected == stored


# ── public entry points ───────────────────────────────────────────────────────

def get_feature_index(hidraw_path: str, uuid: int) -> int:
    """Return the runtime feature index for a 16-bit HID++ UUID (via ROOT getFeature)."""
    fd = os.open(hidraw_path, os.O_RDWR)
    try:
        resp = _send(fd, _long(0x00, 0, struct.pack('>H', uuid)))
        feat_idx = resp[4]
        if feat_idx == 0:
            raise RuntimeError(f'feature 0x{uuid:04x} not supported by keyboard')
        return feat_idx
    finally:
        os.close(fd)


def ensure_gkey_remap(hidraw_path: str, feature_idx: int) -> bool:
    """
    Check keyboard flash; remap G1–G5 → F13–F17 across all 3 profiles.

    Reads each ROM sector (0x0101–0x0103) as the source and writes the patched
    data to the corresponding user sector (0x0001–0x0003). All 3 must be valid
    for M-key profile switching to work.
    Returns True if any write was performed, False if already fully remapped.
    Raises on I/O error or keyboard timeout.
    """
    fd = os.open(hidraw_path, os.O_RDWR)
    try:
        # Read all 3 user sectors; skip write only if every sector is already
        # remapped AND has a valid CRC (rules out uninitialised flash with 0xFF bytes).
        user_data = [_read_full_sector(fd, feature_idx, addr)
                     for _, addr in _PROFILE_SECTORS]
        if all(_is_remapped(s) and _crc_valid(s) for s in user_data):
            print('[onboard] G-key remap already F13–F17 on all profiles, skipping')
            return False

        # Write all 3 profiles so M-key switching has valid flash for each slot.
        print('[onboard] remapping G1–G5 → F13–F17 in keyboard flash (all 3 profiles)...')
        for rom_addr, user_addr in _PROFILE_SECTORS:
            rom_data = _read_full_sector(fd, feature_idx, rom_addr)
            _patch_gkeys(rom_data)
            _apply_crc(rom_data)
            _write_full_sector(fd, feature_idx, user_addr, rom_data)

        _set_current_profile(fd, feature_idx, 0)   # profile index 0 = profile 1
        print('[onboard] all 3 profiles remapped and saved')
        return True
    finally:
        os.close(fd)
