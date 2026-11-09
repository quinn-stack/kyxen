"""
HID++ feature utilities and ONBOARD_PROFILES (0x8100) sector access.

Feature index lookup
---------------------
get_feature_index(hidraw_path, uuid) looks up the runtime index for any
HID++ 2.0 feature UUID via the ROOT feature (index 0x00, func=0 getFeature).
Feature indices are NOT fixed — always look them up rather than hardcoding.

Feature UUIDs relevant to Kyxen (index on G815 / on a G915, firmware-dependent):
  0x8010 — 0x0a / 0x10 — must be enabled before M-key notifications work
  0x8020 — 0x0b / 0x11 — M-key profile switch (notifications + activation)
  0x8081 — 0x10 / 0x0a — PerKeyLightingV2
  0x8100 — 0x11 / 0x14 — ONBOARD_PROFILES (sector read/write)

These are separate features. 0x8020 handles profile switching; 0x8100
handles raw sector access only.

ONBOARD_PROFILES sector access
--------------------------------
Used once at daemon startup to remap G1–G5 to F13–F17 (HID 0x68–0x6c) in
keyboard flash, so evdev G-key events are unambiguous and never collide with
physical key presses. Factory bindings differ per model and profile (G815:
F1–F5; G915: F1–F5, 1–5, 6–0 on profiles 1–3).

Sectors:
  ROM   0x0101–0x0103 — factory defaults, read-only (G915: no CRC, ends ff ff)
  User  0x0001–0x0003 — writable flash (one per M-key profile slot)

The sector size comes from getDescription (func=0, bytes 7–8 of the payload):
256 on the G815, 255 on the G915. Reads past the end fail with INVALID_ARGUMENT,
so the last chunk is read at offset size-16.

Write protocol (confirmed from libratbag source + Solaar source + USB capture):
  func=0  getDescription()               → ... sector_size (BE) at payload[7:9]
  func=5  readData(sector, offset)       → 16 bytes  (LONG report 0x11)
  func=6  writeStart(sector, 0, size)    → ack       (LONG report 0x11)
  func=7  writeData(16 bytes) × n        → ack       (LONG report 0x11)
  func=8  writeEnd()                     → ack       (SHORT report 0x10)
  CRC-CCITT (poly=0x1021, init=0xFFFF) over bytes[0:size-2], stored BE at [size-2:size]

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

# HID++ 2.0 feature IDs. Their runtime *indices* differ per model and firmware
# (e.g. ONBOARD_PROFILES is 0x11 on the G815 but 0x15 on the G915), so always
# resolve them with get_feature_index().
FEATURE_GKEY             = 0x8010
FEATURE_MKEYS            = 0x8020
FEATURE_RGB_EFFECTS      = 0x8071
FEATURE_PER_KEY_LIGHTING = 0x8081   # PerKeyLightingV2
FEATURE_ONBOARD_PROFILES = 0x8100

SECTOR_ROM_1  = 0x0101   # profile 1 ROM sector — factory defaults, read-only
SECTOR_ROM_2  = 0x0102   # profile 2 ROM sector
SECTOR_ROM_3  = 0x0103   # profile 3 ROM sector
SECTOR_USER_1 = 0x0001   # profile 1 user sector — writable flash
SECTOR_USER_2 = 0x0002   # profile 2 user sector — writable flash
SECTOR_USER_3 = 0x0003   # profile 3 user sector — writable flash

SECTOR_SIZE       = 0x0100   # default sector size (G815); see get_sector_size()
GKEY_BLOCK_OFFSET = 0x0020   # offset of first G-key entry in the sector
GKEY_COUNT        = 5

# Button binding entry (4 bytes): type, subtype, modifiers, HID usage
_BINDING_HID      = 0x80
_BINDING_KEYBOARD = 0x02

_PROFILE_SECTORS = [
    (SECTOR_ROM_1, SECTOR_USER_1),
    (SECTOR_ROM_2, SECTOR_USER_2),
    (SECTOR_ROM_3, SECTOR_USER_3),
]

# HID keyboard usages: G815 factory default (F1–F5) and target (F13–F17)
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
    """
    Send a HID++ request and return the matching response.

    Skips non-HID++ reports and HID++ packets that belong to other requests or
    notifications. Raises on a HID++ 1.0 error (short report, 0x8f) or a
    HID++ 2.0 error (feature index 0xff) for this request.
    """
    feat, func = pkt[2], pkt[3]
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
        if len(resp) < 4 or resp[0] not in (0x10, 0x11, 0x12):
            continue
        # HID++ 1.0 error (short report, 0x8f) or HID++ 2.0 error (index 0xff)
        if resp[2] in (0x8f, 0xff) and resp[3] == feat:
            raise RuntimeError(f'HID++ error: {resp.hex()}')
        if resp[2] == feat and resp[3] == func:
            return resp


# ── sector operations ─────────────────────────────────────────────────────────

def get_sector_size(fd: int, feat: int) -> int:
    """Return the onboard-profile sector size reported by getDescription."""
    resp = _send(fd, _long(feat, 0))
    size = struct.unpack_from('>H', resp, 4 + 7)[0]
    if not 32 <= size <= 0x1000:
        raise RuntimeError(f'implausible sector size {size} in {resp.hex()}')
    return size


def _read_full_sector(fd: int, feat: int, sector: int, size: int = SECTOR_SIZE) -> bytearray:
    """Read a whole sector in 16-byte readData (func=5) calls.

    Reading past the end of the sector is an error, so the final chunk is
    read at offset size-16 (overlapping the previous one when size % 16 != 0).
    """
    data = bytearray(size)
    for offset in range(0, size, 16):
        offset = min(offset, size - 16)
        resp = _send(fd, _long(feat, 5, struct.pack('>HH', sector, offset)))
        chunk = resp[4:20]
        if len(chunk) < 16:
            raise RuntimeError(
                f'sector 0x{sector:04x} offset 0x{offset:02x}: '
                f'short response ({len(resp)} bytes): {resp.hex()}'
            )
        data[offset:offset + 16] = chunk
    return data


def _write_full_sector(fd: int, feat: int, sector: int, data: bytes,
                       size: int = SECTOR_SIZE) -> None:
    """
    Write a whole sector via the 3-step write protocol (libratbag/Solaar confirmed):
      writeStart(sector, sub_addr=0, count=size)
      writeData(16 bytes) × ceil(size / 16)   — last chunk zero-padded
      writeEnd() — SHORT report
    """
    if len(data) != size:
        raise ValueError(f'sector data is {len(data)} bytes, expected {size}')
    _send(fd, _long(feat, 6, struct.pack('>HHH', sector, 0, size)))
    for off in range(0, size, 16):
        _send(fd, _long(feat, 7, bytes(data[off:off + 16])))
    _send(fd, _short(feat, 8), timeout=5.0)


def _set_current_profile(fd: int, feat: int, profile_idx: int) -> None:
    """Activate a profile by index (0-based) using setCurrentProfile (func=3, SHORT)."""
    pkt = bytes([_SHORT, 0xff, feat, 0x30, 0x00, profile_idx + 1, 0x00])
    _send(fd, pkt)


def _gkey_usages(data: bytearray) -> bytes:
    return bytes(data[GKEY_BLOCK_OFFSET + i * 4 + 3] for i in range(GKEY_COUNT))


def _patch_gkeys(data: bytearray) -> None:
    """Bind G1–G5 to F13–F17 in-place (keeps the keyboard binding type)."""
    for i in range(GKEY_COUNT):
        base = GKEY_BLOCK_OFFSET + i * 4
        data[base + 2] = 0x00               # no modifiers
        data[base + 3] = _F13_F17[i]


def _apply_crc(data: bytearray) -> None:
    """Compute CRC-CCITT over all but the last 2 bytes and store it BE there."""
    crc = _crc_ccitt(bytes(data[:-2]))
    struct.pack_into('>H', data, len(data) - 2, crc)


def _is_remapped(data: bytearray) -> bool:
    """Return True if G1–G5 already target F13–F17."""
    return _gkey_usages(data) == _F13_F17


def _crc_valid(data: bytearray) -> bool:
    """Return True if the sector's stored CRC matches its content (rules out uninitialised flash)."""
    expected = _crc_ccitt(bytes(data[:-2]))
    stored   = struct.unpack_from('>H', data, len(data) - 2)[0]
    return expected == stored


