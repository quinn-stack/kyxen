"""
LightingKeyboardWidget — QPainter-based interactive G815 keyboard for the lighting editor.

Each key is a clickable, paintable rectangle that displays its assigned colour.
Supports select mode (click / rubber-band drag) and brush mode (paint while dragging).

Signals
-------
selection_changed(list[str])   emitted whenever the selected key set changes
key_entered(str)               emitted on every key the cursor enters while LMB is held
                               (used by the editor to apply brush colour)
"""
from __future__ import annotations
from typing import NamedTuple

from PySide6.QtCore  import QPoint, QRect, QRectF, Qt, Signal
from PySide6.QtGui   import (QColor, QFont, QFontMetrics, QMouseEvent,
                              QPainter, QPen)
from PySide6.QtWidgets import QMenu, QWidget


# ── Layout constants ──────────────────────────────────────────────────────────

_U   = 36      # pixels per key unit
_GAP =  2      # gap between keys in pixels
_R   =  3      # corner radius

# Row Y positions and heights (key units)
_Y_MEDIA =  0.00;  _H_MEDIA = 0.60
_Y_FN    =  0.72;  _H_FN    = 0.70
_Y_NUM   =  1.54;  _H_ROW   = 1.00   # all remaining rows share this height
_Y_QWER  =  2.59
_Y_ASDF  =  3.64
_Y_ZXCV  =  4.69
_Y_BOT   =  5.74
_Y_LOGO  =  6.90;  _H_LOGO  = 0.50

# X offsets (key units)
_X_MAIN  = 1.25   # main block starts after G-keys + gap
_X_NAV   = _X_MAIN + 15.25  # nav cluster (right of backspace gap)
_X_NP    = _X_NAV  + 3.75   # numpad

_MARGIN = 6   # outer widget margin px


class _KeyRect(NamedTuple):
    name: str
    x:    float   # key units
    y:    float
    w:    float
    h:    float


# ── Key layout ────────────────────────────────────────────────────────────────
# All positions in key units; pixel rect = (x*_U + _MARGIN, y*_U + _MARGIN, w*_U - _GAP, h*_U - _GAP)

