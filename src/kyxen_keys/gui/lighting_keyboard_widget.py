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

from PySide6.QtCore  import QPoint, QRect, QRectF, Qt, Signal
from PySide6.QtGui   import (QColor, QFont, QFontMetrics, QMouseEvent,
                              QPainter, QPen)
from PySide6.QtWidgets import QMenu, QWidget

from kyxen_keys.keyboard_layout import KeyRect as _KeyRect, LAYOUT as _LAYOUT
from kyxen_keys.keyboard_layout import (
    X_MAIN as _X_MAIN, X_NAV as _X_NAV, X_NP as _X_NP,
    Y_BOT as _Y_BOT, H_ROW as _H_ROW,
)


# ── Rendering constants ───────────────────────────────────────────────────────

_U      = 36   # pixels per key unit
_GAP    =  2   # gap between keys in pixels
_R      =  3   # corner radius
_MARGIN =  6   # outer widget margin px


# ── Pixel rect lookup ─────────────────────────────────────────────────────────

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
_WIDGET_H = int((_Y_BOT + _H_ROW + 0.15) * _U) + _MARGIN * 2

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
    'GAME_MODE': 'GM', 'M1': 'M1', 'M2': 'M2', 'M3': 'M3', 'MR': 'MR',
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
