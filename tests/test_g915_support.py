"""Tests for G915 support: HID++ interface detection, runtime feature
indices and the flash-write safety check. No keyboard required."""
from __future__ import annotations
import os
import socket
import struct

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


def test_g815_remap_uses_resolved_onboard_profiles_index(monkeypatch) -> None:
    seen = {}
    monkeypatch.setattr(onboard_profiles, 'get_feature_index', lambda p, f: 0x11)
    monkeypatch.setattr(onboard_profiles, 'ensure_gkey_remap',
                        lambda path, idx: seen.setdefault('idx', idx) and False)
    LogitechG815(DevicePaths(evdev='/dev/null', hidraw='/dev/hidraw9')).ensure_gkey_remap()
    assert seen['idx'] == 0x11


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


# ── onboard profile sectors ──────────────────────────────────────────────────

F1_F5   = bytes([0x3a, 0x3b, 0x3c, 0x3d, 0x3e])
DIGITS  = bytes([0x1e, 0x1f, 0x20, 0x21, 0x22])   # G915 profile 2 factory default
F13_F17 = bytes([0x68, 0x69, 0x6a, 0x6b, 0x6c])


def _sector(gkeys: bytes, size: int = 256, crc: str = 'valid', binding: bytes = b'\x80\x02') -> bytearray:
    data = bytearray(size)
    data[0] = 0x42   # some profile content to prove it is preserved
    for i, key in enumerate(gkeys):
        base = onboard_profiles.GKEY_BLOCK_OFFSET + i * 4
        data[base:base + 4] = binding + bytes([0x00, key])
    if crc == 'valid':
        onboard_profiles._apply_crc(data)
    elif crc == 'none':
        data[-2:] = b'\xff\xff'          # G915 ROM sectors carry no CRC
    else:
        onboard_profiles._apply_crc(data)
        data[-1] ^= 0xFF
    return data


@pytest.mark.parametrize('size', [256, 255])
def test_crc_uses_actual_sector_size(size: int) -> None:
    data = _sector(F1_F5, size)
    assert onboard_profiles._crc_valid(data)
    assert struct.unpack('>H', data[-2:])[0] == onboard_profiles._crc_ccitt(bytes(data[:-2]))


def test_source_check_accepts_user_sector_and_crc_less_rom() -> None:
    onboard_profiles._check_source_sector(0x0002, _sector(DIGITS, 255), is_rom=False)
    onboard_profiles._check_source_sector(0x0102, _sector(DIGITS, 255, crc='none'), is_rom=True)


@pytest.mark.parametrize('data,is_rom', [
    (_sector(F1_F5, crc='bad'), False),
    (_sector(F1_F5, crc='none'), False),                       # user sector without CRC
    (_sector(F1_F5, crc='bad'), True),
    (_sector(F1_F5, binding=b'\x80\x01'), False),              # mouse binding, not keyboard
])
def test_source_check_rejects_unexpected_data(data: bytearray, is_rom: bool) -> None:
    with pytest.raises(RuntimeError, match='refusing to write flash'):
        onboard_profiles._check_source_sector(0x0001, data, is_rom)


class _FakeFlash:
    """Stands in for _read_full_sector/_write_full_sector on a 255-byte-sector keyboard."""

    def __init__(self, monkeypatch, sectors: dict[int, bytearray], size: int = 255) -> None:
        self.sectors, self.writes = sectors, {}
        monkeypatch.setattr(os, 'open', lambda *a, **k: 99)
        monkeypatch.setattr(os, 'close', lambda fd: None)
        monkeypatch.setattr(onboard_profiles, 'get_sector_size', lambda fd, feat: size)
        monkeypatch.setattr(onboard_profiles, '_read_full_sector',
                            lambda fd, feat, addr, sz: bytearray(self.sectors[addr]))
        monkeypatch.setattr(onboard_profiles, '_write_full_sector', self._write)
        monkeypatch.setattr(onboard_profiles, '_set_current_profile', lambda *a: None)

    def _write(self, fd, feat, addr, data, size):
        assert len(data) == size
        self.writes[addr] = bytearray(data)


def test_remap_patches_valid_user_sectors_in_place(monkeypatch) -> None:
    user1 = _sector(F1_F5, 255)
    user1[1] = 0x99                                   # user customisation
    onboard_profiles._apply_crc(user1)
    flash = _FakeFlash(monkeypatch, {
        0x0001: user1,
        0x0002: _sector(DIGITS, 255, crc='bad'),       # broken → rebuilt from ROM
        0x0003: _sector(DIGITS, 255),
        0x0102: _sector(DIGITS, 255, crc='none'),
    })
    assert onboard_profiles.ensure_gkey_remap('/dev/hidrawX', 0x14) is True
    assert sorted(flash.writes) == [1, 2, 3]
    assert flash.writes[1][1] == 0x99                  # customisation kept
    for data in flash.writes.values():
        assert onboard_profiles._gkey_usages(data) == F13_F17
        assert onboard_profiles._crc_valid(data)


def test_no_flash_write_when_any_source_is_unexpected(monkeypatch) -> None:
    flash = _FakeFlash(monkeypatch, {
        0x0001: _sector(F1_F5, 255), 0x0002: _sector(DIGITS, 255),
        0x0003: _sector(DIGITS, 255, crc='bad'),
        0x0103: _sector(DIGITS, 255, crc='bad'),       # ROM unusable too
    })
    with pytest.raises(RuntimeError):
        onboard_profiles.ensure_gkey_remap('/dev/hidrawX', 0x14)
    assert flash.writes == {}


