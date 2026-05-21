#!/usr/bin/env python3
"""
G815 Key Code Mapper — GUI probe tool.

Lights one key code at a time in red. Press the lit key on the G815 to
auto-record and advance. Click Skip to skip a code, Save & Quit at any time.
Progress is saved to g815_keymap.json so you can resume across sessions.

Usage:
    python3 ~/kyxen/probe_mkeys.py              # full sweep 0x00–0xFF
    python3 ~/kyxen/probe_mkeys.py 0x60 0x80   # specific sub-range
    python3 ~/kyxen/probe_mkeys.py --resume     # skip already-mapped codes
"""
from __future__ import annotations
import sys
import os
import json
import select as sel
import threading
from pathlib import Path

REPO    = Path(__file__).parent
MAPFILE = REPO / 'g815_keymap.json'
sys.path.insert(0, str(REPO / 'src'))

import evdev
from evdev import ecodes
from PySide6.QtCore    import Qt, Signal, QObject, QTimer
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QLineEdit, QFrame,
)

from kyxen_keys.keyboards import detect_keyboard


# ── HID++ helpers ─────────────────────────────────────────────────────────────

def _send(fd: int, data: bytes) -> None:
    pkt = data + bytes(max(0, 20 - len(data)))
    os.write(fd, pkt)
    r, _, _ = sel.select([fd], [], [], 0.3)
    if r:
        os.read(fd, 64)


def _write(fd: int, data: bytes) -> None:
    """Fire-and-forget write — no response wait. Used for the refresh loop."""
    pkt = data + bytes(max(0, 20 - len(data)))
    os.write(fd, pkt)


def _enter_direct(fd: int) -> None:
    _send(fd, bytes([0x11, 0xff, 0x08, 0x3e]))
    _send(fd, bytes([0x11, 0xff, 0x08, 0x1e]))
    _send(fd, bytes([0x11, 0xff, 0x0f, 0x1e, 0x00, 0x00, 0x00, 0x00,
                     0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x01]))
    _send(fd, bytes([0x11, 0xff, 0x0f, 0x1e, 0x01, 0x00, 0x00, 0x00,
                     0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x01]))


def _set_key(fd: int, key_id: int, r: int, g: int, b: int) -> None:
    pkt = bytearray([0x11, 0xff, 0x10, 0x1f, key_id, r, g, b, 0xff])
    _write(fd, bytes(pkt))


def _commit(fd: int) -> None:
    _write(fd, bytes([0x11, 0xff, 0x10, 0x7f]))


def _clear_all_keys(hidraw: str) -> None:
    """
    Turn every LED off. Zone-off alone doesn't clear keys set via direct mode,
    so we also sweep all 256 key codes to black in direct mode.
    """
    fd = os.open(hidraw, os.O_RDWR)
    try:
        # 1. Zone effects off
        for zone in range(5):
            _send(fd, bytes([0x11, 0xff, 0x0d, 0x3d,
                             zone, 0x00, 0, 0, 0,
                             0x00, 0x00, 0x00, 0x32, 0x64,
                             0x00, 0x00, 0x00, 0x00, 0x00, 0x00]))
        # 2. Enter direct mode, bulk-clear all 256 key codes
        _enter_direct(fd)
        codes = list(range(0x100))
        for i in range(0, len(codes), 13):
            chunk = codes[i:i + 13]
            pkt = bytearray([0x11, 0xff, 0x10, 0x6f, 0, 0, 0])
            pkt.extend(chunk)
            if len(chunk) < 13:
                pkt.append(0xff)
            _send(fd, bytes(pkt))
        _commit(fd)
    finally:
        os.close(fd)


# ── evdev name helper ──────────────────────────────────────────────────────────

