#!/usr/bin/env python3
"""
Probe 0x8071 (RGBEffects) and 0x8081 (PerKeyLightingV2) with SW-mode init.
Run with daemon stopped: systemctl --user stop kyxen
  python3 ~/kyxen/probe_rgb_effects2.py
"""
import os, select, sys, time
sys.path.insert(0, '/home/wade/kyxen/src')

from kyxen_keys.keyboards import detect_keyboard
from kyxen_keys import onboard_profiles as op

kb     = detect_keyboard()
hidraw = kb.paths.hidraw
fd     = os.open(hidraw, os.O_RDWR)

# Flush any buffered packets before we start probing
def flush(ms=200):
    deadline = time.monotonic() + ms / 1000
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        r, _, _ = select.select([fd], [], [], remaining)
        if not r:
            break
        os.read(fd, 64)

def send(pkt, timeout=1.0):
    """Send and return the NEXT response whose feature byte matches pkt[2] (or any error)."""
    feature = pkt[2]
    os.write(fd, bytes(pkt).ljust(20, b'\x00')[:20])
    deadline = time.monotonic() + timeout
    while True:
        r, _, _ = select.select([fd], [], [], max(0, deadline - time.monotonic()))
        if not r:
            return None
        d = os.read(fd, 64)
        if not d or d[0] not in (0x10, 0x11, 0x12):
            continue
        # Accept error packets (byte[2]=0xff) or responses from our feature
        if d[2] == 0xff or d[2] == feature:
            return d
        # Discard ACKs from other features (lighting engine etc)

f8071 = op.get_feature_index(hidraw, 0x8071)
f8081 = op.get_feature_index(hidraw, 0x8081)
print(f'0x8071 (RGBEffects)       → index 0x{f8071:02x}')
print(f'0x8081 (PerKeyLightingV2) → index 0x{f8081:02x}')

# Flush the IRoot responses that feat() lookups left in the buffer
flush(300)
print('Buffer flushed.\n')

# ── SW mode init (same as lighting_engine._init) ──────────────────────────────
print('=== SW mode init ===')
os.write(fd, bytes([0x11, 0xff, 0x09, 0x0f]) + bytes(16))
time.sleep(0.15)
os.write(fd, bytes([0x11, 0xff, 0x03, 0x2e]) + bytes(16))
time.sleep(0.15)
flush(100)
print('SW mode active.\n')

# ── 0x8071 RGBEffects ─────────────────────────────────────────────────────────
print('=== 0x8071 RGBEffects ===')

r = send([0x11, 0xff, f8071, 0x00])
print(f'getCapabilities:  {r[:16].hex(" ") if r else "no response"}')
if r and r[2] != 0xff:
    print(f'  byte[4]=effect_count={r[4]}  byte[5]=cluster_count={r[5]}  caps_flags={r[6]:02x}')

r = send([0x11, 0xff, f8071, 0x10])
print(f'func=1:           {r[:16].hex(" ") if r else "no response"}')

r = send([0x11, 0xff, f8071, 0x20])
print(f'func=2:           {r[:16].hex(" ") if r else "no response"}')

r = send([0x11, 0xff, f8071, 0x30, 0x00])
print(f'getNthEffect(0):  {r[:16].hex(" ") if r else "no response"}')

r = send([0x11, 0xff, f8071, 0x30, 0x01])
print(f'getNthEffect(1):  {r[:16].hex(" ") if r else "no response"}')

r = send([0x11, 0xff, f8071, 0x30, 0x02])
print(f'getNthEffect(2):  {r[:16].hex(" ") if r else "no response"}')

# Try setCurrentEffect with cluster=0, static colour, blue
# Format (guessing): [cluster, effect_id, r, g, b, speed(hi), speed(lo), ...]
print('\n--- setCurrentEffect(cluster=0, effect=1=static, blue) ---')
r = send([0x11, 0xff, f8071, 0x40, 0x00, 0x01, 0x00, 0x00, 0xff, 0x00, 0x64])
print(f'result: {r[:16].hex(" ") if r else "no response"}')
time.sleep(1.0)
if input('Keys lit blue? [y/N] ').strip().lower() == 'y':
    print('SUCCESS: 0x8071 static effect works!')
