#!/usr/bin/env python3
"""
M-key LED test round 3.
Feature 0x0c = 0x8030 (SoftwareControllableLED) confirmed.
Run with daemon stopped: systemctl --user stop kyxen
"""
import os, select, time

HIDRAW = '/dev/hidraw8'

def write20(fd, data):
    os.write(fd, bytes(data) + b'\x00' * max(0, 20 - len(data)))

def send(fd, data, timeout=0.35):
    write20(fd, data)
    r, _, _ = select.select([fd], [], [], timeout)
    resp = os.read(fd, 64) if r else None
    if resp:
        print(f"  <- {resp[:12].hex(' ')}")
    return resp

def drain(fd, t=0.3):
    while True:
        r, _, _ = select.select([fd], [], [], t)
        if not r: break
        d = os.read(fd, 64)
        print(f"  drn {d[:12].hex(' ')}")


# ── H1: 0b 1e 02 with NO SW enable (hardware mode) ──────────────────────────
print("=== H1: 0b 1e 02 in hardware mode (no SW enable) ===")
fd = os.open(HIDRAW, os.O_RDWR | os.O_NONBLOCK)
drain(fd, 0.05)
send(fd, [0x11, 0xff, 0x0b, 0x1e, 0x02])
time.sleep(0.8)
h1 = input("M2 lit? [y/N] ").strip().lower() == 'y'
send(fd, [0x11, 0xff, 0x0b, 0x1e, 0x01])
drain(fd, 0.1)
os.close(fd)
if h1:
    print("*** H1 WORKS ***")
    raise SystemExit(0)


# ── H2: feat 0x11 profile=2, then SW enable, then 0b 1e 02 ──────────────────
print("\n=== H2: feat 0x11 activate profile 2 -> SW enable -> 0b 1e 02 ===")
fd = os.open(HIDRAW, os.O_RDWR | os.O_NONBLOCK)
drain(fd, 0.05)
print("  0x11 func=1 param=2 (activate profile 2):")
send(fd, [0x11, 0xff, 0x11, 0x1e, 0x02])
print("  0x11 func=2 (get active):")
send(fd, [0x11, 0xff, 0x11, 0x2e])
drain(fd, 0.2)
print("  SW mode enable:")
send(fd, [0x11, 0xff, 0x0a, 0x2e, 0x01])
drain(fd, 0.4)
print("  0b 1e 02:")
send(fd, [0x11, 0xff, 0x0b, 0x1e, 0x02])
drain(fd, 0.3)
time.sleep(0.5)
h2 = input("M2 lit? [y/N] ").strip().lower() == 'y'
send(fd, [0x11, 0xff, 0x0b, 0x1e, 0x01])
drain(fd, 0.1)
os.close(fd)
if h2:
    print("*** H2 WORKS: feat 0x11 profile activate is the prerequisite ***")
    raise SystemExit(0)


# ── H3: feat 0x0c func=0 param=02 as LED setter ─────────────────────────────
print("\n=== H3: SW enable + 0b 1e 02 + 0c 0e 02 as LED setter ===")
fd = os.open(HIDRAW, os.O_RDWR | os.O_NONBLOCK)
drain(fd, 0.05)
send(fd, [0x11, 0xff, 0x0a, 0x2e, 0x01])
drain(fd, 0.4)
send(fd, [0x11, 0xff, 0x0b, 0x1e, 0x02])
send(fd, [0x11, 0xff, 0x0c, 0x0e, 0x02])
drain(fd, 0.3)
time.sleep(0.5)
h3 = input("M2 lit? [y/N] ").strip().lower() == 'y'
send(fd, [0x11, 0xff, 0x0b, 0x1e, 0x01])
send(fd, [0x11, 0xff, 0x0c, 0x0e, 0x01])
drain(fd, 0.1)
os.close(fd)
if h3:
    print("*** H3 WORKS: 0c 0e [bitmask] sets indicator ***")
    raise SystemExit(0)


# ── H4: 3-second delay test ──────────────────────────────────────────────────
print("\n=== H4: SW enable + 0b 1e 02, wait 3s (delay test) ===")
fd = os.open(HIDRAW, os.O_RDWR | os.O_NONBLOCK)
drain(fd, 0.05)
send(fd, [0x11, 0xff, 0x0a, 0x2e, 0x01])
drain(fd, 0.4)
send(fd, [0x11, 0xff, 0x0b, 0x1e, 0x02])
print("  Waiting 3 seconds — watch for any LED change...")
time.sleep(3.0)
h4 = input("M2 lit at any point? [y/N] ").strip().lower() == 'y'
send(fd, [0x11, 0xff, 0x0b, 0x1e, 0x01])
drain(fd, 0.1)
os.close(fd)
if h4:
    print("*** H4: delayed effect ***")
    raise SystemExit(0)


# ── H5: feat 0x11 activate profile 1 (M1), SW enable, then 0b 1e 01 ─────────
# Maybe setting M1 (matching HW default) is the only one that works
print("\n=== H5: feat 0x11 profile 1, SW enable, 0b 1e 01 (confirm M1) ===")
print("(Watch whether M1 re-lights after the script opens)")
fd = os.open(HIDRAW, os.O_RDWR | os.O_NONBLOCK)
drain(fd, 0.05)
send(fd, [0x11, 0xff, 0x11, 0x1e, 0x01])    # activate profile 1
send(fd, [0x11, 0xff, 0x0a, 0x2e, 0x01])    # SW enable
drain(fd, 0.4)
send(fd, [0x11, 0xff, 0x0b, 0x1e, 0x01])    # M1 confirm
drain(fd, 0.3)
time.sleep(0.5)
h5 = input("M1 lit? [y/N] ").strip().lower() == 'y'
os.close(fd)
if h5:
    print("*** H5: M1 lit with profile activate — need 0x11 first ***")
    raise SystemExit(0)

print("\nAll tests failed.")
print("Hypothesis: firmware requires full GHub-style enumeration before 0b 1e works.")
print("Try running with GHub first, then kill GHub but keep session alive?")
