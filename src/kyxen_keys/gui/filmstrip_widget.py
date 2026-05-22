"""
FilmstripWidget — horizontal strip of slide thumbnails for the animation editor.

Each thumbnail is a scaled-down keyboard preview.  Between thumbnails are '+' add
buttons.  A selected thumbnail has a gold border.  Each thumbnail has a small '×'
delete handle in its top-right corner.
"""
from __future__ import annotations

from PySide6.QtCore    import QPoint, QRect, Qt, Signal
from PySide6.QtGui     import QColor, QFont, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import QScrollArea, QSizePolicy, QWidget

from kyxen_keys.gui.lighting_keyboard_widget import _PX_RECTS, _WIDGET_W, _WIDGET_H


# ── Layout constants ──────────────────────────────────────────────────────────

_THUMB_W  = 140    # thumbnail width  (px)
_THUMB_H  = 44     # thumbnail height (px)
_LABEL_H  = 14     # label strip below thumbnail
_ADD_W    = 18     # '+ add' button width
_ADD_H    = 18     # '+ add' button height
_DEL_SIZE = 12     # '×' delete handle size
_GAP      =  4     # gap between add btn and thumb (each side)
_VM       =  5     # top/bottom margin

# Total widget height
_STRIP_H = _VM + _THUMB_H + _LABEL_H + _VM

# Colours
_COL_BG      = QColor(22, 22, 22)
_COL_THUMB   = QColor(38, 38, 38)
_COL_SEL     = QColor(255, 200, 0)
_COL_ADD_BG  = QColor(50, 80, 50)
_COL_ADD_FG  = QColor(140, 200, 140)
_COL_DEL_BG  = QColor(90, 40, 40)
_COL_DEL_FG  = QColor(220, 120, 120)
_COL_LABEL   = QColor(160, 160, 160)


def _scale_x(thumb_x: int) -> float:
    return _THUMB_W / _WIDGET_W

def _scale_y() -> float:
    return _THUMB_H / _WIDGET_H


