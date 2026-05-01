"""Macro execution — type text (via uinput) or run a shell command."""
from __future__ import annotations
import subprocess
import threading
import time
from evdev import UInput, ecodes

from .config import MacroAction

_uinput: UInput | None = None
_char_map: dict[str, tuple[int, bool]] | None = None


def set_uinput(ui: UInput) -> None:
    global _uinput, _char_map
    _uinput = ui
    _char_map = _get_char_map()   # detect layout once at startup


def run(action: MacroAction) -> None:
    if action.action == 'none':
        return
    t = threading.Thread(target=_execute, args=(action,), daemon=True)
    t.start()


def _execute(action: MacroAction) -> None:
    print(f'[macro] {action.action!r}  text={action.text!r}  cmd={action.cmd!r}')
    if action.action == 'type' and action.text:
        _type_text(action.text)
    elif action.action == 'command' and action.cmd:
        _run_command(action.cmd)


# ── keyboard layout detection ─────────────────────────────────────────────────

def _detect_layout() -> str:
    try:
        out = subprocess.run(['localectl', 'status'], capture_output=True, text=True).stdout
        for line in out.splitlines():
            if 'X11 Layout' in line:
                layout = line.split(':', 1)[1].strip().lower()
                return layout.split(',')[0]   # take first if multiple
    except Exception:
        pass
    return 'us'


# ── character maps ────────────────────────────────────────────────────────────
# Each map: char → (evdev_keycode, needs_shift)

def _base_map() -> dict[str, tuple[int, bool]]:
    m: dict[str, tuple[int, bool]] = {}
    for c in 'abcdefghijklmnopqrstuvwxyz':
        code = getattr(ecodes, f'KEY_{c.upper()}')
        m[c]       = (code, False)
        m[c.upper()] = (code, True)
    for c in '1234567890':
        m[c] = (getattr(ecodes, f'KEY_{c}'), False)
    m.update({
        ' ':  (ecodes.KEY_SPACE,       False),
        '\n': (ecodes.KEY_ENTER,       False),
        '\t': (ecodes.KEY_TAB,         False),
        '.':  (ecodes.KEY_DOT,         False),
        ',':  (ecodes.KEY_COMMA,       False),
        '-':  (ecodes.KEY_MINUS,       False),
        '=':  (ecodes.KEY_EQUAL,       False),
        '[':  (ecodes.KEY_LEFTBRACE,   False),
        ']':  (ecodes.KEY_RIGHTBRACE,  False),
        ';':  (ecodes.KEY_SEMICOLON,   False),
        '`':  (ecodes.KEY_GRAVE,       False),
        '/':  (ecodes.KEY_SLASH,       False),
        '_':  (ecodes.KEY_MINUS,       True),
        '+':  (ecodes.KEY_EQUAL,       True),
        '{':  (ecodes.KEY_LEFTBRACE,   True),
        '}':  (ecodes.KEY_RIGHTBRACE,  True),
        ':':  (ecodes.KEY_SEMICOLON,   True),
        '<':  (ecodes.KEY_COMMA,       True),
        '>':  (ecodes.KEY_DOT,         True),
        '?':  (ecodes.KEY_SLASH,       True),
    })
    return m


_LAYOUTS: dict[str, dict[str, tuple[int, bool]]] = {}


def _build_us() -> dict[str, tuple[int, bool]]:
    m = _base_map()
    m.update({
        '!': (ecodes.KEY_1,          True),
        '@': (ecodes.KEY_2,          True),
        '#': (ecodes.KEY_3,          True),
        '$': (ecodes.KEY_4,          True),
        '%': (ecodes.KEY_5,          True),
        '^': (ecodes.KEY_6,          True),
        '&': (ecodes.KEY_7,          True),
        '*': (ecodes.KEY_8,          True),
        '(': (ecodes.KEY_9,          True),
        ')': (ecodes.KEY_0,          True),
        "'": (ecodes.KEY_APOSTROPHE, False),
        '"': (ecodes.KEY_APOSTROPHE, True),
        '~': (ecodes.KEY_GRAVE,      True),
        '|': (ecodes.KEY_BACKSLASH,  True),
        '\\': (ecodes.KEY_BACKSLASH, False),
    })
    return m


