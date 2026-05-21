#!/usr/bin/env python3
"""
Test whether 0x8081 PerKeyLightingV2 accepts multi-key payloads per packet.
Current format: [key_id, key_id, r, g, b] — 5 bytes per key, 3 keys fit in 16-byte payload.
Run with daemon stopped: systemctl --user stop kyxen
  python3 ~/kyxen/probe_batch_write.py
"""
import os, select, sys, time
sys.path.insert(0, '/home/wade/kyxen/src')

from kyxen_keys.keyboards import detect_keyboard
from kyxen_keys import onboard_profiles as op
from kyxen_keys.lighting import KEY_IDS

kb     = detect_keyboard()
hidraw = kb.paths.hidraw
fd     = os.open(hidraw, os.O_RDWR)

def flush(ms=200):
    deadline = time.monotonic() + ms / 1000
    while True:
        r, _, _ = select.select([fd], [], [], max(0, deadline - time.monotonic()))
        if not r: break
        os.read(fd, 64)

f8081 = op.get_feature_index(hidraw, 0x8081)
flush(300)
print(f'0x8081 → index 0x{f8081:02x}\nBuffer flushed.\n')

# SW mode init
os.write(fd, bytes([0x11, 0xff, 0x09, 0x0f]) + bytes(16))
time.sleep(0.15)
os.write(fd, bytes([0x11, 0xff, 0x03, 0x2e]) + bytes(16))
time.sleep(0.15)
flush(100)

COMMIT = bytes([0x11, 0xff, f8081, 0x7e]) + bytes(16)

def commit_and_wait(msg):
    os.write(fd, COMMIT)
    time.sleep(0.5)
    result = input(f'{msg} [y/N] ').strip().lower() == 'y'
    flush(50)
    return result

# All keys off first
p = bytearray(20)
p[0], p[1], p[2], p[3] = 0x11, 0xff, f8081, 0x5e
for kid in KEY_IDS.values():
    p[4] = p[5] = kid; p[6] = p[7] = p[8] = 0
    os.write(fd, bytes(p))
os.write(fd, COMMIT)
time.sleep(0.3)
flush(100)
print('Keys cleared.\n')

# ── Test 1: 2 keys per packet ─────────────────────────────────────────────────
# Format attempt: [key1_id, key1_id, r1, g1, b1, key2_id, key2_id, r2, g2, b2, ...]
print('=== Test 1: 2 keys per packet (5+5 bytes) ===')
# Set ESC=red and F1=green in one packet
ESC = KEY_IDS['ESC']
F1  = KEY_IDS['F1']
pkt = bytearray(20)
pkt[0], pkt[1], pkt[2], pkt[3] = 0x11, 0xff, f8081, 0x5e
# key 1: ESC = red
pkt[4] = pkt[5] = ESC; pkt[6], pkt[7], pkt[8] = 0xff, 0x00, 0x00
# key 2: F1 = green
pkt[9] = pkt[10] = F1; pkt[11], pkt[12], pkt[13] = 0x00, 0xff, 0x00
os.write(fd, bytes(pkt))
if commit_and_wait('ESC=red AND F1=green both lit?'):
    print('SUCCESS: 2 keys per packet works!\n')
else:
    print('FAIL or partial. Clearing.\n')
    for kid in [ESC, F1]:
        p[4] = p[5] = kid; p[6] = p[7] = p[8] = 0
        os.write(fd, bytes(p))
    os.write(fd, COMMIT); time.sleep(0.2); flush(50)

# ── Test 2: 3 keys per packet ─────────────────────────────────────────────────
print('=== Test 2: 3 keys per packet (5+5+5 bytes, uses 15 of 16 payload bytes) ===')
F2 = KEY_IDS['F2']
pkt2 = bytearray(20)
pkt2[0], pkt2[1], pkt2[2], pkt2[3] = 0x11, 0xff, f8081, 0x5e
pkt2[4]  = pkt2[5]  = ESC; pkt2[6],  pkt2[7],  pkt2[8]  = 0xff, 0x00, 0x00
pkt2[9]  = pkt2[10] = F1;  pkt2[11], pkt2[12], pkt2[13] = 0x00, 0xff, 0x00
pkt2[14] = pkt2[15] = F2;  pkt2[16], pkt2[17], pkt2[18] = 0x00, 0x00, 0xff
os.write(fd, bytes(pkt2))
if commit_and_wait('ESC=red, F1=green, F2=blue all lit?'):
    print('SUCCESS: 3 keys per packet works!\n')
else:
    print('FAIL or partial.\n')

# ── Test 3: 4 keys per packet (4 bytes each, drop the duplicate key_id) ────────
print('=== Test 3: 4 keys per packet WITHOUT duplicate key_id (4 bytes each) ===')
print('Format: [key_id, r, g, b, key_id, r, g, b, ...] — 4 bytes per key')
F3 = KEY_IDS['F3']
pkt3 = bytearray(20)
pkt3[0], pkt3[1], pkt3[2], pkt3[3] = 0x11, 0xff, f8081, 0x5e
# key 1: ESC = red
pkt3[4],  pkt3[5],  pkt3[6],  pkt3[7]  = ESC, 0xff, 0x00, 0x00
# key 2: F1 = green
pkt3[8],  pkt3[9],  pkt3[10], pkt3[11] = F1,  0x00, 0xff, 0x00
# key 3: F2 = blue
pkt3[12], pkt3[13], pkt3[14], pkt3[15] = F2,  0x00, 0x00, 0xff
# key 4: F3 = white
pkt3[16], pkt3[17], pkt3[18], pkt3[19] = F3,  0xff, 0xff, 0xff
os.write(fd, bytes(pkt3))
if commit_and_wait('ESC=red, F1=green, F2=blue, F3=white all lit?'):
    print('SUCCESS: 4 keys per packet (no duplicate key_id) works!\n')
else:
    print('FAIL.\n')

# ── Summary ───────────────────────────────────────────────────────────────────
# Clear all
for kid in KEY_IDS.values():
    p[4] = p[5] = kid; p[6] = p[7] = p[8] = 0
    os.write(fd, bytes(p))
os.write(fd, COMMIT)

os.close(fd)
print('Done.')
