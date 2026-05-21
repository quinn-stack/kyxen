#!/usr/bin/env python3
"""
Targeted M-key LED test based on GHub USB capture findings.
GHub exact LED packet: 11 ff 0b 1d [bitmask] 00...
  feature=0x0b (0x8020), func=1, SW_ID=0xd → byte3=0x1d
  No commit packet.
Testing M2 (0x02) so we can see a change from the default M1-lit state.
Run with daemon stopped: systemctl --user stop kyxen
"""
import os, select as _sel, time

HIDRAW    = '/dev/hidraw8'
FEAT_8010 = 0x0a
FEAT_8020 = 0x0b


def _write(fd, data):
    os.write(fd, bytes(data) + b'\x00' * max(0, 20 - len(data)))


def _send(fd, data, timeout=0.3):
    _write(fd, data)
    r, _, _ = _sel.select([fd], [], [], timeout)
    return os.read(fd, 64) if r else None


def drain(fd):
    while True:
        r, _, _ = _sel.select([fd], [], [], 0.05)
        if not r: break
        os.read(fd, 64)


# ── Test A: standalone, GHub's exact SW_ID (0xd), no commit ─────────────────
print("=== Test A: standalone, 0x1d (SW_ID=d), no commit ===")
print("Expected: M2 lights up while M1 stays lit.")
fd = os.open(HIDRAW, os.O_RDWR)
# Enable with SW_ID 0xd to match what we send
_send(fd, [0x11, 0xff, FEAT_8010, 0x2d, 0x01])   # func2 SW=d
_send(fd, [0x11, 0xff, FEAT_8020, 0x1d, 0x01])   # func1 SW=d param=M1 (resets to M1)
time.sleep(0.1)
_write(fd, [0x11, 0xff, FEAT_8020, 0x1d, 0x02])  # set M2 — GHub's exact byte3
time.sleep(0.5)
a = input("M2 lit? [y/N] ").strip().lower() == 'y'
_write(fd, [0x11, 0xff, FEAT_8020, 0x1d, 0x00])
os.close(fd)

if a:
    print("\n*** WORKS: enable SW=d + LED 0x1d no commit ***")
    raise SystemExit

# ── Test B: GHub exact, SW_ID=d, but with old SW_ID=e enable ────────────────
print("\n=== Test B: SW_ID=d LED cmd, but SW_ID=e enable (old enable) ===")
fd = os.open(HIDRAW, os.O_RDWR)
_send(fd, [0x11, 0xff, FEAT_8010, 0x2e, 0x01])   # func2 SW=e  (our current)
_send(fd, [0x11, 0xff, FEAT_8020, 0x1e, 0x01])   # func1 SW=e
time.sleep(0.1)
_write(fd, [0x11, 0xff, FEAT_8020, 0x1d, 0x02])  # LED with SW=d
time.sleep(0.5)
b = input("M2 lit? [y/N] ").strip().lower() == 'y'
_write(fd, [0x11, 0xff, FEAT_8020, 0x1d, 0x00])
os.close(fd)

if b:
    print("\n*** WORKS: old enable + LED 0x1d no commit ***")
    raise SystemExit

# ── Test C: respond immediately to a real notification ───────────────────────
print("\n=== Test C: press M2 — script will respond instantly ===")
print("Enabling software mode, then waiting for you to press M2...")
fd = os.open(HIDRAW, os.O_RDWR)
_send(fd, [0x11, 0xff, FEAT_8010, 0x2d, 0x01])
_send(fd, [0x11, 0xff, FEAT_8020, 0x1d, 0x01])
drain(fd)

print("Press M2 now (waiting 10s)...")
deadline = time.time() + 10
got_notif = False
while time.time() < deadline:
    r, _, _ = _sel.select([fd], [], [], 0.5)
    if not r: continue
    data = os.read(fd, 64)
    if (len(data) >= 5 and data[0] == 0x11 and data[2] == FEAT_8020 and data[3] == 0x00
            and data[4] != 0x00):
        bitmask = data[4]
        print(f"  Got notification: bitmask=0x{bitmask:02x}")
        # Immediately ack — GHub's exact format
        _write(fd, [0x11, 0xff, FEAT_8020, 0x1d, bitmask])
        got_notif = True
        break

if got_notif:
    time.sleep(0.5)
    c = input("Did the M-key LED light up? [y/N] ").strip().lower() == 'y'
    if c:
        print("\n*** WORKS: immediate ack after notification ***")
        print("Fix: respond to notifications in run_mkey_listener instead of queue.")
    else:
        print("\nAck after notification also failed.")
else:
    print("No notification received.")
    c = False

os.close(fd)

if not a and not b and not c:
    print("\nAll failed. Check the Lighting pcapng on the flash drive for M-key LED packets.")
