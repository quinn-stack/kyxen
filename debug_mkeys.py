#!/usr/bin/env python3
"""
Tests the EXACT logic now in gkeys.py run_mkey_listener against live lighting.
Run with daemon stopped: systemctl --user stop kyxen
  python3 ~/kyxen/debug_mkeys.py
Press M1/M2/M3 during Phase 2.
"""
import os, select as _sel, sys, threading, time, colorsys
sys.path.insert(0, '/home/wade/kyxen/src')

from kyxen_keys.keyboards import detect_keyboard
from kyxen_keys import onboard_profiles
from kyxen_keys.lighting import KEY_IDS

kb = detect_keyboard()
hidraw    = kb.paths.hidraw
feat_8010 = onboard_profiles.get_feature_index(hidraw, 0x8010)
feat_8020 = onboard_profiles.get_feature_index(hidraw, 0x8020)
feat_8100 = onboard_profiles.get_feature_index(hidraw, 0x8100)
print(f'hidraw={hidraw}  feat_8010=0x{feat_8010:02x} feat_8020=0x{feat_8020:02x} feat_8100=0x{feat_8100:02x}')

ALL_KEYS = list(KEY_IDS.values())
COMMIT   = bytes([0x11, 0xff, 0x10, 0x7e]) + bytes(16)
stop     = threading.Event()

# ── lighting thread (same as LightingEngine) ──────────────────────────────────
def lighting_thread():
    fd = os.open(hidraw, os.O_RDWR | os.O_NONBLOCK)
    try:
        os.write(fd, bytes([0x11, 0xff, 0x09, 0x0f]) + bytes(16))
        time.sleep(0.15)
        os.write(fd, bytes([0x11, 0xff, 0x03, 0x2e]) + bytes(16))
        time.sleep(0.15)
        t0 = time.monotonic()
        p  = bytearray(20)
        p[0], p[1], p[2], p[3] = 0x11, 0xff, 0x10, 0x5e
        while not stop.is_set():
            hue = (time.monotonic() - t0) * 0.1 % 1.0
            rv, gv, bv = colorsys.hsv_to_rgb(hue, 1.0, 1.0)
            r, g, b = int(rv*255), int(gv*255), int(bv*255)
            for key_id in ALL_KEYS:
                p[4] = p[5] = key_id; p[6], p[7], p[8] = r, g, b
                os.write(fd, bytes(p))
            os.write(fd, COMMIT)
            time.sleep(0.05)
    except Exception as e:
        print(f'[lighting] {e}')
    finally:
        os.close(fd)

# ── M-key listener (exact copy of new gkeys.py logic) ─────────────────────────
detections = []
def mkey_thread():
    import time as _time
    fd = os.open(hidraw, os.O_RDWR | os.O_NONBLOCK)
    try:
        def _drain(timeout):
            deadline = _time.monotonic() + timeout
            while True:
                remaining = deadline - _time.monotonic()
                if remaining <= 0: break
                r, _, _ = _sel.select([fd], [], [], remaining)
                if not r: break
                os.read(fd, 64)

        def _drain_and_check():
            while True:
                try:
                    data = os.read(fd, 64)
                except BlockingIOError:
                    return
                if (len(data) >= 5 and data[0] == 0x11
                        and data[2] == feat_8020 and data[3] == 0x00
                        and data[4] in (0x01, 0x02, 0x04)):
                    name = {0x01:'M1', 0x02:'M2', 0x04:'M3'}[data[4]]
                    detections.append(name)
                    print(f'  *** {name} DETECTED ***')

        _drain(0.05)
        os.write(fd, bytes([0x11, 0xff, feat_8100, 0x1e, 0x01]) + b'\x00'*15)
        _drain(0.3)
        print('[mkey] sent feat_8010 SW enable')
        os.write(fd, bytes([0x11, 0xff, feat_8010, 0x2e, 0x01]) + b'\x00'*15)
        _drain(0.4)
        print('[mkey] sent feat_8020 arm')
        os.write(fd, bytes([0x11, 0xff, feat_8020, 0x1e, 0x01]) + b'\x00'*15)
        _drain(0.3)
        print('[mkey] startup done, entering poll loop')

        while not stop.is_set():
            _drain_and_check()
            _time.sleep(0.005)
    except Exception as e:
        print(f'[mkey] ERROR: {e}')
        import traceback; traceback.print_exc()
    finally:
        os.close(fd)

# Start lighting first (like daemon does), then M-key listener
print('\n[1] starting lighting engine...')
t_light = threading.Thread(target=lighting_thread, daemon=True)
t_light.start()
time.sleep(0.4)  # let lighting get going

print('[2] starting M-key listener...')
t_mkey = threading.Thread(target=mkey_thread, daemon=True)
t_mkey.start()

print('\nPress M1, M2, M3 — waiting 20s...')
time.sleep(20)
stop.set()
t_light.join(timeout=2)
t_mkey.join(timeout=2)
print(f'\nResult: {len(detections)} M-key detections: {detections}')
