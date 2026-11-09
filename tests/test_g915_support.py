"""Tests for G915 support: HID++ interface detection, runtime feature
indices and the flash-write safety check. No keyboard required."""
from __future__ import annotations
import os

import pytest

from kyxen_keys import lighting_engine, onboard_profiles
from kyxen_keys.keyboards import ALL_DRIVERS, DevicePaths, LogitechG815
from kyxen_keys.keyboards.detect import is_hidpp_descriptor
from kyxen_keys.keyboards.logitech_g915 import LogitechG915

# Report descriptors read from a G915 (046d:c33e) connected by USB cable.
G915_IFACE0_BOOT_KBD = bytes.fromhex(
    '05010906a101050719e029e7150025017501950881029505050819012905910295017503'
    '910395707501050719042973810295051987298b81029503199029928102c0')
G915_IFACE1_MOUSE_CC = bytes.fromhex(
    '05010902a10185020901a100951075011500250105091901291081029502751016018026'
    'ff7f0501093009318106950175081581257f093881069501050c0a38028106c0c0050c09'
    '01a101850395027510150126ff0219012aff028100c005010980a1018504950175021501'
    '2503098209810983810075068103c0')
G915_IFACE2_HIDPP = bytes.fromhex(
    '0600ff0901a101851095067508150026ff000901810009019100c00600ff0902a1018511'
    '95137508150026ff000902810009029100c0')


# ── HID++ interface detection ────────────────────────────────────────────────

def test_hidpp_descriptor_found_on_interface_2_only() -> None:
    assert not is_hidpp_descriptor(G915_IFACE0_BOOT_KBD)
    assert not is_hidpp_descriptor(G915_IFACE1_MOUSE_CC)
    assert is_hidpp_descriptor(G915_IFACE2_HIDPP)


def test_report_id_0x11_outside_vendor_page_is_not_hidpp() -> None:
    # Generic Desktop page with report ID 0x11
    assert not is_hidpp_descriptor(bytes.fromhex('05010906a1018511c0'))


# ── driver registry ──────────────────────────────────────────────────────────

def test_g915_registered_with_wired_pid() -> None:
    assert LogitechG915 in ALL_DRIVERS
    assert LogitechG915.PRODUCT_IDS == [0xC33E]
    assert 0xC33E not in LogitechG815.PRODUCT_IDS


def test_g815_specific_init_not_inherited_by_g915() -> None:
    paths = DevicePaths(evdev='/dev/null', hidraw='/dev/null')
    assert LogitechG815(paths).lighting_init_packets() == list(lighting_engine.G815_INIT_PACKETS)
    assert LogitechG915(paths).lighting_init_packets() == []


def test_feature_index_is_looked_up_once(monkeypatch) -> None:
    calls = []

    def fake_lookup(path: str, feature_id: int) -> int:
        calls.append((path, feature_id))
        return 0x15

    monkeypatch.setattr(onboard_profiles, 'get_feature_index', fake_lookup)
    kb = LogitechG915(DevicePaths(evdev='/dev/null', hidraw='/dev/hidraw5'))
    assert kb.feature_index(0x8100) == 0x15
    assert kb.feature_index(0x8100) == 0x15
    assert calls == [('/dev/hidraw5', 0x8100)]


def test_feature_index_without_hidraw_raises() -> None:
    kb = LogitechG915(DevicePaths(evdev='/dev/null', hidraw=''))
    with pytest.raises(RuntimeError):
        kb.feature_index(0x8081)


def test_remap_uses_resolved_onboard_profiles_index(monkeypatch) -> None:
    seen = {}
    monkeypatch.setattr(onboard_profiles, 'get_feature_index', lambda p, f: 0x15)
    monkeypatch.setattr(onboard_profiles, 'ensure_gkey_remap',
                        lambda path, idx: seen.setdefault('idx', idx) and False)
    LogitechG915(DevicePaths(evdev='/dev/null', hidraw='/dev/hidraw5')).ensure_gkey_remap()
    assert seen['idx'] == 0x15


# ── lighting frames ──────────────────────────────────────────────────────────

