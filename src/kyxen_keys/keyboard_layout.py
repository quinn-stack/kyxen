"""
Logitech G815 physical key layout — shared between the lighting engine and GUI.

All positions are in key units (1 unit = 1 standard key width ≈ 18mm).
X=0, Y=0 is the top-left corner of the G-key column.
"""
from __future__ import annotations
from typing import NamedTuple


class KeyRect(NamedTuple):
    name: str
    x:    float
    y:    float
    w:    float
    h:    float


# ── Position constants (key units) ────────────────────────────────────────────

X_MAIN = 1.25              # main block starts after G-key column
X_NAV  = X_MAIN + 15.25   # nav cluster
X_NP   = X_NAV  + 3.75    # numpad

Y_MEDIA = 0.00;  H_MEDIA = 0.60
Y_FN    = 0.72;  H_FN    = 0.70
Y_NUM   = 1.54;  H_ROW   = 1.00
Y_QWER  = 2.59
Y_ASDF  = 3.64
Y_ZXCV  = 4.69
Y_BOT   = 5.74

_ROW_GAP = 2 / 36  # inter-row gap in key units (matches widget _GAP/_U)


# ── Key layout ────────────────────────────────────────────────────────────────

LAYOUT: list[KeyRect] = [
    # G-keys
    KeyRect('G1', 0, Y_NUM,  1.0, H_ROW),
    KeyRect('G2', 0, Y_QWER, 1.0, H_ROW),
    KeyRect('G3', 0, Y_ASDF, 1.0, H_ROW),
    KeyRect('G4', 0, Y_ZXCV, 1.0, H_ROW),
    KeyRect('G5', 0, Y_BOT,  1.0, H_ROW),

    # Media row — logo, M-keys, illumination, media controls
    KeyRect('LOGO',         0.25,            Y_MEDIA, 0.75, H_MEDIA),
    KeyRect('M1',           X_MAIN + 1.75,   Y_MEDIA, 1.00, H_MEDIA),
    KeyRect('M2',           X_MAIN + 2.75,   Y_MEDIA, 1.00, H_MEDIA),
    KeyRect('M3',           X_MAIN + 3.75,   Y_MEDIA, 1.00, H_MEDIA),
    KeyRect('MR',           X_MAIN + 4.75,   Y_MEDIA, 1.00, H_MEDIA),
    KeyRect('GAME_MODE',    X_MAIN + 6.25,   Y_MEDIA, 1.00, H_MEDIA),
    KeyRect('ILLUMINATION', X_MAIN + 7.25,   Y_MEDIA, 1.00, H_MEDIA),
    KeyRect('MEDIA_PREV',   X_NP   + 0.00,   Y_MEDIA, 1.00, H_MEDIA),
    KeyRect('PLAY_PAUSE',   X_NP   + 1.00,   Y_MEDIA, 1.00, H_MEDIA),
    KeyRect('MEDIA_NEXT',   X_NP   + 2.00,   Y_MEDIA, 1.00, H_MEDIA),
    KeyRect('MUTE',         X_NP   + 3.00,   Y_MEDIA, 1.00, H_MEDIA),

    # Fn row — F1–F4 / 0.50u gap / F5–F8 / 1.00u gap / F9–F12
    KeyRect('ESC',          X_MAIN + 0.00,   Y_FN, 1.0, H_FN),
    KeyRect('F1',           X_MAIN + 1.75,   Y_FN, 1.0, H_FN),
    KeyRect('F2',           X_MAIN + 2.75,   Y_FN, 1.0, H_FN),
    KeyRect('F3',           X_MAIN + 3.75,   Y_FN, 1.0, H_FN),
    KeyRect('F4',           X_MAIN + 4.75,   Y_FN, 1.0, H_FN),
    KeyRect('F5',           X_MAIN + 6.25,   Y_FN, 1.0, H_FN),
    KeyRect('F6',           X_MAIN + 7.25,   Y_FN, 1.0, H_FN),
    KeyRect('F7',           X_MAIN + 8.25,   Y_FN, 1.0, H_FN),
    KeyRect('F8',           X_MAIN + 9.25,   Y_FN, 1.0, H_FN),
    KeyRect('F9',           X_MAIN + 11.25,  Y_FN, 1.0, H_FN),
    KeyRect('F10',          X_MAIN + 12.25,  Y_FN, 1.0, H_FN),
    KeyRect('F11',          X_MAIN + 13.25,  Y_FN, 1.0, H_FN),
    KeyRect('F12',          X_MAIN + 14.25,  Y_FN, 1.0, H_FN),
    KeyRect('PRINT_SCREEN', X_NAV  + 0.00,   Y_FN, 1.0, H_FN),
    KeyRect('SCROLL_LOCK',  X_NAV  + 1.00,   Y_FN, 1.0, H_FN),
    KeyRect('PAUSE',        X_NAV  + 2.00,   Y_FN, 1.0, H_FN),

    # Number row
    KeyRect('BACKTICK',  X_MAIN + 0.00,  Y_NUM, 1.00, H_ROW),
    KeyRect('1',         X_MAIN + 1.00,  Y_NUM, 1.00, H_ROW),
    KeyRect('2',         X_MAIN + 2.00,  Y_NUM, 1.00, H_ROW),
    KeyRect('3',         X_MAIN + 3.00,  Y_NUM, 1.00, H_ROW),
    KeyRect('4',         X_MAIN + 4.00,  Y_NUM, 1.00, H_ROW),
    KeyRect('5',         X_MAIN + 5.00,  Y_NUM, 1.00, H_ROW),
    KeyRect('6',         X_MAIN + 6.00,  Y_NUM, 1.00, H_ROW),
    KeyRect('7',         X_MAIN + 7.00,  Y_NUM, 1.00, H_ROW),
    KeyRect('8',         X_MAIN + 8.00,  Y_NUM, 1.00, H_ROW),
    KeyRect('9',         X_MAIN + 9.00,  Y_NUM, 1.00, H_ROW),
    KeyRect('0',         X_MAIN + 10.00, Y_NUM, 1.00, H_ROW),
    KeyRect('MINUS',     X_MAIN + 11.00, Y_NUM, 1.00, H_ROW),
    KeyRect('EQUALS',    X_MAIN + 12.00, Y_NUM, 1.00, H_ROW),
    KeyRect('BACKSPACE', X_MAIN + 13.00, Y_NUM, 2.25, H_ROW),
    KeyRect('INSERT',    X_NAV  + 0.00,  Y_NUM, 1.0,  H_ROW),
    KeyRect('HOME',      X_NAV  + 1.00,  Y_NUM, 1.0,  H_ROW),
    KeyRect('PAGE_UP',   X_NAV  + 2.00,  Y_NUM, 1.0,  H_ROW),
    KeyRect('NUM_LOCK',  X_NP   + 0.00,  Y_NUM, 1.0,  H_ROW),
    KeyRect('NUM_SLASH', X_NP   + 1.00,  Y_NUM, 1.0,  H_ROW),
    KeyRect('NUM_STAR',  X_NP   + 2.00,  Y_NUM, 1.0,  H_ROW),
    KeyRect('NUM_MINUS', X_NP   + 3.00,  Y_NUM, 1.0,  H_ROW),

    # QWERTY row
    KeyRect('TAB',       X_MAIN + 0.00,  Y_QWER, 1.50, H_ROW),
    KeyRect('Q',         X_MAIN + 1.50,  Y_QWER, 1.00, H_ROW),
    KeyRect('W',         X_MAIN + 2.50,  Y_QWER, 1.00, H_ROW),
    KeyRect('E',         X_MAIN + 3.50,  Y_QWER, 1.00, H_ROW),
    KeyRect('R',         X_MAIN + 4.50,  Y_QWER, 1.00, H_ROW),
    KeyRect('T',         X_MAIN + 5.50,  Y_QWER, 1.00, H_ROW),
    KeyRect('Y',         X_MAIN + 6.50,  Y_QWER, 1.00, H_ROW),
    KeyRect('U',         X_MAIN + 7.50,  Y_QWER, 1.00, H_ROW),
    KeyRect('I',         X_MAIN + 8.50,  Y_QWER, 1.00, H_ROW),
    KeyRect('O',         X_MAIN + 9.50,  Y_QWER, 1.00, H_ROW),
    KeyRect('P',         X_MAIN + 10.50, Y_QWER, 1.00, H_ROW),
    KeyRect('L_BRACKET', X_MAIN + 11.50, Y_QWER, 1.00, H_ROW),
    KeyRect('R_BRACKET', X_MAIN + 12.50, Y_QWER, 1.00, H_ROW),
    KeyRect('RETURN',    X_MAIN + 13.50, Y_QWER, 1.75, H_ROW),
    KeyRect('DELETE',    X_NAV  + 0.00,  Y_QWER, 1.0,  H_ROW),
    KeyRect('END',       X_NAV  + 1.00,  Y_QWER, 1.0,  H_ROW),
    KeyRect('PAGE_DOWN', X_NAV  + 2.00,  Y_QWER, 1.0,  H_ROW),
    KeyRect('NUM_7',     X_NP   + 0.00,  Y_QWER, 1.0,  H_ROW),
    KeyRect('NUM_8',     X_NP   + 1.00,  Y_QWER, 1.0,  H_ROW),
    KeyRect('NUM_9',     X_NP   + 2.00,  Y_QWER, 1.0,  H_ROW),
    KeyRect('NUM_PLUS',  X_NP   + 3.00,  Y_QWER, 1.0,  H_ROW * 2 + _ROW_GAP),

    # ASDF row
    KeyRect('CAPS_LOCK',  X_MAIN + 0.00,  Y_ASDF, 1.75, H_ROW),
    KeyRect('A',          X_MAIN + 1.75,  Y_ASDF, 1.00, H_ROW),
    KeyRect('S',          X_MAIN + 2.75,  Y_ASDF, 1.00, H_ROW),
    KeyRect('D',          X_MAIN + 3.75,  Y_ASDF, 1.00, H_ROW),
    KeyRect('F',          X_MAIN + 4.75,  Y_ASDF, 1.00, H_ROW),
    KeyRect('G',          X_MAIN + 5.75,  Y_ASDF, 1.00, H_ROW),
    KeyRect('H',          X_MAIN + 6.75,  Y_ASDF, 1.00, H_ROW),
    KeyRect('J',          X_MAIN + 7.75,  Y_ASDF, 1.00, H_ROW),
    KeyRect('K',          X_MAIN + 8.75,  Y_ASDF, 1.00, H_ROW),
    KeyRect('L',          X_MAIN + 9.75,  Y_ASDF, 1.00, H_ROW),
    KeyRect('SEMICOLON',  X_MAIN + 10.75, Y_ASDF, 1.00, H_ROW),
    KeyRect('APOSTROPHE', X_MAIN + 11.75, Y_ASDF, 1.00, H_ROW),
    KeyRect('HASH',       X_MAIN + 12.75, Y_ASDF, 1.00, H_ROW),
    KeyRect('NUM_4',      X_NP   + 0.00,  Y_ASDF, 1.0,  H_ROW),
    KeyRect('NUM_5',      X_NP   + 1.00,  Y_ASDF, 1.0,  H_ROW),
    KeyRect('NUM_6',      X_NP   + 2.00,  Y_ASDF, 1.0,  H_ROW),

    # ZXCV row
    KeyRect('L_SHIFT',    X_MAIN + 0.00,  Y_ZXCV, 1.25, H_ROW),
    KeyRect('BACKSLASH',  X_MAIN + 1.25,  Y_ZXCV, 1.00, H_ROW),
    KeyRect('Z',          X_MAIN + 2.25,  Y_ZXCV, 1.00, H_ROW),
    KeyRect('X',          X_MAIN + 3.25,  Y_ZXCV, 1.00, H_ROW),
    KeyRect('C',          X_MAIN + 4.25,  Y_ZXCV, 1.00, H_ROW),
    KeyRect('V',          X_MAIN + 5.25,  Y_ZXCV, 1.00, H_ROW),
    KeyRect('B',          X_MAIN + 6.25,  Y_ZXCV, 1.00, H_ROW),
    KeyRect('N',          X_MAIN + 7.25,  Y_ZXCV, 1.00, H_ROW),
    KeyRect('M',          X_MAIN + 8.25,  Y_ZXCV, 1.00, H_ROW),
    KeyRect('COMMA',      X_MAIN + 9.25,  Y_ZXCV, 1.00, H_ROW),
    KeyRect('PERIOD',     X_MAIN + 10.25, Y_ZXCV, 1.00, H_ROW),
    KeyRect('R_SLASH',    X_MAIN + 11.25, Y_ZXCV, 1.00, H_ROW),
    KeyRect('R_SHIFT',    X_MAIN + 12.25, Y_ZXCV, 3.00, H_ROW),
    KeyRect('UP',         X_NAV  + 1.00,  Y_ZXCV, 1.0,  H_ROW),
    KeyRect('NUM_1',      X_NP   + 0.00,  Y_ZXCV, 1.0,  H_ROW),
    KeyRect('NUM_2',      X_NP   + 1.00,  Y_ZXCV, 1.0,  H_ROW),
    KeyRect('NUM_3',      X_NP   + 2.00,  Y_ZXCV, 1.0,  H_ROW),
    KeyRect('NUM_ENTER',  X_NP   + 3.00,  Y_ZXCV, 1.0,  H_ROW * 2 + _ROW_GAP),

    # Bottom row
    KeyRect('L_CTRL',     X_MAIN + 0.00,  Y_BOT, 1.25, H_ROW),
    KeyRect('L_SUPER',    X_MAIN + 1.25,  Y_BOT, 1.25, H_ROW),
    KeyRect('L_ALT',      X_MAIN + 2.50,  Y_BOT, 1.25, H_ROW),
    KeyRect('SPACE',      X_MAIN + 3.75,  Y_BOT, 6.25, H_ROW),
    KeyRect('R_ALT',      X_MAIN + 10.00, Y_BOT, 1.25, H_ROW),
    KeyRect('R_SUPER',    X_MAIN + 11.25, Y_BOT, 1.25, H_ROW),
    KeyRect('CONTEXT',    X_MAIN + 12.50, Y_BOT, 1.25, H_ROW),
    KeyRect('R_CTRL',     X_MAIN + 13.75, Y_BOT, 1.50, H_ROW),
    KeyRect('LEFT',       X_NAV  + 0.00,  Y_BOT, 1.0,  H_ROW),
    KeyRect('DOWN',       X_NAV  + 1.00,  Y_BOT, 1.0,  H_ROW),
    KeyRect('RIGHT',      X_NAV  + 2.00,  Y_BOT, 1.0,  H_ROW),
    KeyRect('NUM_0',      X_NP   + 0.00,  Y_BOT, 2.0,  H_ROW),
    KeyRect('NUM_PERIOD', X_NP   + 2.00,  Y_BOT, 1.0,  H_ROW),
]