def _evdev_name(code: int) -> str:
    raw = ecodes.KEY.get(code, '')
    if isinstance(raw, list):
        raw = raw[0] if raw else ''
    name = raw.replace('KEY_', '').lower()
    _nice = {
        'grave': '`', 'minus': '-', 'equal': '=',
        'leftbrace': '[', 'rightbrace': ']', 'backslash': '\\',
        'semicolon': ';', 'apostrophe': "'", 'comma': ',',
        'dot': '.', 'slash': '/', 'space': 'space',
        'leftctrl': 'ctrl_l', 'rightctrl': 'ctrl_r',
        'leftshift': 'shift_l', 'rightshift': 'shift_r',
        'leftalt': 'alt_l', 'rightalt': 'alt_r',
        'leftmeta': 'super_l', 'rightmeta': 'super_r',
        'capslock': 'caps', 'pageup': 'pageup', 'pagedown': 'pagedown',
        'kpenter': 'numpad_enter', 'kpslash': 'numpad_/',
        'kpasterisk': 'numpad_*', 'kpminus': 'numpad_-',
        'kpplus': 'numpad_+', 'kpdot': 'numpad_.',
    }
    return _nice.get(name, name) if name else ''


# ── key listener (background thread) ──────────────────────────────────────────

class _Bridge(QObject):
    key_pressed = Signal(str)


class _KeyListener(threading.Thread):
    """
    Listens ONLY to the G815's standard keyboard evdev interface, found via
    sysfs by walking from the known G-key evdev path up to the USB device node
    and finding all sibling event devices on that USB device.
    Also listens for M1/M2/M3 via HID++ notifications on hidraw.
    """

    def __init__(self, kb, bridge: _Bridge, stop: threading.Event):
        super().__init__(daemon=True)
        self._kb            = kb
        self._bridge        = bridge
        self._stop          = stop
        self._feat_8020: int | None = None
        self._last_record   = 0.0   # monotonic time of last auto-record (debounce)

    def _find_kb_evdev(self) -> evdev.InputDevice | None:
        """
        Locate the G815's standard keyboard evdev using sysfs — walks from the
        known G-key evdev up to the USB device node, then finds the sibling
        interface whose name ends with ' Keyboard'. This is immune to other
        Logitech devices appearing on the same system.
        """
        from pathlib import Path
        import time as _time

        gkey_path  = self._kb.paths.evdev
        event_name = Path(gkey_path).name
        event_link = Path(f'/sys/class/input/{event_name}')
        if not event_link.exists():
            return None
        try:
            real = event_link.resolve()
        except Exception:
            return None

        # Walk up sysfs to the USB device (has idVendor file)
        current    = real.parent
        usb_device = None
        while current != current.parent:
            if (current / 'idVendor').exists():
                usb_device = current
                break
            current = current.parent
        if usb_device is None:
            return None

        # Find every event* directory under this USB device and check for ' Keyboard'
        for ep in usb_device.rglob('event*'):
            if not ep.is_dir():
                continue
            dev_path = f'/dev/input/{ep.name}'
            if dev_path == gkey_path:
                continue
            try:
                dev = evdev.InputDevice(dev_path)
                if dev.name.endswith(' Keyboard'):
                    return dev
            except Exception:
                pass
        return None

    def run(self) -> None:
        kb_dev = self._find_kb_evdev()
        if kb_dev is None:
            print('[probe] G815 keyboard evdev not found — key auto-detect disabled')

        # HID++ M-key listener
        mkey_fd: int | None = None
        hidraw = self._kb.paths.hidraw
        if hidraw:
            try:
                from kyxen_keys import onboard_profiles
                feat_8010 = onboard_profiles.get_feature_index(hidraw, 0x8010)
                self._feat_8020 = onboard_profiles.get_feature_index(hidraw, 0x8020)
                mkey_fd = os.open(hidraw, os.O_RDWR | os.O_NONBLOCK)
                os.write(mkey_fd,
                         bytes([0x11, 0xff, feat_8010, 0x2e, 0x01]) + b'\x00' * 15)
                os.write(mkey_fd,
                         bytes([0x11, 0xff, self._feat_8020, 0x1e, 0x01]) + b'\x00' * 15)
            except Exception as e:
                print(f'[probe] M-key listener not started: {e}')
                mkey_fd = None

        watch_fds: list[int] = []
        if kb_dev:
            watch_fds.append(kb_dev.fd)
        if mkey_fd is not None:
            watch_fds.append(mkey_fd)

        if not watch_fds:
            return

        try:
            while not self._stop.is_set():
                ready, _, _ = sel.select(watch_fds, [], [], 0.5)
                for fd in ready:
                    if kb_dev and fd == kb_dev.fd:
                        try:
                            for ev in kb_dev.read():
                                # value 1 = key down, value 2 = auto-repeat — ignore repeats
                                if ev.type == ecodes.EV_KEY and ev.value == 1:
                                    import time as _t
                                    if _t.monotonic() - self._last_record < 0.3:
                                        continue  # debounce
                                    name = _evdev_name(ev.code)
                                    if name:
                                        self._last_record = _t.monotonic()
                                        self._bridge.key_pressed.emit(name)
                        except Exception:
                            pass
                    elif fd == mkey_fd:
                        try:
                            data = os.read(fd, 64)
                            self._handle_mkey(data)
                        except Exception:
                            pass
        finally:
            if kb_dev:
                kb_dev.close()
            if mkey_fd is not None:
                try:
                    os.close(mkey_fd)
                except Exception:
                    pass

    def _handle_mkey(self, data: bytes) -> None:
        if (len(data) >= 5 and data[0] == 0x11
                and self._feat_8020 is not None
                and data[2] == self._feat_8020 and data[3] == 0x00):
            names = {0x01: 'm1', 0x02: 'm2', 0x04: 'm3'}
            name = names.get(data[4])
            if name:
                import time as _t
                if _t.monotonic() - self._last_record >= 0.3:
                    self._last_record = _t.monotonic()
                    self._bridge.key_pressed.emit(name)


