"""
HID++ 2.0 probe — enable G-key software mode then listen on both hidraw
interfaces simultaneously. G815: hidraw7=HID++ control, hidraw6=G-key interface.
Run with daemon stopped.
"""
import os, select, time, sys

hidraw_hidpp  = '/dev/hidraw7'   # HID++ control interface
hidraw_gkeys  = '/dev/hidraw6'   # G-key boot/notification interface

print(f'Opening {hidraw_hidpp} (HID++) and {hidraw_gkeys} (G-key interface)\n')

fd7 = os.open(hidraw_hidpp, os.O_RDWR)
fd6 = os.open(hidraw_gkeys, os.O_RDWR | os.O_NONBLOCK)

def send_recv(fd: int, data: list[int]) -> bytes | None:
    pkt = bytes(data) + bytes(20 - len(data))
    os.write(fd, pkt)
    r, _, _ = select.select([fd], [], [], 0.5)
    return os.read(fd, 64) if r else None

def hexdump(data: bytes | None) -> str:
    return ' '.join(f'{b:02x}' for b in data) if data else '(no response)'

HIDPP   = 0x11
DEV     = 0xFF
FEATURE = 0x07

def call(fd, func: int, params: list[int] = []) -> bytes | None:
    data = [HIDPP, DEV, FEATURE, (func << 4) | 0x01] + params
    return send_recv(fd, data)

# Send all three enable candidates to hidraw7
print('Sending enable commands to hidraw7...')
for func, params in [(0, []), (1, [0x01]), (2, [0x01])]:
    r = call(fd7, func, params)
    print(f'  func {func} params {params}: {hexdump(r)}')

# Also try sending directly to hidraw6
print('\nSending enable commands to hidraw6...')
for func, params in [(0, []), (1, [0x01]), (2, [0x01])]:
    r = call(fd6, func, params)
    print(f'  func {func} params {params}: {hexdump(r)}')

print('\nListening on BOTH hidraw6 and hidraw7 for 10 seconds — press G-keys now...\n')
deadline = time.time() + 10
while time.time() < deadline:
    ready, _, _ = select.select([fd6, fd7], [], [], 0.25)
    for fd in ready:
        data = os.read(fd, 64)
        name = 'hidraw6' if fd == fd6 else 'hidraw7'
        print(f'  [{name}] {hexdump(data)}')

os.close(fd6)
os.close(fd7)
print('\ndone')
