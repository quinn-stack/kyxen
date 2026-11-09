"""
Keyboard layout handling for text injection.

uinput injects *physical* key codes; the desktop's XKB layout decides which
character each key produces. To type a character we therefore need the
reverse mapping for the user's layout: character → (evdev keycode, modifiers).

Layout selection, first match wins:
  1. ``keyboard_layout`` / ``keyboard_variant`` in ~/.config/kyxen/config.toml
  2. ``X11 Layout`` / ``X11 Variant`` from ``localectl status``
  3. ``us``

Supported layouts: us, gb, de, at (Austrian German is identical to German
for every character we type). Unknown layouts fall back to us.
"""
from __future__ import annotations
import subprocess
from dataclasses import dataclass, field

from evdev import ecodes

SHIFT = 0x01   # needs Shift held
ALTGR = 0x02   # needs AltGr (Right Alt / ISO_Level3_Shift) held

# char → (evdev keycode, modifier flags)
CharMap = dict[str, tuple[int, int]]


@dataclass
class TextLayout:
    name:      str
    chars:     CharMap
    # Characters produced by a dead key: the key is followed by Space so the
    # bare accent is emitted instead of being combined with the next letter.
    dead_keys: frozenset[str] = field(default_factory=frozenset)

    def lookup(self, ch: str) -> tuple[int, int] | None:
        return self.chars.get(ch)

    def needs_space_after(self, ch: str) -> bool:
        return ch in self.dead_keys


# ── maps ──────────────────────────────────────────────────────────────────────

def _letters_and_digits(swap_yz: bool = False) -> CharMap:
    m: CharMap = {}
    for c in 'abcdefghijklmnopqrstuvwxyz':
        key = c
        if swap_yz and c in 'yz':
            key = 'z' if c == 'y' else 'y'
        code = getattr(ecodes, f'KEY_{key.upper()}')
        m[c]         = (code, 0)
        m[c.upper()] = (code, SHIFT)
    for c in '1234567890':
        m[c] = (getattr(ecodes, f'KEY_{c}'), 0)
    m[' ']  = (ecodes.KEY_SPACE, 0)
    m['\n'] = (ecodes.KEY_ENTER, 0)
    m['\t'] = (ecodes.KEY_TAB,   0)
    return m


def _us_punctuation() -> CharMap:
    e = ecodes
    return {
        '-': (e.KEY_MINUS, 0),       '_': (e.KEY_MINUS, SHIFT),
        '=': (e.KEY_EQUAL, 0),       '+': (e.KEY_EQUAL, SHIFT),
        '[': (e.KEY_LEFTBRACE, 0),   '{': (e.KEY_LEFTBRACE, SHIFT),
        ']': (e.KEY_RIGHTBRACE, 0),  '}': (e.KEY_RIGHTBRACE, SHIFT),
        ';': (e.KEY_SEMICOLON, 0),   ':': (e.KEY_SEMICOLON, SHIFT),
        ',': (e.KEY_COMMA, 0),       '<': (e.KEY_COMMA, SHIFT),
        '.': (e.KEY_DOT, 0),         '>': (e.KEY_DOT, SHIFT),
        '/': (e.KEY_SLASH, 0),       '?': (e.KEY_SLASH, SHIFT),
        '!': (e.KEY_1, SHIFT),       ')': (e.KEY_0, SHIFT),
        '$': (e.KEY_4, SHIFT),       '%': (e.KEY_5, SHIFT),
        '^': (e.KEY_6, SHIFT),       '&': (e.KEY_7, SHIFT),
        '*': (e.KEY_8, SHIFT),       '(': (e.KEY_9, SHIFT),
    }


def _build_us() -> TextLayout:
    e = ecodes
    m = _letters_and_digits()
    m.update(_us_punctuation())
    m.update({
        '@':  (e.KEY_2, SHIFT),
        '#':  (e.KEY_3, SHIFT),
        "'":  (e.KEY_APOSTROPHE, 0),  '"': (e.KEY_APOSTROPHE, SHIFT),
        '`':  (e.KEY_GRAVE, 0),       '~': (e.KEY_GRAVE, SHIFT),
        '\\': (e.KEY_BACKSLASH, 0),   '|': (e.KEY_BACKSLASH, SHIFT),
    })
    return TextLayout('us', m)


def _build_gb() -> TextLayout:
    """UK (GB) QWERTY — differs from US for several symbols."""
    e = ecodes
    m = _letters_and_digits()
    m.update(_us_punctuation())
    m.update({
        '"':  (e.KEY_2, SHIFT),
        '£':  (e.KEY_3, SHIFT),
        '€':  (e.KEY_4, ALTGR),
        "'":  (e.KEY_APOSTROPHE, 0),  '@': (e.KEY_APOSTROPHE, SHIFT),
        '#':  (e.KEY_BACKSLASH, 0),   '~': (e.KEY_BACKSLASH, SHIFT),
        '`':  (e.KEY_GRAVE, 0),       '¬': (e.KEY_GRAVE, SHIFT),
        '\\': (e.KEY_102ND, 0),       '|': (e.KEY_102ND, SHIFT),
    })
    return TextLayout('gb', m)