# ── map helpers ────────────────────────────────────────────────────────────────

def load_map() -> dict[int, str]:
    if not MAPFILE.exists():
        return {}
    try:
        return {int(k, 16): v for k, v in json.loads(MAPFILE.read_text()).items()}
    except Exception:
        return {}


def save_map(keymap: dict[int, str]) -> None:
    MAPFILE.write_text(
        json.dumps({f'0x{k:02x}': v for k, v in sorted(keymap.items())}, indent=2)
    )


# ── GUI ────────────────────────────────────────────────────────────────────────

class ProbeWindow(QWidget):
    def __init__(self, hidraw: str, codes: list[int],
                 keymap: dict[int, str], resume: bool):
        super().__init__()
        self._hidraw = hidraw
        self._codes  = codes
        self._keymap = keymap
        self._resume = resume
        self._idx    = 0
        self._lit_fd: int | None = None
        self._recording = False   # guard against double-fire
        self._lit_code: int | None = None   # currently lit key code

        self.setWindowTitle('G815 Key Mapper')
        self.setMinimumWidth(360)
        self._build_ui()

        # Refresh timer — re-commits the lit key every 50 ms so it stays on.
        # The G815's direct mode is frame-based; without continuous re-commits
        # the keyboard reverts to hardware state after one frame (~1 ms).
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setInterval(50)
        self._refresh_timer.timeout.connect(self._refresh_lit_key)

        # Background key listener
        self._bridge   = _Bridge()
        self._stop_evt = threading.Event()
        self._bridge.key_pressed.connect(self._on_key_detected)

        kb = detect_keyboard()
        if kb:
            _KeyListener(kb, self._bridge, self._stop_evt).start()

        # Open hidraw fd for lighting — stays open throughout the session
        try:
            self._lit_fd = os.open(hidraw, os.O_RDWR)
            _enter_direct(self._lit_fd)
        except OSError as e:
            self._set_status(f'Cannot open {hidraw}: {e}')

        self._advance()

    # ── UI ────────────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(16, 16, 16, 16)

        self._code_label = QLabel()
        self._code_label.setAlignment(Qt.AlignCenter)
        f = self._code_label.font()
        f.setPointSize(32)
        f.setBold(True)
        self._code_label.setFont(f)
        layout.addWidget(self._code_label)

        self._progress = QLabel()
        self._progress.setAlignment(Qt.AlignCenter)
        self._progress.setStyleSheet('color: #888;')
        layout.addWidget(self._progress)

        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        layout.addWidget(sep)

        row = QHBoxLayout()
        row.addWidget(QLabel('Detected:'))
        self._name_edit = QLineEdit()
        self._name_edit.setPlaceholderText('press the lit key on the G815…')
        row.addWidget(self._name_edit)
        layout.addLayout(row)

        self._hint = QLabel('Auto-advances when you press the key on the G815.\n'
                            'Or type a name and click Record.')
        self._hint.setStyleSheet('color: #888; font-size: 10px;')
        self._hint.setAlignment(Qt.AlignCenter)
        layout.addWidget(self._hint)

        btn_row = QHBoxLayout()
        self._prev_btn = QPushButton('◀ Previous')
        self._prev_btn.setFixedHeight(38)
        self._prev_btn.clicked.connect(self._on_prev)
        self._record_btn = QPushButton('Record')
        self._record_btn.setFixedHeight(38)
        self._record_btn.clicked.connect(self._on_record)
        self._skip_btn = QPushButton('Skip ▶')
        self._skip_btn.setFixedHeight(38)
        self._skip_btn.clicked.connect(self._on_skip)
        btn_row.addWidget(self._prev_btn)
        btn_row.addWidget(self._record_btn)
        btn_row.addWidget(self._skip_btn)
        layout.addLayout(btn_row)

        sep2 = QFrame()
        sep2.setFrameShape(QFrame.HLine)
        layout.addWidget(sep2)

        self._recent_label = QLabel('Recent mappings:')
        self._recent_label.setStyleSheet('color: #888; font-size: 10px;')
        layout.addWidget(self._recent_label)

        layout.addStretch()

        self._save_btn = QPushButton('Save && Quit')
        self._save_btn.setFixedHeight(36)
        self._save_btn.clicked.connect(self._on_save_quit)
        layout.addWidget(self._save_btn)

        self._status = QLabel('')
        self._status.setAlignment(Qt.AlignCenter)
        self._status.setStyleSheet('color: #666; font-size: 10px;')
        layout.addWidget(self._status)

    # ── navigation ────────────────────────────────────────────────────────────

    def _current_code(self) -> int | None:
        if self._idx < len(self._codes):
            return self._codes[self._idx]
        return None

    def _refresh_lit_key(self) -> None:
        """Called every 50 ms to keep the current key lit (frame-based direct mode)."""
        if self._lit_fd is not None and self._lit_code is not None:
            try:
                _set_key(self._lit_fd, self._lit_code, 255, 0, 0)
                _commit(self._lit_fd)
            except Exception:
                self._refresh_timer.stop()

    def _key_off(self) -> None:
        self._refresh_timer.stop()
        self._lit_code = None
        if self._lit_fd is None:
            return
        try:
            # Single set_key(black) is ignored by G815 direct mode — use the
            # same bulk-clear that reliably cleared the stuck N key on startup.
            codes = list(range(0x100))
            for i in range(0, len(codes), 13):
                chunk = codes[i:i + 13]
                pkt = bytearray([0x11, 0xff, 0x10, 0x6f, 0, 0, 0])
                pkt.extend(chunk)
                if len(chunk) < 13:
                    pkt.append(0xff)
                _write(self._lit_fd, bytes(pkt))
            _send(self._lit_fd, bytes([0x11, 0xff, 0x10, 0x7f]))  # wait for commit ack before returning
        except Exception:
            pass

    def _advance(self) -> None:
        # Skip already-mapped codes in resume mode
        while self._resume and self._idx < len(self._codes):
            if self._codes[self._idx] in self._keymap:
                self._idx += 1
            else:
                break

        self._recording = False
        self._name_edit.clear()

        if self._idx >= len(self._codes):
            self._finish()
            return

        code = self._codes[self._idx]
        mapped = sum(1 for c in self._codes if c in self._keymap)
        self._code_label.setText(f'0x{code:02x}')
        self._progress.setText(f'{mapped} / {len(self._codes)} mapped')

        existing = self._keymap.get(code)
        if existing:
            self._name_edit.setText(existing)
            self._set_status(f'previously: {existing}')
        else:
            self._set_status('')

        if self._lit_fd is not None:
            try:
                self._lit_code = code
                _set_key(self._lit_fd, code, 255, 0, 0)
                _commit(self._lit_fd)
                self._refresh_timer.start()
            except Exception as e:
                self._set_status(f'lighting error: {e}')

    # ── slots ─────────────────────────────────────────────────────────────────

    def _on_key_detected(self, name: str) -> None:
        """G815 key pressed — fill name and auto-record."""
        if self._recording:
            return
        self._name_edit.setText(name)
        self._on_record()

    def _on_record(self) -> None:
        if self._recording:
            return
        name = self._name_edit.text().strip()
        if not name:
            self._set_status('Type a name first, or click Skip.')
            return
        self._recording = True
        code = self._current_code()
        if code is not None:
            self._key_off()
            self._keymap[code] = name
            save_map(self._keymap)
            self._update_recent()
        self._idx += 1
        self._advance()

    def _on_prev(self) -> None:
        if self._idx <= 0:
            return
        self._key_off()
        self._idx -= 1
        self._advance()

    def _on_skip(self) -> None:
        self._key_off()
        self._idx += 1
        self._advance()

    def _on_save_quit(self) -> None:
        self._key_off()
        self._finish()

    def _set_status(self, msg: str) -> None:
        self._status.setText(msg)

    def _update_recent(self) -> None:
        recent = list(sorted(self._keymap.items()))[-6:]
        text = '  '.join(f'0x{c:02x}={n}' for c, n in recent)
        self._recent_label.setText(f'Recent:  {text}')

    # ── finish ────────────────────────────────────────────────────────────────

    def _finish(self) -> None:
        self._refresh_timer.stop()
        self._stop_evt.set()
        if self._lit_fd is not None:
            try:
                os.close(self._lit_fd)
            except Exception:
                pass
            self._lit_fd = None
        save_map(self._keymap)
        self._print_summary()
        self.close()

    def _print_summary(self) -> None:
        km = self._keymap
        print(f'\nMapped {len(km)} keys — saved to {MAPFILE}')
        for code, name in sorted(km.items()):
            print(f'  0x{code:02x}  {name}')
        mkeys = {v: k for k, v in km.items() if v in ('m1', 'm2', 'm3')}
        if len(mkeys) == 3:
            ids = [mkeys['m1'], mkeys['m2'], mkeys['m3']]
            print(f'\nPaste into lighting.py:')
            print(f'  _G815_MKEY_IDS = {ids}  # M1, M2, M3')
        elif mkeys:
            missing = [k for k in ('m1', 'm2', 'm3') if k not in mkeys]
            print(f'\nM-keys still needed: {", ".join(missing)}')

    def closeEvent(self, event) -> None:
        self._refresh_timer.stop()
        self._stop_evt.set()
        if self._lit_fd is not None:
            try:
                os.close(self._lit_fd)
            except Exception:
                pass
        super().closeEvent(event)


# ── entry point ────────────────────────────────────────────────────────────────

def main() -> None:
    resume = '--resume' in sys.argv
    args   = [a for a in sys.argv[1:] if not a.startswith('--')]
    start  = int(args[0], 16) if len(args) > 0 else 0x00
    end    = int(args[1], 16) if len(args) > 1 else 0x100

    kb = detect_keyboard()
    if kb is None:
        print('No supported keyboard found.')
        sys.exit(1)

    hidraw = kb.paths.hidraw
    print(f'Keyboard : {kb.MODEL_NAME}')
    print(f'Hidraw   : {hidraw}')
    print('Clearing all LEDs...')
    try:
        _clear_all_keys(hidraw)
        print('Done.')
    except Exception as e:
        print(f'Warning: LED clear failed: {e}')

    keymap = load_map()
    codes  = list(range(start, end))

    app    = QApplication(sys.argv)
    window = ProbeWindow(hidraw, codes, keymap, resume)
    window.show()
    sys.exit(app.exec())


if __name__ == '__main__':
    main()