class FilmstripWidget(QWidget):
    """
    Horizontal filmstrip.  Must be placed inside a QScrollArea.

    Call set_slides() to refresh after any data change.
    """

    slide_selected  = Signal(int)   # thumbnail clicked → index
    slide_add_after = Signal(int)   # '+' clicked → insert after index (-1 = prepend)
    slide_delete    = Signal(int)   # '×' clicked → index to delete

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._slides: list[dict[str, QColor]] = []   # per-slide {key: QColor}
        self._base   = QColor('#00CC44')
        self._sel    = -1
        self._hov_add   = -2   # -2=none, -1=before-first, N=after-slide-N
        self._hov_del   = -1
        self._hov_thumb = -1

        font = QFont()
        font.setPointSize(7)
        self._font = font
        self._fm   = QFontMetrics(font)

        self.setFixedHeight(_STRIP_H)
        self.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
        self.setMouseTracking(True)

    # ── Public API ────────────────────────────────────────────────────────────

    def set_slides(
        self,
        slides_key_colours: list[dict[str, str]],
        base_colour_hex: str,
        selected: int,
    ) -> None:
        self._slides = [
            {k: QColor(v) for k, v in kc.items()}
            for kc in slides_key_colours
        ]
        self._base = QColor(base_colour_hex)
        self._sel  = selected
        self._recompute_width()
        self.update()

    def set_selected(self, idx: int) -> None:
        self._sel = idx
        self.update()

    # ── Geometry helpers ──────────────────────────────────────────────────────

    def _recompute_width(self) -> None:
        n = len(self._slides)
        # Layout: M | +add | gap | thumb | gap | +add | gap | thumb | ... | +add | M
        total = 10 + (n + 1) * (_ADD_W + _GAP) + n * (_THUMB_W + _GAP)
        self.setMinimumWidth(max(total, 200))
        self.resize(max(total, 200), _STRIP_H)

    def _add_rect(self, pos: int) -> QRect:
        """Rect for add button at pos (-1=before first, 0..N-1=after slide pos)."""
        n = len(self._slides)
        x = 5
        if pos == -1:
            # Before the first slide
            ay = _VM + (_THUMB_H - _ADD_H) // 2
            return QRect(x, ay, _ADD_W, _ADD_H)
        # After slide [pos]
        for i in range(pos + 1):
            x += _ADD_W + _GAP + _THUMB_W + _GAP
        ay = _VM + (_THUMB_H - _ADD_H) // 2
        return QRect(x, ay, _ADD_W, _ADD_H)

    def _thumb_rect(self, idx: int) -> QRect:
        """Rect for thumbnail idx."""
        x = 5 + _ADD_W + _GAP + idx * (_ADD_W + _GAP + _THUMB_W + _GAP)
        return QRect(x, _VM, _THUMB_W, _THUMB_H)

    def _del_rect(self, idx: int) -> QRect:
        """Rect for delete handle on thumbnail idx."""
        tr = self._thumb_rect(idx)
        return QRect(tr.right() - _DEL_SIZE, tr.top(), _DEL_SIZE, _DEL_SIZE)

    def _label_rect(self, idx: int) -> QRect:
        tr = self._thumb_rect(idx)
        return QRect(tr.x(), tr.bottom(), tr.width(), _LABEL_H)

    # ── Painting ──────────────────────────────────────────────────────────────

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), _COL_BG)

        n = len(self._slides)

        # Draw thumbnails
        sx = _THUMB_W / _WIDGET_W
        sy = _THUMB_H / _WIDGET_H
        for idx in range(n):
            tr    = self._thumb_rect(idx)
            kc    = self._slides[idx]
            sel   = (idx == self._sel)
            hovd  = (idx == self._hov_del)
            hovt  = (idx == self._hov_thumb)

            # Background (filled by key rects)
            p.fillRect(tr, _COL_THUMB)

            # Key colour rects (clipped to thumbnail)
            p.setClipRect(tr)
            for name, px in _PX_RECTS.items():
                colour = kc.get(name, self._base)
                kr = QRect(
                    tr.x() + int(px.x() * sx),
                    tr.y() + int(px.y() * sy),
                    max(1, int(px.width()  * sx)),
                    max(1, int(px.height() * sy)),
                )
                p.fillRect(kr, colour)
            p.setClipping(False)

            # Border
            if sel:
                pen = QPen(_COL_SEL, 2)
            elif hovt:
                pen = QPen(QColor(100, 100, 100), 1)
            else:
                pen = QPen(QColor(55, 55, 55), 1)
            p.setPen(pen)
            p.drawRect(tr.adjusted(0, 0, -1, -1))

            # Delete handle
            dr   = self._del_rect(idx)
            dclr = _COL_DEL_BG if hovd else QColor(60, 30, 30)
            p.fillRect(dr, dclr)
            p.setPen(QPen(_COL_DEL_FG if hovd else QColor(160, 80, 80), 1))
            p.setFont(self._font)
            p.drawText(dr, Qt.AlignCenter, '×')

            # Slide number label
            lr = self._label_rect(idx)
            p.setPen(QPen(_COL_SEL if sel else _COL_LABEL))
            p.setFont(self._font)
            p.drawText(lr, Qt.AlignCenter, f'Slide {idx + 1}')

        # Draw add buttons
        for pos in range(-1, n):
            ar   = self._add_rect(pos)
            hov  = (pos == self._hov_add)
            bg   = QColor(70, 100, 70) if hov else _COL_ADD_BG
            fg   = QColor(180, 240, 180) if hov else _COL_ADD_FG
            p.fillRect(ar, bg)
            p.setPen(QPen(fg, 1))
            p.setFont(self._font)
            p.drawText(ar, Qt.AlignCenter, '+')

        p.end()

    # ── Mouse ─────────────────────────────────────────────────────────────────

    def mouseMoveEvent(self, event) -> None:
        pos = event.pos()
        prev_ha, prev_hd, prev_ht = self._hov_add, self._hov_del, self._hov_thumb
        n = len(self._slides)

        self._hov_add   = -2
        self._hov_del   = -1
        self._hov_thumb = -1

        for pos_idx in range(-1, n):
            if self._add_rect(pos_idx).contains(pos):
                self._hov_add = pos_idx
                break

        if self._hov_add == -2:
            for idx in range(n):
                if self._del_rect(idx).contains(pos):
                    self._hov_del = idx
                    break
                if self._thumb_rect(idx).contains(pos):
                    self._hov_thumb = idx
                    break

        if (self._hov_add, self._hov_del, self._hov_thumb) != (prev_ha, prev_hd, prev_ht):
            self.update()

    def leaveEvent(self, _event) -> None:
        self._hov_add = -2
        self._hov_del = -1
        self._hov_thumb = -1
        self.update()

    def mousePressEvent(self, event) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            return
        pos = event.pos()
        n   = len(self._slides)

        for pos_idx in range(-1, n):
            if self._add_rect(pos_idx).contains(pos):
                self.slide_add_after.emit(pos_idx)
                return

        for idx in range(n):
            if self._del_rect(idx).contains(pos):
                self.slide_delete.emit(idx)
                return
            if self._thumb_rect(idx).contains(pos):
                self.slide_selected.emit(idx)
                return