_LAYOUT: list[_KeyRect] = [
    # G-keys ──────────────────────────────────────────────────────────────────
    _KeyRect('G1', 0, _Y_NUM,  1.0, _H_ROW),
    _KeyRect('G2', 0, _Y_QWER, 1.0, _H_ROW),
    _KeyRect('G3', 0, _Y_ASDF, 1.0, _H_ROW),
    _KeyRect('G4', 0, _Y_ZXCV, 1.0, _H_ROW),
    _KeyRect('G5', 0, _Y_BOT,  1.0, _H_ROW),

    # M-keys + Game Mode (top-left, same row as media keys) ──────────────────
    _KeyRect('GAME_MODE', 0.00, _Y_MEDIA, 0.75, _H_MEDIA),
    _KeyRect('M1',        0.75, _Y_MEDIA, 0.75, _H_MEDIA),
    _KeyRect('M2',        1.50, _Y_MEDIA, 0.75, _H_MEDIA),
    _KeyRect('M3',        2.25, _Y_MEDIA, 0.75, _H_MEDIA),

    # Media keys ──────────────────────────────────────────────────────────────
    _KeyRect('MEDIA_PREV', _X_MAIN + 11.75, _Y_MEDIA, 1.0, _H_MEDIA),
    _KeyRect('PLAY_PAUSE', _X_MAIN + 12.75, _Y_MEDIA, 1.0, _H_MEDIA),
    _KeyRect('MEDIA_NEXT', _X_MAIN + 13.75, _Y_MEDIA, 1.0, _H_MEDIA),
    _KeyRect('MUTE',       _X_MAIN + 14.75, _Y_MEDIA, 1.0, _H_MEDIA),

    # Fn row ──────────────────────────────────────────────────────────────────
    _KeyRect('ESC',          _X_MAIN + 0.00, _Y_FN, 1.0, _H_FN),
    _KeyRect('F1',           _X_MAIN + 1.50, _Y_FN, 1.0, _H_FN),
    _KeyRect('F2',           _X_MAIN + 2.50, _Y_FN, 1.0, _H_FN),
    _KeyRect('F3',           _X_MAIN + 3.50, _Y_FN, 1.0, _H_FN),
    _KeyRect('F4',           _X_MAIN + 4.50, _Y_FN, 1.0, _H_FN),
    _KeyRect('F5',           _X_MAIN + 5.75, _Y_FN, 1.0, _H_FN),
    _KeyRect('F6',           _X_MAIN + 6.75, _Y_FN, 1.0, _H_FN),
    _KeyRect('F7',           _X_MAIN + 7.75, _Y_FN, 1.0, _H_FN),
    _KeyRect('F8',           _X_MAIN + 8.75, _Y_FN, 1.0, _H_FN),
    _KeyRect('F9',           _X_MAIN + 10.00, _Y_FN, 1.0, _H_FN),
    _KeyRect('F10',          _X_MAIN + 11.00, _Y_FN, 1.0, _H_FN),
    _KeyRect('F11',          _X_MAIN + 12.00, _Y_FN, 1.0, _H_FN),
    _KeyRect('F12',          _X_MAIN + 13.00, _Y_FN, 1.0, _H_FN),
    _KeyRect('PRINT_SCREEN', _X_MAIN + 14.25, _Y_FN, 1.0, _H_FN),
    _KeyRect('SCROLL_LOCK',  _X_MAIN + 15.25, _Y_FN, 1.0, _H_FN),
    _KeyRect('PAUSE',        _X_MAIN + 16.25, _Y_FN, 1.0, _H_FN),
    _KeyRect('ILLUMINATION', _X_MAIN + 17.25, _Y_FN, 1.0, _H_FN),

    # Number row ──────────────────────────────────────────────────────────────
    _KeyRect('BACKTICK',  _X_MAIN + 0.00, _Y_NUM, 1.00, _H_ROW),
    _KeyRect('1',         _X_MAIN + 1.00, _Y_NUM, 1.00, _H_ROW),
    _KeyRect('2',         _X_MAIN + 2.00, _Y_NUM, 1.00, _H_ROW),
    _KeyRect('3',         _X_MAIN + 3.00, _Y_NUM, 1.00, _H_ROW),
    _KeyRect('4',         _X_MAIN + 4.00, _Y_NUM, 1.00, _H_ROW),
    _KeyRect('5',         _X_MAIN + 5.00, _Y_NUM, 1.00, _H_ROW),
    _KeyRect('6',         _X_MAIN + 6.00, _Y_NUM, 1.00, _H_ROW),
    _KeyRect('7',         _X_MAIN + 7.00, _Y_NUM, 1.00, _H_ROW),
    _KeyRect('8',         _X_MAIN + 8.00, _Y_NUM, 1.00, _H_ROW),
    _KeyRect('9',         _X_MAIN + 9.00, _Y_NUM, 1.00, _H_ROW),
    _KeyRect('0',         _X_MAIN + 10.00, _Y_NUM, 1.00, _H_ROW),
    _KeyRect('MINUS',     _X_MAIN + 11.00, _Y_NUM, 1.00, _H_ROW),
    _KeyRect('EQUALS',    _X_MAIN + 12.00, _Y_NUM, 1.00, _H_ROW),
    _KeyRect('BACKSPACE', _X_MAIN + 13.00, _Y_NUM, 2.25, _H_ROW),
    # Nav
    _KeyRect('INSERT',   _X_NAV + 0.00, _Y_NUM, 1.0, _H_ROW),
    _KeyRect('HOME',     _X_NAV + 1.00, _Y_NUM, 1.0, _H_ROW),
    _KeyRect('PAGE_UP',  _X_NAV + 2.00, _Y_NUM, 1.0, _H_ROW),
    # Numpad
    _KeyRect('NUM_LOCK',  _X_NP + 0.00, _Y_NUM, 1.0, _H_ROW),
    _KeyRect('NUM_SLASH', _X_NP + 1.00, _Y_NUM, 1.0, _H_ROW),
    _KeyRect('NUM_STAR',  _X_NP + 2.00, _Y_NUM, 1.0, _H_ROW),
    _KeyRect('NUM_MINUS', _X_NP + 3.00, _Y_NUM, 1.0, _H_ROW),

    # QWERTY row ──────────────────────────────────────────────────────────────
    _KeyRect('TAB',       _X_MAIN + 0.00, _Y_QWER, 1.50, _H_ROW),
    _KeyRect('Q',         _X_MAIN + 1.50, _Y_QWER, 1.00, _H_ROW),
    _KeyRect('W',         _X_MAIN + 2.50, _Y_QWER, 1.00, _H_ROW),
    _KeyRect('E',         _X_MAIN + 3.50, _Y_QWER, 1.00, _H_ROW),
    _KeyRect('R',         _X_MAIN + 4.50, _Y_QWER, 1.00, _H_ROW),
    _KeyRect('T',         _X_MAIN + 5.50, _Y_QWER, 1.00, _H_ROW),
    _KeyRect('Y',         _X_MAIN + 6.50, _Y_QWER, 1.00, _H_ROW),
    _KeyRect('U',         _X_MAIN + 7.50, _Y_QWER, 1.00, _H_ROW),
    _KeyRect('I',         _X_MAIN + 8.50, _Y_QWER, 1.00, _H_ROW),
    _KeyRect('O',         _X_MAIN + 9.50, _Y_QWER, 1.00, _H_ROW),
    _KeyRect('P',         _X_MAIN + 10.50, _Y_QWER, 1.00, _H_ROW),
    _KeyRect('L_BRACKET', _X_MAIN + 11.50, _Y_QWER, 1.00, _H_ROW),
    _KeyRect('R_BRACKET', _X_MAIN + 12.50, _Y_QWER, 1.00, _H_ROW),
    _KeyRect('RETURN',    _X_MAIN + 13.50, _Y_QWER, 1.75, _H_ROW),
    # Nav
    _KeyRect('DELETE',    _X_NAV + 0.00, _Y_QWER, 1.0, _H_ROW),
    _KeyRect('END',       _X_NAV + 1.00, _Y_QWER, 1.0, _H_ROW),
    _KeyRect('PAGE_DOWN', _X_NAV + 2.00, _Y_QWER, 1.0, _H_ROW),
    # Numpad (NUM_PLUS spans 2 rows)
    _KeyRect('NUM_7',     _X_NP + 0.00, _Y_QWER, 1.0, _H_ROW),
    _KeyRect('NUM_8',     _X_NP + 1.00, _Y_QWER, 1.0, _H_ROW),
    _KeyRect('NUM_9',     _X_NP + 2.00, _Y_QWER, 1.0, _H_ROW),
    _KeyRect('NUM_PLUS',  _X_NP + 3.00, _Y_QWER, 1.0, _H_ROW * 2 + _GAP / _U),

    # ASDF row ────────────────────────────────────────────────────────────────
    _KeyRect('CAPS_LOCK',  _X_MAIN + 0.00, _Y_ASDF, 1.75, _H_ROW),
    _KeyRect('A',          _X_MAIN + 1.75, _Y_ASDF, 1.00, _H_ROW),
    _KeyRect('S',          _X_MAIN + 2.75, _Y_ASDF, 1.00, _H_ROW),
    _KeyRect('D',          _X_MAIN + 3.75, _Y_ASDF, 1.00, _H_ROW),
    _KeyRect('F',          _X_MAIN + 4.75, _Y_ASDF, 1.00, _H_ROW),
    _KeyRect('G',          _X_MAIN + 5.75, _Y_ASDF, 1.00, _H_ROW),
    _KeyRect('H',          _X_MAIN + 6.75, _Y_ASDF, 1.00, _H_ROW),
    _KeyRect('J',          _X_MAIN + 7.75, _Y_ASDF, 1.00, _H_ROW),
    _KeyRect('K',          _X_MAIN + 8.75, _Y_ASDF, 1.00, _H_ROW),
    _KeyRect('L',          _X_MAIN + 9.75, _Y_ASDF, 1.00, _H_ROW),
    _KeyRect('SEMICOLON',  _X_MAIN + 10.75, _Y_ASDF, 1.00, _H_ROW),
    _KeyRect('APOSTROPHE', _X_MAIN + 11.75, _Y_ASDF, 1.00, _H_ROW),
    _KeyRect('HASH',       _X_MAIN + 12.75, _Y_ASDF, 1.00, _H_ROW),
    # Numpad
    _KeyRect('NUM_4',      _X_NP + 0.00, _Y_ASDF, 1.0, _H_ROW),
    _KeyRect('NUM_5',      _X_NP + 1.00, _Y_ASDF, 1.0, _H_ROW),
    _KeyRect('NUM_6',      _X_NP + 2.00, _Y_ASDF, 1.0, _H_ROW),

    # ZXCV row ────────────────────────────────────────────────────────────────
    _KeyRect('L_SHIFT',    _X_MAIN + 0.00, _Y_ZXCV, 1.25, _H_ROW),
    _KeyRect('BACKSLASH',  _X_MAIN + 1.25, _Y_ZXCV, 1.00, _H_ROW),
    _KeyRect('Z',          _X_MAIN + 2.25, _Y_ZXCV, 1.00, _H_ROW),
    _KeyRect('X',          _X_MAIN + 3.25, _Y_ZXCV, 1.00, _H_ROW),
    _KeyRect('C',          _X_MAIN + 4.25, _Y_ZXCV, 1.00, _H_ROW),
    _KeyRect('V',          _X_MAIN + 5.25, _Y_ZXCV, 1.00, _H_ROW),
    _KeyRect('B',          _X_MAIN + 6.25, _Y_ZXCV, 1.00, _H_ROW),
    _KeyRect('N',          _X_MAIN + 7.25, _Y_ZXCV, 1.00, _H_ROW),
    _KeyRect('M',          _X_MAIN + 8.25, _Y_ZXCV, 1.00, _H_ROW),
    _KeyRect('COMMA',      _X_MAIN + 9.25, _Y_ZXCV, 1.00, _H_ROW),
    _KeyRect('PERIOD',     _X_MAIN + 10.25, _Y_ZXCV, 1.00, _H_ROW),
    _KeyRect('R_SLASH',    _X_MAIN + 11.25, _Y_ZXCV, 1.00, _H_ROW),
    _KeyRect('R_SHIFT',    _X_MAIN + 12.25, _Y_ZXCV, 3.00, _H_ROW),
    # Nav
    _KeyRect('UP',         _X_NAV + 1.00, _Y_ZXCV, 1.0, _H_ROW),
    # Numpad (NUM_ENTER spans 2 rows)
    _KeyRect('NUM_1',      _X_NP + 0.00, _Y_ZXCV, 1.0, _H_ROW),
    _KeyRect('NUM_2',      _X_NP + 1.00, _Y_ZXCV, 1.0, _H_ROW),
    _KeyRect('NUM_3',      _X_NP + 2.00, _Y_ZXCV, 1.0, _H_ROW),
    _KeyRect('NUM_ENTER',  _X_NP + 3.00, _Y_ZXCV, 1.0, _H_ROW * 2 + _GAP / _U),

    # Bottom row ──────────────────────────────────────────────────────────────
    _KeyRect('L_CTRL',   _X_MAIN + 0.00, _Y_BOT, 1.25, _H_ROW),
    _KeyRect('L_SUPER',  _X_MAIN + 1.25, _Y_BOT, 1.25, _H_ROW),
    _KeyRect('L_ALT',    _X_MAIN + 2.50, _Y_BOT, 1.25, _H_ROW),
    _KeyRect('SPACE',    _X_MAIN + 3.75, _Y_BOT, 6.25, _H_ROW),
    _KeyRect('R_ALT',    _X_MAIN + 10.00, _Y_BOT, 1.25, _H_ROW),
    _KeyRect('R_SUPER',  _X_MAIN + 11.25, _Y_BOT, 1.25, _H_ROW),
    _KeyRect('CONTEXT',  _X_MAIN + 12.50, _Y_BOT, 1.25, _H_ROW),
    _KeyRect('R_CTRL',   _X_MAIN + 13.75, _Y_BOT, 1.50, _H_ROW),
    # Nav
    _KeyRect('LEFT',     _X_NAV + 0.00, _Y_BOT, 1.0, _H_ROW),
    _KeyRect('DOWN',     _X_NAV + 1.00, _Y_BOT, 1.0, _H_ROW),
    _KeyRect('RIGHT',    _X_NAV + 2.00, _Y_BOT, 1.0, _H_ROW),
    # Numpad
    _KeyRect('NUM_0',      _X_NP + 0.00, _Y_BOT, 2.0, _H_ROW),
    _KeyRect('NUM_PERIOD', _X_NP + 2.00, _Y_BOT, 1.0, _H_ROW),

    # Logo ────────────────────────────────────────────────────────────────────
    _KeyRect('LOGO', _X_MAIN + 5.50, _Y_LOGO, 2.0, _H_LOGO),
]

