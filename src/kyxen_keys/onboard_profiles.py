"""
ONBOARD_PROFILES (HID++ 0x8100) write support.

Used once at daemon startup to remap G1–G5 from F1–F5 (HID 0x3a–0x3e)
to F13–F17 (HID 0x68–0x6c) in keyboard flash, so evdev G-key events are
unambiguous and never collide with physical F-key presses.

Write protocol (confirmed from libratbag source + Solaar source):
  func=5  readData(sector, offset)       → 16 bytes  (long report 0x11)
  func=6  writeStart(sector, 0, 256)     → ack       (long report 0x11, sub_addr always 0)
  func=7  writeData(16 bytes)            → ack       (long report 0x11, repeated ×16)
  func=8  writeEnd()                     → ack       (SHORT report 0x10)
  CRC-CCITT over bytes[0:254], stored BE at bytes[254:256]
"""
from __future__ import annotations
import os
import select
import struct

_LONG  = 0x11   # 20-byte HID++ long report ID
_SHORT = 0x10   # 7-byte HID++ short report ID

SECTOR_ROM_1      = 0x0101   # profile 1 ROM sector — factory defaults, read-only
SECTOR_USER_1     = 0x0001   # profile 1 user sector — writable RAM/flash
SECTOR_SIZE       = 0x0100   # 256 bytes per sector
GKEY_BLOCK_OFFSET = 0x0020   # offset of first G-key entry in the sector

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
    r, _, _ = select.select([fd], [], [], timeout)
    if not r:
        raise TimeoutError('no response from keyboard')
    resp = os.read(fd, 64)
    # HID++ error response: byte[2]=0xff, byte[3]=feature_idx, byte[4]=func, byte[5]=error
    if len(resp) >= 3 and resp[2] == 0xff:
        raise RuntimeError(f'HID++ error: {resp.hex()}')
    return resp


# ── sector operations ─────────────────────────────────────────────────────────

def _read_full_sector(fd: int, feat: int, sector: int) -> bytearray:
    """Read all 256 bytes of sector via 16 successive readData (func=5) calls."""
    data = bytearray()
    for offset in range(0, SECTOR_SIZE, 16):
        params = struct.pack('>HH', sector, offset)
        resp = _send(fd, _long(feat, 5, params))
        data.extend(resp[4:20])
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


# ── public entry point ────────────────────────────────────────────────────────

def ensure_gkey_remap(hidraw_path: str, feature_idx: int) -> bool:
    """
    Check keyboard flash; remap G1–G5 → F13–F17 if not already done.

    Reads from the ROM sector (0x0101, factory defaults) as source and
    writes the patched profile to the user sector (0x0001, writable).
    Returns True if a write was performed, False if already remapped.
    Raises on I/O error or keyboard timeout.
    """
    fd = os.open(hidraw_path, os.O_RDWR)
    try:
        # Check the user sector first — if it already has the remap, done
        user_data = _read_full_sector(fd, feature_idx, SECTOR_USER_1)
        if _is_remapped(user_data):
            print('[onboard] G-key remap already F13–F17, skipping')
            return False

        # Read ROM sector as authoritative source for current G-key bindings
        print('[onboard] remapping G1–G5 → F13–F17 in keyboard flash...')
        rom_data = _read_full_sector(fd, feature_idx, SECTOR_ROM_1)
        _patch_gkeys(rom_data)
        _apply_crc(rom_data)

        # Write patched profile to writable user sector and activate it
        _write_full_sector(fd, feature_idx, SECTOR_USER_1, rom_data)
        _set_current_profile(fd, feature_idx, 0)   # profile index 0 = profile 1
        print('[onboard] remap written and saved')
        return True
    finally:
        os.close(fd)
