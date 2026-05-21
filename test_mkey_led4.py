#!/usr/bin/env python3
"""
M-key indicator LED test round 4.

Goal: determine whether `0b 1e [bitmask]` alone switches the indicator
AFTER a profile-1 activate, or whether the indicator is solely driven by
which profile was last activated via feat 0x11.

Run with daemon stopped: systemctl --user stop kyxen
Watch M1/M2/M3 LEDs throughout each test.
"""
import os, select, time

HIDRAW = '/dev/hidraw8'
F_PRFL = 0x11   # feat 0x8100 (onboard profiles)
F_8010 = 0x0a   # feat 0x8010 (SW mode enable)
F_8020 = 0x0b   # feat 0x8020 (M-key LED)

def w(fd, data):
    os.write(fd, bytes(data) + b'\x00' * max(0, 20 - len(data)))

def drain(fd, t=0.4):
    while True:
        r, _, _ = select.select([fd], [], [], t)
        if not r: break
        d = os.read(fd, 64)
        print(f"  drn {d[:10].hex(' ')}")

def ask(q):
    return input(q + ' [y/N] ').strip().lower() == 'y'


# ── T1: profile-1 activate + SW enable, then send 0b 1e 02 ──────────────────
# If `0b 1e 02` actually changes the indicator, M2 should light.
# If indicator is driven by profile activate, M1 will stay lit.
print("=== T1: profile-1 activate + SW enable + 0b 1e 02 ===")
print("Watching for M1→M2 transition...")
fd = os.open(HIDRAW, os.O_RDWR | os.O_NONBLOCK)
drain(fd, 0.05)
print("  activate profile 1:")
w(fd, [0x11, 0xff, F_PRFL, 0x1e, 0x01])
drain(fd, 0.3)
print("  SW enable:")
w(fd, [0x11, 0xff, F_8010, 0x2e, 0x01])
drain(fd, 0.4)
print("  set LED → M2 (0x02):")
w(fd, [0x11, 0xff, F_8020, 0x1e, 0x02])
drain(fd, 0.2)
time.sleep(0.5)
t1 = ask("M2 now lit (indicator switched from M1)?")
w(fd, [0x11, 0xff, F_8020, 0x1e, 0x00])
drain(fd, 0.1)
os.close(fd)

if t1:
    print("*** T1 WORKS — 0b 1e 02 changes indicator after profile-1 activate.")
    print("    Daemon LED queue mechanism is correct; look for a different bug.")
    raise SystemExit(0)
print("T1 FAILED — 0b 1e does NOT change indicator after profile-1 activate.\n")


# ── T2: profile-2 activate + SW enable, then send 0b 1e 01 ──────────────────
# If profile activate drives the indicator, M2 stays lit despite 0b 1e 01.
# If 0b 1e actually works from profile-2 base, M1 will light.
print("=== T2: profile-2 activate + SW enable + 0b 1e 01 ===")
print("Watching for M2 (after activate) then whether 0b 1e 01 switches back to M1...")
fd = os.open(HIDRAW, os.O_RDWR | os.O_NONBLOCK)
drain(fd, 0.05)
print("  activate profile 2:")
w(fd, [0x11, 0xff, F_PRFL, 0x1e, 0x02])
drain(fd, 0.3)
print("  SW enable:")
w(fd, [0x11, 0xff, F_8010, 0x2e, 0x01])
drain(fd, 0.4)
print("  set LED → M1 (0x01):")
w(fd, [0x11, 0xff, F_8020, 0x1e, 0x01])
drain(fd, 0.2)
time.sleep(0.5)
t2_m2_after_activate = ask("M2 lit immediately after profile-2 activate (before reading above)?")
t2_m1_after_cmd = ask("M1 now lit (indicator switched back to M1 after 0b 1e 01)?")
os.close(fd)

print(f"T2: M2 after activate={t2_m2_after_activate}, M1 after 0b1e01={t2_m1_after_cmd}")
print()


# ── T3: re-activate profile per LED change ───────────────────────────────────
# Hypothesis: to switch indicator to M2, send profile-2 activate (no SW needed).
# Then send profile-1 activate to go back to M1. SW mode is never re-sent.
print("=== T3: profile activate as the LED setter (no SW enable second time) ===")
fd = os.open(HIDRAW, os.O_RDWR | os.O_NONBLOCK)
drain(fd, 0.05)
# Full init once
w(fd, [0x11, 0xff, F_PRFL, 0x1e, 0x01])
drain(fd, 0.3)
w(fd, [0x11, 0xff, F_8010, 0x2e, 0x01])
drain(fd, 0.4)
# Now just re-activate profile 2 — no additional SW enable
print("  activate profile 2 (just the activate, no SW re-enable):")
w(fd, [0x11, 0xff, F_PRFL, 0x1e, 0x02])
drain(fd, 0.2)
time.sleep(0.5)
t3 = ask("M2 lit?")
w(fd, [0x11, 0xff, F_PRFL, 0x1e, 0x01])
drain(fd, 0.1)
os.close(fd)

if t3:
    print("*** T3: profile re-activate alone switches the indicator — no 0b 1e needed.")
    print("    Fix: send 11 ff 11 1e [1|2|3] whenever the M-key changes.")
    raise SystemExit(0)


# ── T4: profile activate + 0b 1e together each switch ────────────────────────
print("\n=== T4: profile-2 activate + 0b 1e 02 together (both commands for each switch) ===")
fd = os.open(HIDRAW, os.O_RDWR | os.O_NONBLOCK)
drain(fd, 0.05)
w(fd, [0x11, 0xff, F_PRFL, 0x1e, 0x01])
drain(fd, 0.3)
w(fd, [0x11, 0xff, F_8010, 0x2e, 0x01])
drain(fd, 0.4)
print("  send profile-2 activate + 0b 1e 02 together:")
w(fd, [0x11, 0xff, F_PRFL, 0x1e, 0x02])
time.sleep(0.05)
w(fd, [0x11, 0xff, F_8020, 0x1e, 0x02])
drain(fd, 0.2)
time.sleep(0.5)
t4 = ask("M2 lit?")
w(fd, [0x11, 0xff, F_PRFL, 0x1e, 0x01])
time.sleep(0.05)
w(fd, [0x11, 0xff, F_8020, 0x1e, 0x01])
drain(fd, 0.1)
os.close(fd)

if t4:
    print("*** T4: profile activate + 0b 1e together works.")
    raise SystemExit(0)

print("\nAll tests failed. Gather more info — check if M-key press itself changes indicator.")
