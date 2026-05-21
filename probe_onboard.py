#!/usr/bin/env python3
"""
G815 onboard profile probe.
Run with daemon stopped: systemctl --user stop kyxen
  python3 ~/kyxen/probe_onboard.py

1. Enumerates every HID++ feature (UUID + index)
2. Dumps all 3 ROM sectors as hex so we can map the lighting fields
"""
import os, select, struct, sys
sys.path.insert(0, '/home/wade/kyxen/src')

from kyxen_keys.keyboards import detect_keyboard
from kyxen_keys import onboard_profiles as op

kb     = detect_keyboard()
hidraw = kb.paths.hidraw
print(f'Keyboard: {kb.MODEL_NAME}\nHID++:    {hidraw}\n')

fd = os.open(hidraw, os.O_RDWR)

def send(pkt):
    os.write(fd, pkt.ljust(20, b'\x00')[:20])
    import time
    deadline = time.monotonic() + 2.0
    while True:
        r, _, _ = select.select([fd], [], [], max(0, deadline - time.monotonic()))
        if not r:
            return None
        d = os.read(fd, 64)
        if d and d[0] in (0x10, 0x11, 0x12):
            return d

# ── 1. Enumerate all features ─────────────────────────────────────────────────
print('=== HID++ Feature Table ===')
# IRoot (0x00) getFeatureCount: func=0 on IFeatureSet (index 0x01)
feat_set_resp = send(bytes([0x11, 0xff, 0x00, 0x00, 0x00, 0x01]))  # getFeature(0x0001)
if not feat_set_resp:
    print('No response to getFeature(IFeatureSet)')
    sys.exit(1)
feat_set_idx = feat_set_resp[4]
count_resp = send(bytes([0x11, 0xff, feat_set_idx, 0x00]))  # getCount()
feature_count = count_resp[4] if count_resp else 0
print(f'Feature set index: 0x{feat_set_idx:02x}, total features: {feature_count}')
print(f'{"Idx":>4}  {"UUID":>6}  {"Obsolete":>8}  {"Hidden":>6}')
print('-' * 40)
known = {
    0x0000: 'IRoot', 0x0001: 'IFeatureSet', 0x0002: 'IFirmwareInfo',
    0x0003: 'DeviceNameType', 0x0005: 'DeviceTypeAndName',
    0x1000: 'BatteryStatus', 0x1001: 'BatteryVoltage',
    0x1801: 'StartupMode', 0x1802: 'DeviceReset',
    0x1f20: 'ADCMeasurement',
    0x4100: 'Receiver',
    0x4220: 'LEDControl',
    0x4301: 'TouchpadRawXY',
    0x8010: 'OnboardProfiles', 0x8020: 'ProfileSwitch',
    0x8060: 'AdjustableDPI', 0x8061: 'ExtendedAdjustableDPI',
    0x8070: 'SensorRange',
    0x8071: 'RGBEffects', 0x8080: 'PerKeyLighting',
    0x8081: 'PerKeyLightingV2', 0x8090: 'ColorID',
    0x8100: 'OnboardProfiles(storage)',
    0x8110: 'MouseButtonSpy',
    0x8300: 'GKeys', 0x8310: 'MKeys', 0x8320: 'GKeyLabels',
}
features = {}
for i in range(1, feature_count + 1):
    resp = send(bytes([0x11, 0xff, feat_set_idx, 0x10, i]))  # getFeatureID(i)
    if not resp:
        continue
    uuid = struct.unpack_from('>H', resp, 4)[0]
    obs  = bool(resp[6] & 0x20)
    hid  = bool(resp[6] & 0x40)
    name = known.get(uuid, '???')
    print(f'  0x{i:02x}  0x{uuid:04x}  {"yes" if obs else "no":>8}  {"yes" if hid else "no":>6}  {name}')
    features[i] = uuid

# ── 2. Dump ROM sectors ───────────────────────────────────────────────────────
print('\n=== ROM Sector Dumps ===')
feat_8100 = op.get_feature_index(hidraw, 0x8100)
print(f'feat_8100 = 0x{feat_8100:02x}  (ONBOARD_PROFILES)\n')

for profile_num, rom_sector in enumerate([0x0101, 0x0102, 0x0103], 1):
    data = op._read_full_sector(fd, feat_8100, rom_sector)
    crc_ok = op._crc_valid(data)
    print(f'--- ROM sector 0x{rom_sector:04x} (profile {profile_num}) CRC {"OK" if crc_ok else "FAIL"} ---')
    for row in range(0, 256, 16):
        hex_part = ' '.join(f'{b:02x}' for b in data[row:row+16])
        asc_part = ''.join(chr(b) if 32 <= b < 127 else '.' for b in data[row:row+16])
        print(f'  {row:02x}: {hex_part}  |{asc_part}|')
    print()

os.close(fd)
print('Done.')