else:
    # Try effect_id=0 (might be the static/off effect on this keyboard)
    print('\n--- setCurrentEffect(cluster=0, effect=0) ---')
    r = send([0x11, 0xff, f8071, 0x40, 0x00, 0x00, 0x00, 0x00, 0xff, 0x00, 0x64])
    print(f'result: {r[:16].hex(" ") if r else "no response"}')
    time.sleep(1.0)
    input('Any change? (press Enter)')

# Try breathing effect (common effect ID = 2 or 3)
print('\n--- setCurrentEffect(cluster=0, effect=2=breathing?, blue, medium speed) ---')
r = send([0x11, 0xff, f8071, 0x40, 0x00, 0x02, 0x00, 0x00, 0xff, 0x01, 0x00])
print(f'result: {r[:16].hex(" ") if r else "no response"}')
time.sleep(2.0)
breathing = input('Breathing blue? [y/N] ').strip().lower() == 'y'
if breathing:
    print('SUCCESS: 0x8071 breathing effect works!')

print('\n--- setCurrentEffect(cluster=0, effect=3?, blue) ---')
r = send([0x11, 0xff, f8071, 0x40, 0x00, 0x03, 0x00, 0x00, 0xff, 0x01, 0x00])
print(f'result: {r[:16].hex(" ") if r else "no response"}')
time.sleep(2.0)
input('Any effect? (press Enter)')

print('\n--- setCurrentEffect(cluster=0, effect=8=rainbow_wave?) ---')
r = send([0x11, 0xff, f8071, 0x40, 0x00, 0x08, 0x00, 0x00, 0xff, 0x01, 0x00])
print(f'result: {r[:16].hex(" ") if r else "no response"}')
time.sleep(2.0)
input('Any effect? (press Enter)')

# ── 0x8081 PerKeyLightingV2 ───────────────────────────────────────────────────
print('\n=== 0x8081 PerKeyLightingV2 ===')

r = send([0x11, 0xff, f8081, 0x00])
print(f'getCapabilities:  {r[:16].hex(" ") if r else "no response"}')

# Try the write format used by existing lighting.py: func=0x5e, key_id twice, r g b
# ESC key_id = 0x26 per KEY_IDS map
print('\n--- Set ESC=red using func=0x5e (existing write format) ---')
pkt = bytearray(20)
pkt[0], pkt[1], pkt[2], pkt[3] = 0x11, 0xff, f8081, 0x5e
pkt[4] = pkt[5] = 0x26  # ESC
pkt[6], pkt[7], pkt[8] = 0xff, 0x00, 0x00
os.write(fd, bytes(pkt))
time.sleep(0.05)

# Commit via func=0x7e
commit = bytearray(20)
commit[0], commit[1], commit[2], commit[3] = 0x11, 0xff, f8081, 0x7e
os.write(fd, bytes(commit))
time.sleep(0.5)
esc_red = input('ESC lit red? [y/N] ').strip().lower() == 'y'
if esc_red:
    print('SUCCESS: 0x8081 per-key write confirmed working with static write.')

# Set all keys green to confirm persistence without streaming
print('\n--- Set ALL keys green (write-once static test) ---')
from kyxen_keys.lighting import KEY_IDS
p = bytearray(20)
p[0], p[1], p[2], p[3] = 0x11, 0xff, f8081, 0x5e
for kid in KEY_IDS.values():
    p[4] = p[5] = kid
    p[6], p[7], p[8] = 0x00, 0xff, 0x00
    os.write(fd, bytes(p))
commit[3] = 0x7e
os.write(fd, bytes(commit))
time.sleep(1.0)
all_green = input('All keys green? [y/N] ').strip().lower() == 'y'
if all_green:
    print('SUCCESS: write-once static mode confirmed — keyboard holds the colour with no streaming.')

os.close(fd)
print('\nDone.')
