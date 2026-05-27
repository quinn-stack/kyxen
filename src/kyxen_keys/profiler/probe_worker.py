"""
ProbeWorker — QThread that cycles through LED IDs 0x01–0xFF and waits for
the user to press the corresponding key after each one lights up.

Communication:
  - The UI captures key presses via keyPressEvent and calls receive_key(name).
  - The UI calls skip_current() to move past a LED that doesn't correspond to
    any key (e.g. LEDs that don't light anything visible).
  - The UI calls stop_probe() to abort early.

Key name detection uses Linux native scancodes (most reliable for L/R modifiers)
with a Qt-key fallback for anything not in the scan table.
"""
from __future__ import annotations
import os
import time

from PySide6.QtCore import QMutex, QMutexLocker, QThread, QWaitCondition, Signal, Slot
from PySide6.QtGui import QKeyEvent

from . import hid_probe

# ── Scancode → key name ────────────────────────────────────────────────────────
# Linux evdev scancodes.  Qt X11 adds 8 to the evdev code, so we try both
# (scan - 8) and scan itself when looking up names.

_EVDEV_SCAN: dict[int, str] = {
    1:   'ESC',
    2:   '1',        3:   '2',        4:   '3',        5:   '4',
    6:   '5',        7:   '6',        8:   '7',        9:   '8',
    10:  '9',        11:  '0',
    12:  'MINUS',    13:  'EQUALS',   14:  'BACKSPACE', 15:  'TAB',
    16:  'Q',        17:  'W',        18:  'E',         19:  'R',
    20:  'T',        21:  'Y',        22:  'U',         23:  'I',
    24:  'O',        25:  'P',
    26:  'L_BRACKET', 27: 'R_BRACKET', 28: 'RETURN',
    29:  'L_CTRL',
    30:  'A',        31:  'S',        32:  'D',         33:  'F',
    34:  'G',        35:  'H',        36:  'J',         37:  'K',
    38:  'L',
    39:  'SEMICOLON', 40: 'APOSTROPHE', 41: 'BACKTICK',
    42:  'L_SHIFT',  43:  'BACKSLASH',
    44:  'Z',        45:  'X',        46:  'C',         47:  'V',
    48:  'B',        49:  'N',        50:  'M',
    51:  'COMMA',    52:  'PERIOD',   53:  'R_SLASH',
    54:  'R_SHIFT',  55:  'NUM_STAR', 56:  'L_ALT',     57:  'SPACE',
    58:  'CAPS_LOCK',
    59:  'F1',       60:  'F2',       61:  'F3',        62:  'F4',
    63:  'F5',       64:  'F6',       65:  'F7',        66:  'F8',
    67:  'F9',       68:  'F10',
    69:  'NUM_LOCK', 70:  'SCROLL_LOCK',
    71:  'NUM_7',    72:  'NUM_8',    73:  'NUM_9',     74:  'NUM_MINUS',
    75:  'NUM_4',    76:  'NUM_5',    77:  'NUM_6',     78:  'NUM_PLUS',
    79:  'NUM_1',    80:  'NUM_2',    81:  'NUM_3',
    82:  'NUM_0',    83:  'NUM_PERIOD',
    86:  'HASH',
    87:  'F11',      88:  'F12',
    96:  'NUM_ENTER', 97: 'R_CTRL',  98:  'NUM_SLASH',
    99:  'PRINT_SCREEN',
    100: 'R_ALT',
    102: 'HOME',     103: 'UP',      104: 'PAGE_UP',
    105: 'LEFT',     106: 'RIGHT',
    107: 'END',      108: 'DOWN',    109: 'PAGE_DOWN',
    110: 'INSERT',   111: 'DELETE',
    119: 'PAUSE',
    125: 'L_SUPER',  126: 'R_SUPER', 127: 'CONTEXT',
    # Media / extra
    113: 'MUTE',     114: 'VOL_DOWN', 115: 'VOL_UP',
    163: 'MEDIA_NEXT', 164: 'PLAY_PAUSE', 165: 'MEDIA_PREV',
}

# Also build an X11-offset version (evdev + 8)
_X11_SCAN: dict[int, str] = {k + 8: v for k, v in _EVDEV_SCAN.items()}


