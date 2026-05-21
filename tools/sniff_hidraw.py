"""
Dump all raw HID++ packets from hidraw.
Run with daemon stopped. Press G-keys and watch what comes through.
Usage: python3 sniff_hidraw.py [hidraw_path]
"""
import os, select, sys

path = sys.argv[1] if len(sys.argv) > 1 else '/dev/hidraw6'
print(f'Sniffing {path} — press G-keys, Ctrl+C to stop\n')

fd = os.open(path, os.O_RDWR | os.O_NONBLOCK)
try:
    while True:
        r, _, _ = select.select([fd], [], [], 1.0)
        if not r:
            continue
        data = os.read(fd, 64)
        hex_str = ' '.join(f'{b:02x}' for b in data)
        print(f'[{len(data):2d} bytes]  {hex_str}')
except KeyboardInterrupt:
    print('\ndone')
finally:
    os.close(fd)
