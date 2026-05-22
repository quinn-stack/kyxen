"""Macro execution — type text, run commands, fire key combos, hold-toggle keys."""
from __future__ import annotations
import glob
import os
import subprocess
import threading
import time
from evdev import UInput, ecodes

from .config import MacroAction

_uinput:       UInput | None = None
_mouse_uinput: UInput | None = None
_char_map: dict[str, tuple[int, bool]] | None = None

_MOUSE_BTNS: dict[str, int] = {
    'left':    ecodes.BTN_LEFT,
    'right':   ecodes.BTN_RIGHT,
    'middle':  ecodes.BTN_MIDDLE,
    'button4': ecodes.BTN_SIDE,
    'button5': ecodes.BTN_EXTRA,
}

# ── key name → evdev keycode ──────────────────────────────────────────────────

_KEY_NAMES: dict[str, int] = {
    # modifiers
    'ctrl':    ecodes.KEY_LEFTCTRL,   'lctrl':   ecodes.KEY_LEFTCTRL,
    'rctrl':   ecodes.KEY_RIGHTCTRL,  'control': ecodes.KEY_LEFTCTRL,
    'alt':     ecodes.KEY_LEFTALT,    'lalt':    ecodes.KEY_LEFTALT,
    'ralt':    ecodes.KEY_RIGHTALT,   'altgr':   ecodes.KEY_RIGHTALT,
    'shift':   ecodes.KEY_LEFTSHIFT,  'lshift':  ecodes.KEY_LEFTSHIFT,
    'rshift':  ecodes.KEY_RIGHTSHIFT,
    'super':   ecodes.KEY_LEFTMETA,   'win':     ecodes.KEY_LEFTMETA,
    'meta':    ecodes.KEY_LEFTMETA,   'cmd':     ecodes.KEY_LEFTMETA,
    # common
    'tab':       ecodes.KEY_TAB,        'enter':     ecodes.KEY_ENTER,
    'return':    ecodes.KEY_ENTER,      'esc':       ecodes.KEY_ESC,
    'escape':    ecodes.KEY_ESC,        'space':     ecodes.KEY_SPACE,
    'backspace': ecodes.KEY_BACKSPACE,  'delete':    ecodes.KEY_DELETE,
    'del':       ecodes.KEY_DELETE,     'insert':    ecodes.KEY_INSERT,
    'ins':       ecodes.KEY_INSERT,     'capslock':  ecodes.KEY_CAPSLOCK,
    'caps_lock': ecodes.KEY_CAPSLOCK,   'menu':      ecodes.KEY_COMPOSE,
    'printscreen': ecodes.KEY_SYSRQ,   'pause':     ecodes.KEY_PAUSE,
    # symbol keys
    '-':  ecodes.KEY_MINUS,      '=':  ecodes.KEY_EQUAL,
    '[':  ecodes.KEY_LEFTBRACE,  ']':  ecodes.KEY_RIGHTBRACE,
    '\\': ecodes.KEY_BACKSLASH,  ';':  ecodes.KEY_SEMICOLON,
    "'":  ecodes.KEY_APOSTROPHE, ',':  ecodes.KEY_COMMA,
    '.':  ecodes.KEY_DOT,        '/':  ecodes.KEY_SLASH,
    '`':  ecodes.KEY_GRAVE,
    # navigation
    'home':     ecodes.KEY_HOME,      'end':      ecodes.KEY_END,
    'pageup':   ecodes.KEY_PAGEUP,    'pgup':     ecodes.KEY_PAGEUP,
    'pagedown': ecodes.KEY_PAGEDOWN,  'pgdn':     ecodes.KEY_PAGEDOWN,
    'up':       ecodes.KEY_UP,        'down':     ecodes.KEY_DOWN,
    'left':     ecodes.KEY_LEFT,      'right':    ecodes.KEY_RIGHT,
    # f-keys
    **{f'f{i}': getattr(ecodes, f'KEY_F{i}') for i in range(1, 25)},
}

# key name → X11 keysym name (for xdotool fallback)
_XDOTOOL_MAP: dict[str, str] = {
    'ctrl': 'ctrl', 'lctrl': 'ctrl', 'rctrl': 'ctrl', 'control': 'ctrl',
    'alt': 'alt', 'lalt': 'alt', 'ralt': 'alt', 'altgr': 'alt',
    'shift': 'shift', 'lshift': 'shift', 'rshift': 'shift',
    'super': 'super', 'win': 'super', 'meta': 'super', 'cmd': 'super',
    'tab': 'Tab', 'enter': 'Return', 'return': 'Return',
    'esc': 'Escape', 'escape': 'Escape', 'space': 'space',
    'backspace': 'BackSpace', 'delete': 'Delete', 'del': 'Delete',
    'insert': 'Insert', 'ins': 'Insert',
    'capslock': 'Caps_Lock', 'caps_lock': 'Caps_Lock',
    'menu': 'Menu', 'printscreen': 'Print', 'pause': 'Pause',
    'home': 'Home', 'end': 'End',
    'pageup': 'Page_Up', 'pgup': 'Page_Up',
    'pagedown': 'Page_Down', 'pgdn': 'Page_Down',
    'up': 'Up', 'down': 'Down', 'left': 'Left', 'right': 'Right',
    '-': 'minus', '=': 'equal', '[': 'bracketleft', ']': 'bracketright',
    '\\': 'backslash', ';': 'semicolon', "'": 'apostrophe',
    ',': 'comma', '.': 'period', '/': 'slash', '`': 'grave',
    **{f'f{i}': f'F{i}' for i in range(1, 25)},
}


