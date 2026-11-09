"""Macro execution — type text, run commands, fire key combos, hold-toggle keys."""
from __future__ import annotations
import subprocess
import threading
import time
from evdev import UInput, ecodes

from .config import MacroAction
from . import text_layout
from .text_layout import TextLayout, SHIFT, ALTGR

_uinput:       UInput | None = None
_mouse_uinput: UInput | None = None
_layout:       TextLayout | None = None

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


def _resolve_keys(names: list[str]) -> list[int]:
    """Map combo key names to evdev keycodes.

    Single characters are looked up in the active text layout first, so a
    combo of ``ctrl`` + ``z`` presses the key that produces "z" — on QWERTZ
    that is the physical Y position. Characters that need Shift/AltGr on the
    active layout fall back to the US key position.
    """
    layout = _get_layout()
    codes = []
    for name in names:
        n = name.lower().strip()
        hit = layout.lookup(n) if len(n) == 1 else None
        if hit is not None and hit[1] == 0:
            codes.append(hit[0])
        elif n in _KEY_NAMES:
            codes.append(_KEY_NAMES[n])
        elif len(n) == 1 and n.isalpha() and n.isascii():
            codes.append(getattr(ecodes, f'KEY_{n.upper()}'))
        elif len(n) == 1 and n.isdigit():
            codes.append(getattr(ecodes, f'KEY_{n}'))
        else:
            print(f'[macro] unknown key name: {name!r}')
    return codes


def _get_layout() -> TextLayout:
    global _layout
    if _layout is None:
        name, variant = text_layout.detect_layout()
        _layout = text_layout.build_layout(name, variant)
        suffix = f' ({variant})' if variant else ''
        print(f'[macro] keyboard layout: {_layout.name}{suffix}')
    return _layout


def reset_layout() -> None:
    """Forget the cached layout so the next macro re-detects it."""
    global _layout
    _layout = None


# ── public API ────────────────────────────────────────────────────────────────

def set_uinput(ui: UInput) -> None:
    global _uinput
    _uinput = ui
    _get_layout()


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
        codes = _resolve_keys(action.keys)
        if codes:
            _fire_combo(codes)
    elif action.action == 'mouse_button':
        code = _MOUSE_BTNS.get(action.mouse_btn)
        if code is not None:
            count = 2 if action.mouse_mode == 'double_click' else 1
            _fire_mouse_click(code, count)


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
    _send_keys(codes, press=True)
    time.sleep(0.005)
    _send_keys(codes, press=False)


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


# ── injection ─────────────────────────────────────────────────────────────────

def _type_text(text: str) -> None:
    time.sleep(0.08)
    if _uinput is not None:
        _inject_uinput(text)
    else:
        _inject_subprocess(text)


_MODIFIER_KEYS = (
    (SHIFT, ecodes.KEY_LEFTSHIFT),
    (ALTGR, ecodes.KEY_RIGHTALT),
)


def text_to_key_events(text: str, layout: TextLayout) -> tuple[list[tuple[int, int]], list[str]]:
    """Translate text into (keycode, value) key events for the given layout.

    value is 1 for press and 0 for release. Returns (events, skipped_chars).
    Dead-key characters (e.g. ^ on QWERTZ) are followed by Space so the bare
    accent is produced.
    """
    events: list[tuple[int, int]] = []
    skipped: list[str] = []

    def tap(code: int, mods: int) -> None:
        held = [key for flag, key in _MODIFIER_KEYS if mods & flag]
        events.extend((key, 1) for key in held)
        events.append((code, 1))
        events.append((code, 0))
        events.extend((key, 0) for key in reversed(held))

    for ch in text:
        hit = layout.lookup(ch)
        if hit is None:
            skipped.append(ch)
            continue
        tap(*hit)
        if layout.needs_space_after(ch):
            tap(ecodes.KEY_SPACE, 0)
    return events, skipped


def _inject_uinput(text: str) -> None:
    ui = _uinput
    events, skipped = text_to_key_events(text, _get_layout())
    modifiers = {key for _, key in _MODIFIER_KEYS}
    for code, value in events:
        ui.write(ecodes.EV_KEY, code, value)
        ui.syn()
        time.sleep(0.008 if code in modifiers else 0.018)

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