# Pre-build pixel rect lookup: name → QRect
def _build_px_rects() -> dict[str, QRect]:
    out = {}
    for kr in _LAYOUT:
        x = int(kr.x * _U) + _MARGIN
        y = int(kr.y * _U) + _MARGIN
        w = int(kr.w * _U) - _GAP
        h = int(kr.h * _U) - _GAP
        out[kr.name] = QRect(x, y, w, h)
    return out

_PX_RECTS: dict[str, QRect] = _build_px_rects()

_WIDGET_W = int((_X_NP + 4.0) * _U) + _MARGIN * 2
_WIDGET_H = int((_Y_LOGO + _H_LOGO + 0.15) * _U) + _MARGIN * 2

# ── Key labels ────────────────────────────────────────────────────────────────

_LABELS: dict[str, str] = {
    'BACKTICK': '`',  'MINUS': '-',  'EQUALS': '=',  'BACKSPACE': 'Bksp',
    'L_BRACKET': '[', 'R_BRACKET': ']', 'RETURN': 'Enter', 'CAPS_LOCK': 'Caps',
    'SEMICOLON': ';', 'APOSTROPHE': "'", 'HASH': '#',
    'L_SHIFT': 'Shift', 'BACKSLASH': '\\', 'COMMA': ',', 'PERIOD': '.',
    'R_SLASH': '/', 'R_SHIFT': 'Shift',
    'L_CTRL': 'Ctrl', 'L_SUPER': '⊞', 'L_ALT': 'Alt', 'SPACE': '',
    'R_ALT': 'Alt', 'R_SUPER': '⊞', 'CONTEXT': '≡', 'R_CTRL': 'Ctrl',
    'PRINT_SCREEN': 'PrtSc', 'SCROLL_LOCK': 'ScrLk', 'PAUSE': 'Pause',
    'ILLUMINATION': '💡',
    'INSERT': 'Ins', 'HOME': 'Home', 'PAGE_UP': 'PgUp',
    'DELETE': 'Del', 'END': 'End', 'PAGE_DOWN': 'PgDn',
    'UP': '▲', 'DOWN': '▼', 'LEFT': '◄', 'RIGHT': '►',
    'NUM_LOCK': 'NLk', 'NUM_SLASH': '/', 'NUM_STAR': '*', 'NUM_MINUS': '-',
    'NUM_7': '7', 'NUM_8': '8', 'NUM_9': '9', 'NUM_PLUS': '+',
    'NUM_4': '4', 'NUM_5': '5', 'NUM_6': '6',
    'NUM_1': '1', 'NUM_2': '2', 'NUM_3': '3', 'NUM_ENTER': 'Ent',
    'NUM_0': '0', 'NUM_PERIOD': '.',
    'MEDIA_PREV': '⏮', 'PLAY_PAUSE': '⏯', 'MEDIA_NEXT': '⏭', 'MUTE': '🔇',
    'GAME_MODE': 'GM', 'M1': 'M1', 'M2': 'M2', 'M3': 'M3',
    'G1': 'G1', 'G2': 'G2', 'G3': 'G3', 'G4': 'G4', 'G5': 'G5',
    'LOGO': 'LOGO',
}

