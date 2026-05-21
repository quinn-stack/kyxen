#!/usr/bin/env python3
"""
Probe feature 0x8071 (RGBEffects) and 0x8081 (PerKeyLightingV2).
Run with daemon stopped: systemctl --user stop kyxen
  python3 ~/kyxen/probe_rgb_effects.py
"""
import os, select, struct, sys, time
sys.path.insert(0, '/home/wade/kyxen/src')

from kyxen_keys.keyboards import detect_keyboard
from kyxen_keys import onboard_profiles as op

kb     = detect_keyboard()
hidraw = kb.paths.hidraw
fd     = os.open(hidraw, os.O_RDWR)

def send(pkt, timeout=1.0):
    os.write(fd, bytes(pkt).ljust(20, b'\x00')[:20])
    deadline = time.monotonic() + timeout
    while True:
        r, _, _ = select.select([fd], [], [], max(0, deadline - time.monotonic()))
        if not r: return None
        d = os.read(fd, 64)
        if d and d[0] in (0x10, 0x11, 0x12): return d

def feat(uuid):
    return op.get_feature_index(hidraw, uuid)

f8071 = feat(0x8071)
f8081 = feat(0x8081)
print(f'0x8071 (RGBEffects)       → feature index 0x{f8071:02x}')
print(f'0x8081 (PerKeyLightingV2) → feature index 0x{f8081:02x}')

# ── 0x8071 RGBEffects ─────────────────────────────────────────────────────────
print('\n=== 0x8071 RGBEffects ===')

# func=0 getCapabilities
r = send([0x11, 0xff, f8071, 0x00])
print(f'getCapabilities: {r[:16].hex(" ") if r else "no response"}')
if r:
    # Typical response: [11 ff idx 00] [effects_count] [clusters] [caps_flags ...]
    print(f'  → raw bytes 4-15: {list(r[4:16])}')

# func=1 getEffectCount (or getDivisionCount depending on firmware)
r = send([0x11, 0xff, f8071, 0x10])
print(f'func=1 response: {r[:16].hex(" ") if r else "no response"}')

# func=2 (sometimes getEffect or getCluster)
r = send([0x11, 0xff, f8071, 0x20])
print(f'func=2 response: {r[:16].hex(" ") if r else "no response"}')

# func=3 getNthEffect(0)
r = send([0x11, 0xff, f8071, 0x30, 0x00])
print(f'getNthEffect(0): {r[:16].hex(" ") if r else "no response"}')

# func=3 getNthEffect(1)
r = send([0x11, 0xff, f8071, 0x30, 0x01])
print(f'getNthEffect(1): {r[:16].hex(" ") if r else "no response"}')

# func=4 setCurrentEffect — try setting ALL keys to static blue to test the API
# setCurrentEffect(cluster=0, effect=1(static), r=0, g=0, b=255, ...)
print('\nTrying setCurrentEffect(cluster=0, static blue)...')
r = send([0x11, 0xff, f8071, 0x40, 0x00, 0x01, 0x00, 0x00, 0xff, 0x64])
print(f'setCurrentEffect result: {r[:16].hex(" ") if r else "no response"}')
time.sleep(1.0)
lit = input('Any keys lit blue? [y/N] ').strip().lower() == 'y'
if not lit:
    # Try cluster=0xff (all clusters), same params
    r = send([0x11, 0xff, f8071, 0x40, 0xff, 0x01, 0x00, 0x00, 0xff, 0x64])
    print(f'setCurrentEffect(cluster=0xff) result: {r[:16].hex(" ") if r else "no response"}')
    time.sleep(1.0)
    lit = input('Any keys lit blue now? [y/N] ').strip().lower() == 'y'

# ── 0x8081 PerKeyLightingV2 ───────────────────────────────────────────────────
print('\n=== 0x8081 PerKeyLightingV2 ===')

# func=0 getCapabilities
r = send([0x11, 0xff, f8081, 0x00])
print(f'getCapabilities: {r[:16].hex(" ") if r else "no response"}')

# func=1 — try get something
r = send([0x11, 0xff, f8081, 0x10])
print(f'func=1: {r[:16].hex(" ") if r else "no response"}')

# func=2
r = send([0x11, 0xff, f8081, 0x20])
print(f'func=2: {r[:16].hex(" ") if r else "no response"}')

# func=3 setIndividualRgb (common in PerKeyLightingV2):
# setRgbIndividualKeys with key ESC (id=0x26): r=255, g=0, b=0
print('\nTrying PerKeyLightingV2 set ESC=red...')
# Format varies — try: [key_id, r, g, b] × N keys, then commit
r = send([0x11, 0xff, f8081, 0x30, 0x26, 0xff, 0x00, 0x00])
print(f'func=3 result: {r[:16].hex(" ") if r else "no response"}')
# Try commit via func=4
r = send([0x11, 0xff, f8081, 0x40])
print(f'func=4 (commit?): {r[:16].hex(" ") if r else "no response"}')
time.sleep(1.0)
input('ESC lit red? [any key to continue]')

os.close(fd)
print('\nDone.')