def key_event_to_name(event: QKeyEvent) -> str | None:
    """Convert a QKeyEvent to a Kyxen key name string, or None if unrecognised."""
    scan = event.nativeScanCode()
    # Try X11 offset first (most common on desktop Linux), then raw evdev
    name = _X11_SCAN.get(scan) or _EVDEV_SCAN.get(scan)
    if name:
        return name

    # Fallback: Qt key code
    from PySide6.QtCore import Qt
    key = event.key()
    if Qt.Key.Key_A.value <= key <= Qt.Key.Key_Z.value:
        return chr(key)
    if Qt.Key.Key_0.value <= key <= Qt.Key.Key_9.value:
        return chr(key)

    _QT_SPECIALS: dict[int, str] = {
        Qt.Key.Key_Space.value:       'SPACE',
        Qt.Key.Key_Return.value:      'RETURN',
        Qt.Key.Key_Enter.value:       'NUM_ENTER',
        Qt.Key.Key_Tab.value:         'TAB',
        Qt.Key.Key_Backspace.value:   'BACKSPACE',
        Qt.Key.Key_Escape.value:      'ESC',
        Qt.Key.Key_Delete.value:      'DELETE',
        Qt.Key.Key_Insert.value:      'INSERT',
        Qt.Key.Key_Home.value:        'HOME',
        Qt.Key.Key_End.value:         'END',
        Qt.Key.Key_PageUp.value:      'PAGE_UP',
        Qt.Key.Key_PageDown.value:    'PAGE_DOWN',
        Qt.Key.Key_Up.value:          'UP',
        Qt.Key.Key_Down.value:        'DOWN',
        Qt.Key.Key_Left.value:        'LEFT',
        Qt.Key.Key_Right.value:       'RIGHT',
        Qt.Key.Key_CapsLock.value:    'CAPS_LOCK',
        Qt.Key.Key_NumLock.value:     'NUM_LOCK',
        Qt.Key.Key_ScrollLock.value:  'SCROLL_LOCK',
        Qt.Key.Key_Print.value:       'PRINT_SCREEN',
        Qt.Key.Key_Pause.value:       'PAUSE',
        Qt.Key.Key_F1.value:  'F1',  Qt.Key.Key_F2.value:  'F2',
        Qt.Key.Key_F3.value:  'F3',  Qt.Key.Key_F4.value:  'F4',
        Qt.Key.Key_F5.value:  'F5',  Qt.Key.Key_F6.value:  'F6',
        Qt.Key.Key_F7.value:  'F7',  Qt.Key.Key_F8.value:  'F8',
        Qt.Key.Key_F9.value:  'F9',  Qt.Key.Key_F10.value: 'F10',
        Qt.Key.Key_F11.value: 'F11', Qt.Key.Key_F12.value: 'F12',
        Qt.Key.Key_Shift.value:   'L_SHIFT',
        Qt.Key.Key_Control.value: 'L_CTRL',
        Qt.Key.Key_Alt.value:     'L_ALT',
        Qt.Key.Key_Meta.value:    'L_SUPER',
    }
    return _QT_SPECIALS.get(key)


# ── Worker ────────────────────────────────────────────────────────────────────

class ProbeWorker(QThread):
    """
    Cycles LED IDs 0x01–0xFF.  For each ID it:
      1. Lights the LED white on a black keyboard.
      2. Emits led_testing(led_id).
      3. Waits up to TIMEOUT_S for receive_key() or skip_current().
      4. Emits key_mapped or led_skipped accordingly.
      5. Turns the LED off.

    Call stop_probe() to abort early; probe_done is still emitted with
    whatever was collected.
    """

    led_testing  = Signal(int)         # currently testing this LED id
    key_mapped   = Signal(int, str)    # (led_id, key_name) confirmed
    led_skipped  = Signal(int)         # led_id had no associated key
    probe_done   = Signal(dict)        # complete mapping: led_id → key_name
    probe_error  = Signal(str)         # fatal error message

    TIMEOUT_S = 5.0

    def __init__(self, hidraw_path: str, parent=None) -> None:
        super().__init__(parent)
        self._hidraw_path = hidraw_path
        self._mutex  = QMutex()
        self._cond   = QWaitCondition()
        self._pending_key: str | None = None
        self._do_skip = False
        self._do_stop = False

    @Slot(str)
    def receive_key(self, name: str) -> None:
        with QMutexLocker(self._mutex):
            self._pending_key = name
            self._cond.wakeAll()

    @Slot()
    def skip_current(self) -> None:
        with QMutexLocker(self._mutex):
            self._do_skip = True
            self._cond.wakeAll()

    @Slot()
    def stop_probe(self) -> None:
        with QMutexLocker(self._mutex):
            self._do_stop = True
            self._cond.wakeAll()

    def run(self) -> None:
        mapping: dict[int, str] = {}
        fd: int | None = None
        try:
            fd = hid_probe.open_hidraw(self._hidraw_path)
            hid_probe.init_software_mode(fd)
            hid_probe.set_all_black(fd)

            for led_id in range(0x01, 0x100):
                self._mutex.lock()
                if self._do_stop:
                    self._mutex.unlock()
                    break
                self._pending_key = None
                self._do_skip     = False
                self._mutex.unlock()

                hid_probe.light_single_led(fd, led_id)
                self.led_testing.emit(led_id)

                # Wait for a key, skip, stop, or timeout
                self._mutex.lock()
                t_end = time.monotonic() + self.TIMEOUT_S
                while self._pending_key is None and not self._do_skip and not self._do_stop:
                    remaining_ms = int((t_end - time.monotonic()) * 1000)
                    if remaining_ms <= 0:
                        break
                    self._cond.wait(self._mutex, remaining_ms)
                key_name = self._pending_key
                skipped  = self._do_skip or self._do_stop or key_name is None
                self._mutex.unlock()

                hid_probe.light_single_led(fd, led_id, 0, 0, 0)

                if not skipped and key_name:
                    mapping[led_id] = key_name
                    self.key_mapped.emit(led_id, key_name)
                else:
                    self.led_skipped.emit(led_id)

            hid_probe.set_all_black(fd)

        except Exception as e:
            self.probe_error.emit(str(e))
        finally:
            if fd is not None:
                try:
                    os.close(fd)
                except OSError:
                    pass

        self.probe_done.emit(mapping)
