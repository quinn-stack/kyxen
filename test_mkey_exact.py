#!/usr/bin/env python3
"""
Exact GHub M-key LED sequence from new connection .pcapng.

GHub startup (pkt#1498-1516):
  1) 11 ff 0a 2e 01 00...  enable SW mode (feat=0x0a, func=2, SW=e)
     <- 11 ff 0a 00 ...   (unsolicited notification)
     <- 11 ff 0a 2e 01 ... (ack)
  2) 11 ff 0b 1e 01 00...  set M-key LED=M1 (feat=0x0b, func=1, SW=e)
     <- 11 ff 0b 00 ...   (unsolicited notification)
     <- 11 ff 0b 1e 01 ... (ack)

No commit. No 0x0f commands. Pure 0x0a enable + 0x0b LED set.
Testing with M2 (0x02) so we can see a change from default M1 state.
Run with daemon stopped: systemctl --user stop kyxen
"""
import os, select, time

HIDRAW   = '/dev/hidraw8'
F_8010   = 0x0a   # feature index for 0x8010
F_8020   = 0x0b   # feature index for 0x8020
PAD      = b'\x00' * 15


def write20(fd, data):
    os.write(fd, bytes(data) + PAD)


def drain(fd, timeout=0.4):
    """Read all pending packets until silence."""
    msgs = []
    while True:
        r, _, _ = select.select([fd], [], [], timeout)
        if not r:
            break
        d = os.read(fd, 64)
        msgs.append(d)
        print(f"  <- {d[:20].hex(' ')}")
    return msgs


# ── Test 1: bare minimum – enable + set M2, no wait ────────────────────────
print("=== Test 1: enable SW + set M2 immediately (no drain) ===")
fd = os.open(HIDRAW, os.O_RDWR | os.O_NONBLOCK)
drain(fd, 0.05)   # clear any stale data

write20(fd, [0x11, 0xff, F_8010, 0x2e, 0x01])   # enable SW mode
write20(fd, [0x11, 0xff, F_8020, 0x1e, 0x02])   # set M2

time.sleep(0.5)
t1 = input("M2 lit? [y/N] ").strip().lower() == 'y'
write20(fd, [0x11, 0xff, F_8020, 0x1e, 0x00])   # LEDs off
drain(fd, 0.1)
os.close(fd)

if t1:
    print("\n*** Test 1 WORKS: immediate enable+M2, no drain ***")
    raise SystemExit(0)

# ── Test 2: enable, drain both responses, then set M2 ──────────────────────
print("\n=== Test 2: enable SW, drain, then set M2 ===")
fd = os.open(HIDRAW, os.O_RDWR | os.O_NONBLOCK)
drain(fd, 0.05)

write20(fd, [0x11, 0xff, F_8010, 0x2e, 0x01])   # enable SW mode
print("  responses to enable:")
drain(fd, 0.4)                                    # wait for 0a 00 + 0a 2e

write20(fd, [0x11, 0xff, F_8020, 0x1e, 0x02])   # set M2
print("  responses to M-key set:")
drain(fd, 0.4)

time.sleep(0.5)
t2 = input("M2 lit? [y/N] ").strip().lower() == 'y'
write20(fd, [0x11, 0xff, F_8020, 0x1e, 0x00])
drain(fd, 0.1)
os.close(fd)

if t2:
    print("\n*** Test 2 WORKS: drain after enable, then set M2 ***")
    raise SystemExit(0)

# ── Test 3: init to M1 first (exact GHub order), then M2 ───────────────────
print("\n=== Test 3: enable, drain, set M1 first, drain, then M2 ===")
fd = os.open(HIDRAW, os.O_RDWR | os.O_NONBLOCK)
drain(fd, 0.05)

write20(fd, [0x11, 0xff, F_8010, 0x2e, 0x01])   # enable SW mode
drain(fd, 0.4)
write20(fd, [0x11, 0xff, F_8020, 0x1e, 0x01])   # set M1 (GHub does this first)
drain(fd, 0.3)
time.sleep(0.1)
write20(fd, [0x11, 0xff, F_8020, 0x1e, 0x02])   # now M2
drain(fd, 0.3)

time.sleep(0.5)
t3 = input("M2 lit? [y/N] ").strip().lower() == 'y'
write20(fd, [0x11, 0xff, F_8020, 0x1e, 0x00])
drain(fd, 0.1)
os.close(fd)

if t3:
    print("\n*** Test 3 WORKS: enable + M1 init + M2 ***")
    raise SystemExit(0)

# ── Test 4: respond to M-key press notification ────────────────────────────
print("\n=== Test 4: enable SW, drain, then press M2 — we ack the notification ===")
print("Waiting up to 10s for M2 press...")
fd = os.open(HIDRAW, os.O_RDWR | os.O_NONBLOCK)
drain(fd, 0.05)

write20(fd, [0x11, 0xff, F_8010, 0x2e, 0x01])
drain(fd, 0.4)
write20(fd, [0x11, 0xff, F_8020, 0x1e, 0x01])   # set M1 first
drain(fd, 0.3)

deadline = time.time() + 10
t4 = False
while time.time() < deadline:
    r, _, _ = select.select([fd], [], [], 0.5)
    if not r:
        continue
    d = os.read(fd, 64)
    print(f"  <- {d[:10].hex(' ')} ...")
    # M-key notification: feat=0x0b, func=0, SW=0 → byte[3]=0x00; byte[4]=bitmask
    if len(d) >= 5 and d[0] == 0x11 and d[1] == 0xff and d[2] == F_8020 and d[3] == 0x00 and d[4]:
        bitmask = d[4]
        print(f"  M-key notification! bitmask=0x{bitmask:02x} → acking with SW=e")
        write20(fd, [0x11, 0xff, F_8020, 0x1e, bitmask])
        time.sleep(0.5)
        t4 = input("M-key LED correct? [y/N] ").strip().lower() == 'y'
        break

write20(fd, [0x11, 0xff, F_8020, 0x1e, 0x00])
drain(fd, 0.1)
os.close(fd)

if t4:
    print("\n*** Test 4 WORKS: ack notification with SW=e ***")
    raise SystemExit(0)

print("\nAll tests failed.")
print("Try: check hidraw device, check daemon is stopped, check OS is not grabbing the device.")