# ── Zone definitions ──────────────────────────────────────────────────────────

_ZONES: dict[str, list[str]] = {
    'All':          list(_PX_RECTS.keys()),
    'Letters':      list('ABCDEFGHIJKLMNOPQRSTUVWXYZ'),
    'Number Row':   ['BACKTICK','1','2','3','4','5','6','7','8','9','0','MINUS','EQUALS','BACKSPACE'],
    'F-Keys':       ['F1','F2','F3','F4','F5','F6','F7','F8','F9','F10','F11','F12'],
    'WASD':         ['W','A','S','D'],
    'Arrows':       ['UP','DOWN','LEFT','RIGHT'],
    'Modifiers':    ['L_SHIFT','R_SHIFT','L_CTRL','R_CTRL','L_ALT','R_ALT','L_SUPER','R_SUPER','CAPS_LOCK'],
    'G-Keys':       ['G1','G2','G3','G4','G5'],
    'Numpad':       ['NUM_LOCK','NUM_SLASH','NUM_STAR','NUM_MINUS',
                     'NUM_7','NUM_8','NUM_9','NUM_PLUS',
                     'NUM_4','NUM_5','NUM_6',
                     'NUM_1','NUM_2','NUM_3','NUM_ENTER',
                     'NUM_0','NUM_PERIOD'],
    'Nav Cluster':  ['INSERT','DELETE','HOME','END','PAGE_UP','PAGE_DOWN','UP','DOWN','LEFT','RIGHT'],
    'Media Keys':   ['MEDIA_PREV','PLAY_PAUSE','MEDIA_NEXT','MUTE'],
    'Function Row': ['ESC','F1','F2','F3','F4','F5','F6','F7','F8','F9','F10','F11','F12'],
}