def _check_source_sector(sector: int, data: bytearray, is_rom: bool) -> None:
    """
    Refuse to patch a sector that does not look like the expected profile
    layout. A user sector needs a valid CRC; ROM sectors may carry no CRC at
    all (G915: ff ff). Every G-key entry must be a plain keyboard binding
    (80 02 xx yy), which is what _patch_gkeys rewrites. Anything else means the
    sector layout differs, and writing a patched copy would corrupt the profile.
    """
    if not _crc_valid(data):
        stored = struct.unpack_from('>H', data, len(data) - 2)[0]
        if not (is_rom and stored == 0xFFFF):
            raise RuntimeError(f'sector 0x{sector:04x} has an invalid CRC — refusing to write flash')
    for i in range(GKEY_COUNT):
        base = GKEY_BLOCK_OFFSET + i * 4
        if data[base] != _BINDING_HID or data[base + 1] != _BINDING_KEYBOARD:
            raise RuntimeError(
                f'sector 0x{sector:04x}: G{i + 1} entry {data[base:base + 4].hex()} is not '
                f'a keyboard binding — refusing to write flash'
            )


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

    For each profile the user sector (0x0001–0x0003) is patched in place when
    it holds a valid profile, so settings made with other tools are kept.
    Otherwise the factory ROM sector (0x0101–0x0103) is used as the source.
    All sources are read and validated before anything is written.
    Returns True if any write was performed, False if already fully remapped.
    Raises on I/O error, keyboard timeout or unexpected sector contents.
    """
    fd = os.open(hidraw_path, os.O_RDWR)
    try:
        size = get_sector_size(fd, feature_idx)
        user_data = [_read_full_sector(fd, feature_idx, addr, size)
                     for _, addr in _PROFILE_SECTORS]
        if all(_is_remapped(s) and _crc_valid(s) for s in user_data):
            print('[onboard] G-key remap already F13–F17 on all profiles, skipping')
            return False

        # Pick and validate every source before writing anything, so a layout
        # mismatch can never leave the flash half-written.
        plan: list[tuple[int, bytearray]] = []
        for (rom_addr, user_addr), user in zip(_PROFILE_SECTORS, user_data):
            if _crc_valid(user):
                _check_source_sector(user_addr, user, is_rom=False)
                plan.append((user_addr, user))
            else:
                rom = _read_full_sector(fd, feature_idx, rom_addr, size)
                _check_source_sector(rom_addr, rom, is_rom=True)
                plan.append((user_addr, rom))

        print(f'[onboard] remapping G1–G5 → F13–F17 in keyboard flash '
              f'(3 profiles, {size}-byte sectors)...')
        for user_addr, data in plan:
            _patch_gkeys(data)
            _apply_crc(data)
            _write_full_sector(fd, feature_idx, user_addr, data, size)

        _set_current_profile(fd, feature_idx, 0)   # profile index 0 = profile 1
        print('[onboard] all 3 profiles remapped and saved')
        return True
    finally:
        os.close(fd)