def _resolve_keys(names: list[str]) -> list[int]:
    codes = []
    for name in names:
        n = name.lower().strip()
        if n in _KEY_NAMES:
            codes.append(_KEY_NAMES[n])
        elif len(n) == 1 and n.isalpha():
            codes.append(getattr(ecodes, f'KEY_{n.upper()}'))
        elif len(n) == 1 and n.isdigit():
            codes.append(getattr(ecodes, f'KEY_{n}'))
        else:
            print(f'[macro] unknown key name: {name!r}')
    return codes


# ── public API ────────────────────────────────────────────────────────────────

def set_uinput(ui: UInput) -> None:
    global _uinput, _char_map
    _uinput = ui
    _char_map = _get_char_map()


def set_mouse_uinput(ui: UInput) -> None:
    global _mouse_uinput
    _mouse_uinput = ui


def run(action: MacroAction) -> None:
    if action.action == 'none':
        return
    threading.Thread(target=_execute, args=(action,), daemon=True).start()


def run_hold(action: MacroAction, press: bool) -> None:
    codes = _resolve_keys(action.keys)
    if codes:
        threading.Thread(target=_send_keys, args=(codes, press), daemon=True).start()


def run_mouse_hold(action: MacroAction, press: bool) -> None:
    code = _MOUSE_BTNS.get(action.mouse_btn)
    if code is not None:
        threading.Thread(target=_send_mouse_btn, args=(code, press), daemon=True).start()


def _execute(action: MacroAction) -> None:
    if action.action == 'type' and action.text:
        _type_text(action.text)
    elif action.action == 'command' and action.cmd:
        _run_command(action.cmd)
    elif action.action == 'combo' and action.keys:
        if _uinput is not None:
            codes = _resolve_keys(action.keys)
            if codes:
                _fire_combo(codes)
        else:
            _fire_combo_xdotool(action.keys)
    elif action.action == 'mouse_button':
        code = _MOUSE_BTNS.get(action.mouse_btn)
        if code is not None:
            count = 2 if action.mouse_mode == 'double_click' else 1
            _fire_mouse_click(code, count)


# ── display detection ────────────────────────────────────────────────────────

def _get_display() -> str:
    display = os.environ.get('DISPLAY')
    if display:
        return display
    try:
        out = subprocess.run(['who'], capture_output=True, text=True).stdout
        for line in out.splitlines():
            if '(' in line and ')' in line:
                candidate = line[line.rfind('(') + 1 : line.rfind(')')]
                if candidate.startswith(':'):
                    return candidate
    except Exception:
        pass
    return ':0'


# ── key sending ───────────────────────────────────────────────────────────────

def _send_keys(codes: list[int], press: bool) -> None:
    """Press or release a list of keys in sequence (reversed for release)."""
    ui = _uinput
    if ui is None:
        return
    seq = codes if press else list(reversed(codes))
    val = 1 if press else 0
    for code in seq:
        ui.write(ecodes.EV_KEY, code, val)
        ui.syn()
        time.sleep(0.008)


def _fire_combo(codes: list[int]) -> None:
    # Build reverse map: evdev keycode → canonical name (first entry wins)
    code_to_name: dict[int, str] = {}
    for name, code in _KEY_NAMES.items():
        code_to_name.setdefault(code, name)

    xnames = []
    for code in codes:
        name = code_to_name.get(code)
        if name and name in _XDOTOOL_MAP:
            xnames.append(_XDOTOOL_MAP[name])
        elif name and len(name) == 1:
            xnames.append(name)
        else:
            # fall back to evdev constant (e.g. KEY_A → 'a', KEY_5 → '5')
            evdev_name = ecodes.KEY.get(code, '')
            if evdev_name.startswith('KEY_') and len(evdev_name) == 5:
                xnames.append(evdev_name[4].lower())
            else:
                print(f'[macro] unknown xdotool mapping for evdev code: {code}')

    if not xnames:
        return
    key_str = '+'.join(xnames)
    print(f'[macro] firing combo via xdotool: {key_str}')
    subprocess.run(
        ['xdotool', 'key', '--clearmodifiers', key_str],
        env={**os.environ, 'DISPLAY': _get_display(), 'XAUTHORITY': glob.glob('/run/user/1000/xauth_*')[0]},
        check=False,
    )


def _fire_combo_xdotool(names: list[str]) -> None:
    xnames = []
    for name in names:
        n = name.lower().strip()
        if n in _XDOTOOL_MAP:
            xnames.append(_XDOTOOL_MAP[n])
        elif len(n) == 1 and (n.isalpha() or n.isdigit()):
            xnames.append(n)
        else:
            print(f'[macro] unknown xdotool key name: {name!r}')
    if not xnames:
        return
    chord = '+'.join(xnames)
    print(f'[macro] firing combo via xdotool: {chord}')
    try:
        subprocess.run(
            ['xdotool', 'key', chord],
            env={**os.environ, 'DISPLAY': _get_display()},
            check=False,
        )
    except FileNotFoundError:
        print('[macro] xdotool not found')


def _send_mouse_btn(code: int, press: bool) -> None:
    ui = _mouse_uinput
    if ui is None:
        return
    ui.write(ecodes.EV_KEY, code, 1 if press else 0)
    ui.syn()


def _fire_mouse_click(code: int, count: int) -> None:
    ui = _mouse_uinput
    if ui is None:
        return
    for i in range(count):
        ui.write(ecodes.EV_KEY, code, 1)
        ui.syn()
        time.sleep(0.005)
        ui.write(ecodes.EV_KEY, code, 0)
        ui.syn()
        if i < count - 1:
            time.sleep(0.1)


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
