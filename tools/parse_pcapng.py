#!/usr/bin/env python3
"""Minimal pcapng parser — dumps USB HID payload bytes for G815 packets."""
import struct, sys

def parse(path):
    with open(path, 'rb') as f:
        data = f.read()

    pos = 0
    packets = []

    while pos < len(data):
        if pos + 8 > len(data):
            break
        block_type, block_len = struct.unpack_from('<II', data, pos)
        if block_len < 12 or pos + block_len > len(data):
            break

        # Enhanced Packet Block (EPB) = 0x00000006
        if block_type == 0x00000006:
            # interface_id, ts_hi, ts_lo, cap_len, orig_len
            if pos + 28 <= len(data):
                cap_len = struct.unpack_from('<I', data, pos + 20)[0]
                pkt_data = data[pos + 28 : pos + 28 + cap_len]
                packets.append(pkt_data)

        pos += block_len

    return packets


def dump_usb_hid(packets):
    """Pull HID payload from USBPcap-encapsulated packets."""
    results = []
    for raw in packets:
        # USBPcap header is variable length; IRP ID is first 8 bytes (LE uint64)
        # Header length is at offset 0 as uint16 in some versions,
        # but simplest: look for 0x11 ff pattern (HID++ LONG) in the payload
        hex_raw = raw.hex()
        # Find 11ff pattern
        idx = raw.find(b'\x11\xff')
        if idx != -1:
            payload = raw[idx:idx+20]
            if len(payload) >= 5:
                direction = 'host→kb' if idx < 28 else 'kb→host'
                # Try to determine direction from USBPcap header
                # direction byte is at offset 22 in USBPcap header (0=FDO=host→device, 1=PDO=device→host)
                if len(raw) > 22:
                    dir_byte = raw[22] if len(raw) > 22 else 0xff
                    direction = 'kb→host' if dir_byte & 1 else 'host→kb'
                results.append((direction, payload[:20].hex()))
    return results


def dump_all(path):
    print(f"\n=== {path} ===")
    pkts = parse(path)
    print(f"Total packets: {len(pkts)}")
    hits = dump_usb_hid(pkts)
    if not hits:
        # Try alternative: just scan entire file for 11ff patterns
        with open(path, 'rb') as f:
            raw = f.read()
        print("Scanning raw bytes for 11 ff patterns...")
        pos = 0
        while True:
            idx = raw.find(b'\x11\xff', pos)
            if idx == -1: break
            chunk = raw[idx:idx+20]
            if len(chunk) >= 5:
                print(f"  @{idx:6x}: {chunk.hex(' ')}")
            pos = idx + 1
    else:
        for direction, hex_data in hits:
            b = bytes.fromhex(hex_data)
            feat = b[2]
            func = b[3] >> 4
            swid = b[3] & 0xf
            print(f"  [{direction:10s}] feat=0x{feat:02x} func={func} SW={swid:x}  {hex_data}")


if __name__ == '__main__':
    base = "/run/media/wade/F386-55D0/Lighting pcapng/"
    for name in ["Mkeys light capture.pcapng",
                 "Sequential light capture.pcapng",
                 "new connection .pcapng"]:
        dump_all(base + name)