def _build_gb() -> dict[str, tuple[int, bool]]:
    """UK (GB) QWERTY layout — differs from US for several symbols."""
    m = _base_map()
    m.update({
        '!': (ecodes.KEY_1,          True),
        '"': (ecodes.KEY_2,          True),   # UK: shift+2 = "
        '£': (ecodes.KEY_3,          True),
        '$': (ecodes.KEY_4,          True),
        '%': (ecodes.KEY_5,          True),
        '^': (ecodes.KEY_6,          True),
        '&': (ecodes.KEY_7,          True),
        '*': (ecodes.KEY_8,          True),
        '(': (ecodes.KEY_9,          True),
        ')': (ecodes.KEY_0,          True),
        '@': (ecodes.KEY_APOSTROPHE, True),   # UK: shift+' = @
        "'": (ecodes.KEY_APOSTROPHE, False),
        '#': (ecodes.KEY_BACKSLASH,  False),  # UK: key left of Enter
        '~': (ecodes.KEY_BACKSLASH,  True),
        '\\': (ecodes.KEY_102ND,     False),  # UK: extra key left of Z
        '|': (ecodes.KEY_102ND,      True),
    })
    return m


def _build_de() -> dict[str, tuple[int, bool]]:
    """German QWERTZ layout — letters and common symbols."""
    m = _base_map()
    # QWERTZ: y and z swapped
    m['y'] = (ecodes.KEY_Z, False)
    m['Y'] = (ecodes.KEY_Z, True)
    m['z'] = (ecodes.KEY_Y, False)
    m['Z'] = (ecodes.KEY_Y, True)
    m.update({
        '!': (ecodes.KEY_1,          True),
        '"': (ecodes.KEY_2,          True),
        '§': (ecodes.KEY_3,          True),
        '$': (ecodes.KEY_4,          True),
        '%': (ecodes.KEY_5,          True),
        '&': (ecodes.KEY_6,          True),
        '/': (ecodes.KEY_7,          True),
        '(': (ecodes.KEY_8,          True),
        ')': (ecodes.KEY_9,          True),
        '=': (ecodes.KEY_0,          True),
        '-': (ecodes.KEY_SLASH,      False),
        '_': (ecodes.KEY_SLASH,      True),
        '@': (ecodes.KEY_Q,          False),  # AltGr+Q — approximation
    })
    return m


def _get_char_map() -> dict[str, tuple[int, bool]]:
    layout = _detect_layout()
    if layout not in _LAYOUTS:
        builder = {'us': _build_us, 'gb': _build_gb, 'de': _build_de}.get(layout, _build_us)
        _LAYOUTS[layout] = builder()
        print(f'[macro] keyboard layout: {layout}')
    return _LAYOUTS[layout]


# ── injection ─────────────────────────────────────────────────────────────────

def _type_text(text: str) -> None:
    time.sleep(0.08)
    if _uinput is not None:
        _inject_uinput(text)
    else:
        _inject_subprocess(text)


def _inject_uinput(text: str) -> None:
    char_map = _char_map or _get_char_map()
    ui    = _uinput
    EV    = ecodes.EV_KEY
    SHIFT = ecodes.KEY_LEFTSHIFT
    skipped = []

    for ch in text:
        if ch not in char_map:
            skipped.append(ch)
            continue
        code, needs_shift = char_map[ch]

        if needs_shift:
            ui.write(EV, SHIFT, 1);  ui.syn();  time.sleep(0.008)

        ui.write(EV, code, 1);  ui.syn();  time.sleep(0.018)
        ui.write(EV, code, 0);  ui.syn();  time.sleep(0.018)

        if needs_shift:
            ui.write(EV, SHIFT, 0);  ui.syn();  time.sleep(0.008)

    if skipped:
        print(f'[macro] skipped unmapped chars: {skipped}')


def _inject_subprocess(text: str) -> None:
    for args in [
        ['ydotool', 'type', '--', text],
        ['xdotool', 'type', '--clearmodifiers', '--delay', '20', '--', text],
    ]:
        try:
            subprocess.run(args, check=False)
            return
        except FileNotFoundError:
            continue
    print('[macro] no text injection tool available (tried ydotool, xdotool)')


def _run_command(cmd: str) -> None:
    try:
        subprocess.Popen(cmd, shell=True, start_new_session=True)
    except Exception as e:
        print(f'[macro] command error: {e}')
