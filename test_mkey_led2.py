#!/usr/bin/env python3
"""
M-key indicator LED test round 2.

Two new hypotheses:
  A) 11 ff 0f 5e 01 03 [bitmask] is the actual M-key LED command
     (lighting.py comment) — maybe it works without full init after all
  B) M-key LEDs require per-key RGB software mode first (09 0f + 03 2e),
     THEN 0b 1e works

Run with daemon stopped: systemctl --user stop kyxen
Testing M2 (0x02) to see a change from default M1 state.
"""
import os, select, time

HIDRAW = '/dev/hidraw8'
PAD    = b'\x00' * 15


def write20(fd, data):
    os.write(fd, bytes(data) + b'\x00' * max(0, 20 - len(data)))


def send(fd, data, timeout=0.3):
    write20(fd, data)
    r, _, _ = select.select([fd], [], [], timeout)
    resp = os.read(fd, 64) if r else None
    if resp:
        print(f"  ack: {resp[:12].hex(' ')}")
    return resp


def drain(fd, timeout=0.35):
    while True:
        r, _, _ = select.select([fd], [], [], timeout)
        if not r:
            break
        d = os.read(fd, 64)
        print(f"  drn: {d[:12].hex(' ')}")


# ── Test A: 0f 5e 01 03 02 bare (no init at all) ────────────────────────────
print("=== Test A: bare 0f 5e 01 03 02 (no enable, no init) ===")
fd = os.open(HIDRAW, os.O_RDWR | os.O_NONBLOCK)
drain(fd, 0.1)
send(fd, [0x11, 0xff, 0x0f, 0x5e, 0x01, 0x03, 0x02])
time.sleep(0.5)
a = input("M2 indicator lit? [y/N] ").strip().lower() == 'y'
send(fd, [0x11, 0xff, 0x0f, 0x5e, 0x01, 0x03, 0x01])   # back to M1
drain(fd, 0.1)
os.close(fd)

if a:
    print("\n*** Test A WORKS: bare 0f 5e 01 03 bitmask ***")
    raise SystemExit(0)

# ── Test B: lighting init (09 0f + 03 2e) then 0f 5e 01 03 02 ──────────────
print("\n=== Test B: lighting init then 0f 5e 01 03 02 ===")
fd = os.open(HIDRAW, os.O_RDWR | os.O_NONBLOCK)
drain(fd, 0.1)
print("  sending per-key RGB SW mode init...")
send(fd, [0x11, 0xff, 0x09, 0x0f])       # software control mode
send(fd, [0x11, 0xff, 0x03, 0x2e])       # software lighting mode
drain(fd, 0.2)
send(fd, [0x11, 0xff, 0x0f, 0x5e, 0x01, 0x03, 0x02])
time.sleep(0.5)
b = input("M2 indicator lit? [y/N] ").strip().lower() == 'y'
send(fd, [0x11, 0xff, 0x0f, 0x5e, 0x01, 0x03, 0x01])
drain(fd, 0.1)
os.close(fd)

if b:
    print("\n*** Test B WORKS: lighting init + 0f 5e bitmask ***")
    raise SystemExit(0)

# ── Test C: lighting init then 0a SW enable then 0b 1e 02 ───────────────────
print("\n=== Test C: lighting init + SW mode enable + 0b 1e 02 ===")
fd = os.open(HIDRAW, os.O_RDWR | os.O_NONBLOCK)
drain(fd, 0.1)
print("  lighting init...")
send(fd, [0x11, 0xff, 0x09, 0x0f])
send(fd, [0x11, 0xff, 0x03, 0x2e])
drain(fd, 0.2)
print("  SW mode enable...")
send(fd, [0x11, 0xff, 0x0a, 0x2e, 0x01])
drain(fd, 0.4)
print("  set M2...")
send(fd, [0x11, 0xff, 0x0b, 0x1e, 0x02])
drain(fd, 0.3)
time.sleep(0.5)
c = input("M2 indicator lit? [y/N] ").strip().lower() == 'y'
send(fd, [0x11, 0xff, 0x0b, 0x1e, 0x01])
drain(fd, 0.1)
os.close(fd)

if c:
    print("\n*** Test C WORKS: lighting init + SW enable + 0b 1e ***")
    raise SystemExit(0)

# ── Test D: 0f 5f minimal init then 0f 5e bitmask ───────────────────────────
# From new connection capture: GHub queries 0f 5f before using 0f 5e
print("\n=== Test D: 0f 5f init queries then 0f 5e 01 03 02 ===")
fd = os.open(HIDRAW, os.O_RDWR | os.O_NONBLOCK)
drain(fd, 0.1)
print("  0f 5f queries (from new connection capture)...")
send(fd, [0x11, 0xff, 0x0f, 0x5f, 0x00, 0x00])           # query 1
send(fd, [0x11, 0xff, 0x0f, 0x5f, 0x01, 0x00, 0x06, 0x00]) # query 2
drain(fd, 0.3)
print("  enable SW mode...")
send(fd, [0x11, 0xff, 0x0a, 0x2e, 0x01])
drain(fd, 0.4)
print("  0f 5e 01 03 02...")
send(fd, [0x11, 0xff, 0x0f, 0x5e, 0x01, 0x03, 0x02])
time.sleep(0.5)
d = input("M2 indicator lit? [y/N] ").strip().lower() == 'y'
send(fd, [0x11, 0xff, 0x0f, 0x5e, 0x01, 0x03, 0x01])
drain(fd, 0.1)
os.close(fd)

if d:
    print("\n*** Test D WORKS: 0f 5f init + SW enable + 0f 5e bitmask ***")
    raise SystemExit(0)

# ── Test E: try different 0f 5e parameters ──────────────────────────────────
print("\n=== Test E: trying all 0f 5e params for M2 ===")
print("(lighting init + SW enable first)")
fd = os.open(HIDRAW, os.O_RDWR | os.O_NONBLOCK)
drain(fd, 0.1)
send(fd, [0x11, 0xff, 0x09, 0x0f])
send(fd, [0x11, 0xff, 0x03, 0x2e])
send(fd, [0x11, 0xff, 0x0a, 0x2e, 0x01])
drain(fd, 0.4)

# Try zone 0, mode 3, value 2 (M2 bitmask)
for zone in (0x00, 0x01, 0x02, 0xff):
    for mode in (0x00, 0x01, 0x02, 0x03, 0x04):
        write20(fd, [0x11, 0xff, 0x0f, 0x5e, zone, mode, 0x02])
        time.sleep(0.08)
        r, _, _ = select.select([fd], [], [], 0.05)
        if r:
            os.read(fd, 64)

time.sleep(0.5)
e = input("ANY M2 indicator lighting seen? [y/N] ").strip().lower() == 'y'
os.close(fd)

if e:
    print("Something in zone/mode sweep worked — narrow it down manually.")
    raise SystemExit(0)

print("\nAll tests failed.")
print("Next: probe per-key RGB for M-key indicator addresses,")
print("or dump full G815 feature table to identify unknown features.")