def _build_de(name: str, dead_keys: bool) -> TextLayout:
    """German / Austrian QWERTZ (xkb ``de`` / ``at``)."""
    e = ecodes
    m = _letters_and_digits(swap_yz=True)
    m.update({
        # number row
        '^':  (e.KEY_GRAVE, 0),       '°': (e.KEY_GRAVE, SHIFT),
        '!':  (e.KEY_1, SHIFT),       '¹': (e.KEY_1, ALTGR),
        '"':  (e.KEY_2, SHIFT),       '²': (e.KEY_2, ALTGR),
        '§':  (e.KEY_3, SHIFT),       '³': (e.KEY_3, ALTGR),
        '$':  (e.KEY_4, SHIFT),
        '%':  (e.KEY_5, SHIFT),
        '&':  (e.KEY_6, SHIFT),
        '/':  (e.KEY_7, SHIFT),       '{': (e.KEY_7, ALTGR),
        '(':  (e.KEY_8, SHIFT),       '[': (e.KEY_8, ALTGR),
        ')':  (e.KEY_9, SHIFT),       ']': (e.KEY_9, ALTGR),
        '=':  (e.KEY_0, SHIFT),       '}': (e.KEY_0, ALTGR),
        'ß':  (e.KEY_MINUS, 0),       '?': (e.KEY_MINUS, SHIFT),
        '\\': (e.KEY_MINUS, ALTGR),
        '´':  (e.KEY_EQUAL, 0),       '`': (e.KEY_EQUAL, SHIFT),
        # letter rows
        '@':  (e.KEY_Q, ALTGR),
        '€':  (e.KEY_E, ALTGR),
        'µ':  (e.KEY_M, ALTGR),
        'ü':  (e.KEY_LEFTBRACE, 0),   'Ü': (e.KEY_LEFTBRACE, SHIFT),
        '+':  (e.KEY_RIGHTBRACE, 0),  '*': (e.KEY_RIGHTBRACE, SHIFT),
        '~':  (e.KEY_RIGHTBRACE, ALTGR),
        'ö':  (e.KEY_SEMICOLON, 0),   'Ö': (e.KEY_SEMICOLON, SHIFT),
        'ä':  (e.KEY_APOSTROPHE, 0),  'Ä': (e.KEY_APOSTROPHE, SHIFT),
        '#':  (e.KEY_BACKSLASH, 0),   "'": (e.KEY_BACKSLASH, SHIFT),
        '<':  (e.KEY_102ND, 0),       '>': (e.KEY_102ND, SHIFT),
        '|':  (e.KEY_102ND, ALTGR),
        ',':  (e.KEY_COMMA, 0),       ';': (e.KEY_COMMA, SHIFT),
        '.':  (e.KEY_DOT, 0),         ':': (e.KEY_DOT, SHIFT),
        '-':  (e.KEY_SLASH, 0),       '_': (e.KEY_SLASH, SHIFT),
    })
    dead = frozenset('^´`') if dead_keys else frozenset()
    return TextLayout(name, m, dead)


def build_layout(layout: str, variant: str = '') -> TextLayout:
    """Return the TextLayout for an XKB layout/variant name (falls back to us)."""
    layout  = (layout or 'us').strip().lower()
    variant = (variant or '').strip().lower()
    if layout in ('de', 'at'):
        return _build_de(layout, dead_keys='nodeadkeys' not in variant)
    if layout in ('gb', 'uk'):
        return _build_gb()
    if layout != 'us':
        print(f'[macro] keyboard layout {layout!r} not supported for text macros, using us')
    return _build_us()


# ── detection ─────────────────────────────────────────────────────────────────

def _first(value: str) -> str:
    """XKB allows comma-separated layout lists; the first one is the default."""
    return value.split(',')[0].strip()


def parse_localectl(output: str) -> tuple[str, str]:
    layout = variant = ''
    for line in output.splitlines():
        if ':' not in line:
            continue
        key, value = (s.strip() for s in line.split(':', 1))
        if key == 'X11 Layout':
            layout = _first(value)
        elif key == 'X11 Variant':
            variant = _first(value)
    return layout, variant


def detect_layout() -> tuple[str, str]:
    """Return (layout, variant) using config override → localectl → us."""
    try:
        from . import config as cfg
        gcfg = cfg.load_global_config()
        if gcfg.get('keyboard_layout'):
            return str(gcfg['keyboard_layout']), str(gcfg.get('keyboard_variant', ''))
    except Exception:
        pass
    try:
        out = subprocess.run(['localectl', 'status'], capture_output=True, text=True).stdout
        layout, variant = parse_localectl(out)
        if layout:
            return layout, variant
    except Exception:
        pass
    return 'us', ''