def test_frame_uses_given_feature_index() -> None:
    r, w = os.pipe()
    try:
        lighting_engine._write_frame(w, {'A': (1, 2, 3)}, None, {'A': 0x01}, feature_idx=0x0b)
        data = os.read(r, 4096)
    finally:
        os.close(r)
        os.close(w)
    assert len(data) == 40
    key_pkt, commit = data[:20], data[20:]
    assert key_pkt[:9] == bytes([0x11, 0xff, 0x0b, 0x5e, 0x01, 0x01, 1, 2, 3])
    assert commit[:4] == bytes([0x11, 0xff, 0x0b, 0x7e])


def test_engine_defaults_stay_g815() -> None:
    eng = lighting_engine.LightingEngine('/dev/null', lambda: True)
    assert eng._feature_idx == 0x10
    assert eng._init_packets == list(lighting_engine.G815_INIT_PACKETS)


# ── flash-write safety ───────────────────────────────────────────────────────

def _sector(gkeys: bytes, valid_crc: bool = True) -> bytearray:
    data = bytearray(onboard_profiles.SECTOR_SIZE)
    for i, key in enumerate(gkeys):
        base = onboard_profiles.GKEY_BLOCK_OFFSET + i * 4
        data[base:base + 4] = bytes([0x80, 0x02, 0x00, key])
    onboard_profiles._apply_crc(data)
    if not valid_crc:
        data[-1] ^= 0xFF
    return data


F1_F5 = bytes([0x3a, 0x3b, 0x3c, 0x3d, 0x3e])


def test_check_rom_sector_accepts_factory_bindings() -> None:
    onboard_profiles._check_rom_sector(0x0101, _sector(F1_F5))


@pytest.mark.parametrize('data', [
    _sector(F1_F5, valid_crc=False),
    _sector(bytes([0x04, 0x05, 0x06, 0x07, 0x08])),
])
def test_check_rom_sector_rejects_unexpected_data(data: bytearray) -> None:
    with pytest.raises(RuntimeError, match='refusing to write flash'):
        onboard_profiles._check_rom_sector(0x0101, data)


def test_no_flash_write_when_any_rom_sector_is_unexpected(monkeypatch) -> None:
    sectors = {
        0x0001: _sector(F1_F5), 0x0002: _sector(F1_F5), 0x0003: _sector(F1_F5),
        0x0101: _sector(F1_F5), 0x0102: _sector(F1_F5),
        0x0103: _sector(bytes(5)),   # third ROM profile looks wrong
    }
    writes = []
    monkeypatch.setattr(os, 'open', lambda *a, **k: 99)
    monkeypatch.setattr(os, 'close', lambda fd: None)
    monkeypatch.setattr(onboard_profiles, '_read_full_sector',
                        lambda fd, feat, addr: bytearray(sectors[addr]))
    monkeypatch.setattr(onboard_profiles, '_write_full_sector',
                        lambda fd, feat, addr, data: writes.append(addr))
    monkeypatch.setattr(onboard_profiles, '_set_current_profile', lambda *a: None)

    with pytest.raises(RuntimeError):
        onboard_profiles.ensure_gkey_remap('/dev/hidrawX', 0x15)
    assert writes == []


def test_remap_writes_all_user_sectors_when_rom_is_valid(monkeypatch) -> None:
    sectors = {addr: _sector(F1_F5) for addr in (1, 2, 3, 0x101, 0x102, 0x103)}
    writes = {}
    monkeypatch.setattr(os, 'open', lambda *a, **k: 99)
    monkeypatch.setattr(os, 'close', lambda fd: None)
    monkeypatch.setattr(onboard_profiles, '_read_full_sector',
                        lambda fd, feat, addr: bytearray(sectors[addr]))
    monkeypatch.setattr(onboard_profiles, '_write_full_sector',
                        lambda fd, feat, addr, data: writes.__setitem__(addr, bytes(data)))
    monkeypatch.setattr(onboard_profiles, '_set_current_profile', lambda *a: None)

    assert onboard_profiles.ensure_gkey_remap('/dev/hidrawX', 0x15) is True
    assert sorted(writes) == [1, 2, 3]
    for data in writes.values():
        assert onboard_profiles._is_remapped(bytearray(data))
        assert onboard_profiles._crc_valid(bytearray(data))