def test_already_remapped_skips_write(monkeypatch) -> None:
    flash = _FakeFlash(monkeypatch, {a: _sector(F13_F17, 255) for a in (1, 2, 3)})
    assert onboard_profiles.ensure_gkey_remap('/dev/hidrawX', 0x14) is False
    assert flash.writes == {}


# ── HID++ transport against a fake device ────────────────────────────────────

class _FakeDevice:
    """socketpair-backed fake hidraw node: answers readData like the G915."""

    def __init__(self, sector: bytes, size: int) -> None:
        self.host, self.dev = socket.socketpair(socket.AF_UNIX, socket.SOCK_SEQPACKET)
        self.sector, self.size, self.requests = sector, size, []

    def serve(self, n: int) -> None:
        for _ in range(n):
            req = self.dev.recv(64)
            self.requests.append(req)
            offset = struct.unpack('>H', req[6:8])[0]
            # unrelated notification first, to check response matching
            self.dev.send(bytes([0x11, 0xff, 0x0a, 0x00]) + bytes(16))
            if offset + 16 > self.size:   # HID++ 2.0 error: INVALID_ARGUMENT
                self.dev.send(bytes([0x11, 0xff, 0xff, req[2], req[3], 0x02]) + bytes(14))
            else:
                self.dev.send(req[:4] + self.sector[offset:offset + 16])


def test_read_sector_of_255_bytes_never_reads_past_the_end() -> None:
    import threading
    content = bytes(range(255))
    dev = _FakeDevice(content, 255)
    t = threading.Thread(target=dev.serve, args=(16,))
    t.start()
    data = onboard_profiles._read_full_sector(dev.host.fileno(), 0x14, 0x0001, 255)
    t.join()
    assert bytes(data) == content
    assert struct.unpack('>H', dev.requests[-1][6:8])[0] == 255 - 16


def test_hidpp20_error_is_raised_not_returned_as_data() -> None:
    import threading
    dev = _FakeDevice(bytes(256), 255)
    t = threading.Thread(target=dev.serve, args=(1,))
    t.start()
    with pytest.raises(RuntimeError, match='HID\\+\\+ error'):
        onboard_profiles._send(dev.host.fileno(), onboard_profiles._long(0x14, 5, struct.pack('>HH', 1, 0xF0)))
    t.join()


# ── G-keys via HID++ notifications ───────────────────────────────────────────

def test_gkey_changes_from_bitmasks() -> None:
    from kyxen_keys.gkeys import gkey_changes
    assert gkey_changes(0x00, 0x01) == (['g1'], [])
    assert gkey_changes(0x01, 0x00) == ([], ['g1'])
    assert gkey_changes(0x01, 0x11) == (['g5'], [])          # G5 added while G1 held
    assert gkey_changes(0x11, 0x10) == ([], ['g1'])


def test_g915_reads_gkeys_via_hidpp_without_flash_remap() -> None:
    kb = LogitechG915(DevicePaths(evdev='/dev/null', hidraw='/dev/hidraw5'))
    assert LogitechG915.GKEYS_VIA_HIDPP and not LogitechG815.GKEYS_VIA_HIDPP
    assert LogitechG915.GKEY_SUPPRESS_CODES == frozenset()
    assert kb.ensure_gkey_remap() is False


def test_mkey_listener_reports_gkey_notifications(monkeypatch) -> None:
    """Feed the listener the exact packets captured from a G915 (feature 0x10)."""
    from kyxen_keys import gkeys
    captured = [bytes.fromhex(h) for h in (
        '11ff100001000000000000000000000000000000',   # G1 down
        '11ff100000000000000000000000000000000000',   # up
        '11ff100010000000000000000000000000000000',   # G5 down
        '11ff100000000000000000000000000000000000',   # up
        '11ff110002000000000000000000000000000000',   # M2 (feature 0x11)
    )]
    import threading
    import time
    host, dev = socket.socketpair(socket.AF_UNIX, socket.SOCK_SEQPACKET)
    host.setblocking(False)
    monkeypatch.setattr(gkeys.os, 'open', lambda *a, **k: host.fileno())
    monkeypatch.setattr(gkeys.os, 'close', lambda fd: None)

    def keyboard() -> None:
        time.sleep(1.2)                 # after the listener's startup drain (~1 s)
        for pkt in captured:
            dev.send(pkt)

    threading.Thread(target=keyboard, daemon=True).start()
    events, mkeys = [], []
    deadline = time.monotonic() + 2.0
    gkeys.run_mkey_listener(
        hidraw_path='/dev/hidraw5', feat_8010_idx=0x10, feat_8020_idx=0x11, feat_profiles_idx=0x14,
        on_mkey=mkeys.append, stop_flag=lambda: time.monotonic() > deadline,
        on_gkey_press=lambda g: events.append(('down', g)),
        on_gkey_release=lambda g: events.append(('up', g)),
    )
    assert events == [('down', 'g1'), ('up', 'g1'), ('down', 'g5'), ('up', 'g5')]
    assert mkeys == [1]