# ── Colour helpers ────────────────────────────────────────────────────────────

def _contrast(c: QColor) -> QColor:
    """Return black or white for readable label text on a given background."""
    lum = 0.299 * c.redF() + 0.587 * c.greenF() + 0.114 * c.blueF()
    return QColor(0, 0, 0) if lum > 0.45 else QColor(255, 255, 255)


_DEFAULT_KEY_COLOUR = QColor(30, 30, 30)
_SELECTED_BORDER    = QColor(255, 200, 0)    # gold selection outline
_INHERITED_BORDER   = QColor(80, 80, 80)     # dimmed outline = inherited/unset key
_RUBBER_FILL        = QColor(255, 200, 0, 40)
_RUBBER_BORDER      = QColor(255, 200, 0, 180)


# ── Widget ────────────────────────────────────────────────────────────────────

class LightingKeyboardWidget(QWidget):
    """
    Interactive G815 keyboard for the lighting editor.

    key_colours:  dict[str, QColor]  — current display state (set by editor)
    inherited:    set[str]           — keys whose colour is inherited (dashed outline)
    selection:    set[str]           — currently selected keys
    brush_mode:   bool               — if True, LMB drag paints keys instead of rubber-band
    """

    selection_changed = Signal(list)   # list[str] of selected key names
    key_entered       = Signal(str)    # key name when brush enters it during drag

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFixedSize(_WIDGET_W, _WIDGET_H)
        self.setMouseTracking(True)

        self.key_colours: dict[str, QColor] = {}
        self.inherited:   set[str]          = set()
        self.selection:   set[str]          = set()
        self.brush_mode:  bool              = False

        self._drag_start:   QPoint | None = None
        self._drag_rect:    QRect  | None = None
        self._drag_initial: set[str]      = set()
        self._last_brushed: str | None    = None

        font = QFont()
        font.setPointSize(7)
        font.setBold(False)
        self._font = font
        self._fm   = QFontMetrics(font)

    # ── Public API ────────────────────────────────────────────────────────────

    def set_colours(self, colours: dict[str, QColor], inherited: set[str] | None = None) -> None:
        """Update all key colours and trigger a repaint."""
        self.key_colours = dict(colours)
        self.inherited   = set(inherited) if inherited else set()
        self.update()

    def set_key_colour(self, name: str, colour: QColor, is_inherited: bool = False) -> None:
        self.key_colours[name] = colour
        if is_inherited:
            self.inherited.add(name)
        else:
            self.inherited.discard(name)
        self.update()

    def set_selection(self, names: list[str]) -> None:
        self.selection = set(names)
        self.update()

    def get_selection(self) -> list[str]:
        return sorted(self.selection)

    def select_zone(self, zone_name: str) -> None:
        keys = _ZONES.get(zone_name, [])
        self.selection = {k for k in keys if k in _PX_RECTS}
        self.selection_changed.emit(self.get_selection())
        self.update()

    def clear_selection(self) -> None:
        self.selection.clear()
        self.selection_changed.emit([])
        self.update()

    # ── Painting ──────────────────────────────────────────────────────────────

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setFont(self._font)

        # Background
        p.fillRect(self.rect(), QColor(18, 18, 18))

        for name, rect in _PX_RECTS.items():
            colour     = self.key_colours.get(name, _DEFAULT_KEY_COLOUR)
            selected   = name in self.selection
            is_inh     = name in self.inherited

            # Fill
            p.fillRect(rect, colour)

            # Border
            if selected:
                pen = QPen(_SELECTED_BORDER, 2)
            elif is_inh:
                pen = QPen(_INHERITED_BORDER, 1, Qt.DashLine)
            else:
                pen = QPen(colour.darker(140), 1)
            p.setPen(pen)
            p.drawRoundedRect(QRectF(rect).adjusted(0.5, 0.5, -0.5, -0.5), _R, _R)

            # Label
            label = _LABELS.get(name, name)
            if label:
                p.setPen(QPen(_contrast(colour)))
                p.drawText(rect, Qt.AlignCenter, label)

        # Rubber-band overlay
        if self._drag_rect and not self.brush_mode:
            p.fillRect(self._drag_rect, _RUBBER_FILL)
            p.setPen(QPen(_RUBBER_BORDER, 1))
            p.drawRect(self._drag_rect)

        p.end()

    # ── Mouse interaction ─────────────────────────────────────────────────────

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.LeftButton:
            return
        name = self._key_at(event.pos())

        if self.brush_mode:
            # Brush: paint the key under the cursor
            if name:
                self._last_brushed = name
                if name not in self.selection:
                    self.selection = {name}
                    self.selection_changed.emit(self.get_selection())
                self.key_entered.emit(name)
                self.update()
        else:
            # Select mode
            mods = event.modifiers()
            self._drag_start   = event.pos()
            self._drag_rect    = None
            self._drag_initial = set(self.selection)

            if name:
                if mods & Qt.ShiftModifier:
                    self.selection ^= {name}
                else:
                    self.selection = {name}
                self.selection_changed.emit(self.get_selection())
                self.update()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if not (event.buttons() & Qt.LeftButton):
            return
        name = self._key_at(event.pos())

        if self.brush_mode:
            if name and name != self._last_brushed:
                self._last_brushed = name
                self.selection.add(name)
                self.selection_changed.emit(self.get_selection())
                self.key_entered.emit(name)
                self.update()
        else:
            if self._drag_start is None:
                return
            self._drag_rect = QRect(self._drag_start, event.pos()).normalized()
            # Rubber-band selection
            in_band = {n for n, r in _PX_RECTS.items()
                       if self._drag_rect.intersects(r)}
            mods = event.modifiers()
            if mods & Qt.ShiftModifier:
                self.selection = self._drag_initial | in_band
            else:
                self.selection = in_band
            self.selection_changed.emit(self.get_selection())
            self.update()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.LeftButton:
            return
        self._drag_start    = None
        self._drag_rect     = None
        self._drag_initial  = set()
        self._last_brushed  = None
        self.update()

    def contextMenuEvent(self, event) -> None:
        menu = QMenu(self)
        menu.addAction('Select All',  lambda: self.select_zone('All'))
        menu.addSeparator()
        for zone_name in _ZONES:
            if zone_name == 'All':
                continue
            menu.addAction(zone_name, lambda z=zone_name: self.select_zone(z))
        menu.addSeparator()
        menu.addAction('Clear Selection', self.clear_selection)
        menu.exec(event.globalPos())

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _key_at(self, pos: QPoint) -> str | None:
        for name, rect in _PX_RECTS.items():
            if rect.contains(pos):
                return name
        return None
