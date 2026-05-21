"""Keyframe timeline widget for the animation editor."""
from __future__ import annotations

from PySide6.QtCore   import QPointF, Qt, Signal
from PySide6.QtGui    import (QColor, QFont, QFontMetrics, QPainter, QPen,
                               QPolygonF)
from PySide6.QtWidgets import QMenu, QWidget

from kyxen_keys.lighting_config import Keyframe


# ── Geometry / colour constants ───────────────────────────────────────────────

_RULER_H  = 22   # height of time ruler in px
_TRACK_H  = 46   # height of keyframe track in px
_TOTAL_H  = _RULER_H + _TRACK_H
_MARGIN   = 24   # left/right track margin
_DIA_R    =  6   # diamond half-size
_PH_HIT   =  5   # playhead click hit zone (±px)
_KF_HIT   =  8   # keyframe click hit zone (±px)

_COL_BG        = QColor(24, 24, 24)
_COL_RULER_BG  = QColor(32, 32, 32)
_COL_TRACK_BG  = QColor(18, 18, 18)
_COL_TICK      = QColor(70, 70, 70)
_COL_TICK_MAJ  = QColor(110, 110, 110)
_COL_TRACK_LN  = QColor(44, 44, 44)
_COL_KF        = QColor(155, 155, 155)
_COL_KF_SEL    = QColor(255, 200, 0)
_COL_PLAYHEAD  = QColor(210, 60, 60)

# Dot colour below each diamond indicates transition type
_TRANS_COLOURS: dict[str, QColor] = {
    'linear':  QColor(70, 150, 230),
    'ease':    QColor(70, 220, 150),
    'hsv':     QColor(190, 70, 230),
    'instant': QColor(230, 110, 70),
}

# Tick step options (seconds) — first one where px/tick >= _MIN_TICK_PX is used
_TICK_STEPS   = (0.05, 0.1, 0.2, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0)
_MIN_TICK_PX  = 18


class TimelineWidget(QWidget):
    """
    Horizontal keyframe timeline.

    Signals
    -------
    playhead_changed(float)         scrub time changed
    keyframe_selected(int)          keyframe clicked; -1 = deselected
    keyframe_moved(int, float)      keyframe dragged to new time
    keyframe_add_requested(float)   empty-track click
    keyframe_delete_requested(int)  delete via context menu
    transition_changed(int, str)    transition type edited via context menu
    """

    playhead_changed          = Signal(float)
    keyframe_selected         = Signal(int)
    keyframe_moved            = Signal(int, float)
    keyframe_add_requested    = Signal(float)
    keyframe_delete_requested = Signal(int)
    transition_changed        = Signal(int, str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._duration  = 2.0
        self._keyframes: list[Keyframe] = []
        self._playhead  = 0.0
        self._selected  = -1

        self._drag: str | None = None   # 'ph' | 'kf'
        self._drag_kf   = -1

        self.setFixedHeight(_TOTAL_H)
        self.setMouseTracking(True)

        font = QFont()
        font.setPointSize(7)
        self._font = font
        self._fm   = QFontMetrics(font)

    # ── public ────────────────────────────────────────────────────────────────

    def set_animation(self, duration: float, keyframes: list[Keyframe]) -> None:
        self._duration  = max(duration, 0.1)
        self._keyframes = list(keyframes)
        self._selected  = min(self._selected, len(self._keyframes) - 1)
        self._playhead  = min(self._playhead, self._duration)
        self.update()

    def set_playhead(self, t: float) -> None:
        self._playhead = max(0.0, min(t, self._duration))
        self.update()

    def set_selected(self, idx: int) -> None:
        self._selected = idx
        self.update()

    def selected(self) -> int:
        return self._selected

    # ── coordinate helpers ────────────────────────────────────────────────────

    def _track_range(self):
        return _MARGIN, self.width() - _MARGIN

    def _t2x(self, t: float) -> float:
        x0, x1 = self._track_range()
        return x0 + (t / self._duration) * (x1 - x0) if self._duration else x0

    def _x2t(self, x: float) -> float:
        x0, x1 = self._track_range()
        span = x1 - x0
        if span <= 0:
            return 0.0
        return max(0.0, min((x - x0) / span * self._duration, self._duration))

    def _track_cy(self) -> float:
        return _RULER_H + _TRACK_H / 2

    def _kf_at(self, x: float, y: float) -> int:
        cy = self._track_cy()
        if abs(y - cy) > _KF_HIT + 2:
            return -1
        for i, kf in enumerate(self._keyframes):
            if abs(x - self._t2x(kf.time)) <= _KF_HIT:
                return i
        return -1

    def _near_ph(self, x: float) -> bool:
        return abs(x - self._t2x(self._playhead)) <= _PH_HIT

    # ── painting ──────────────────────────────────────────────────────────────

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w = self.width()
        x0, x1 = self._track_range()
        track_w = x1 - x0

        # Background
        p.fillRect(self.rect(), _COL_BG)

        # Ruler strip
        p.fillRect(0, 0, w, _RULER_H, _COL_RULER_BG)

        # Tick marks
        if self._duration > 0 and track_w > 0:
            tick_step = _TICK_STEPS[-1]
            for s in _TICK_STEPS:
                if track_w / (self._duration / s) >= _MIN_TICK_PX:
                    tick_step = s
                    break
            t = 0.0
            while t <= self._duration + 1e-9:
                tx = self._t2x(t)
                major = abs(t % 1.0) < 1e-9 or tick_step >= 1.0
                p.setPen(QPen(_COL_TICK_MAJ if major else _COL_TICK, 1))
                th = 7 if major else 3
                p.drawLine(int(tx), _RULER_H - th, int(tx), _RULER_H)
                if major:
                    label = f'{int(t)}s' if t == int(t) else f'{t:.1f}s'
                    lw = self._fm.horizontalAdvance(label)
                    p.setPen(QPen(_COL_TICK_MAJ))
                    p.setFont(self._font)
                    p.drawText(int(tx - lw / 2), _RULER_H - th - 2, label)
                t = round(t + tick_step, 9)

        # Track area
        p.fillRect(0, _RULER_H, w, _TRACK_H, _COL_TRACK_BG)
        cy = int(self._track_cy())
        p.setPen(QPen(_COL_TRACK_LN, 1))
        p.drawLine(x0, cy, x1, cy)

        # Playhead (behind diamonds)
        ph_x = int(self._t2x(self._playhead))
        p.setPen(QPen(_COL_PLAYHEAD, 2))
        p.drawLine(ph_x, 0, ph_x, self.height())

        # Keyframe diamonds
        for i, kf in enumerate(self._keyframes):
            kx  = self._t2x(kf.time)
            sel = (i == self._selected)
            col = _COL_KF_SEL if sel else _COL_KF

            diamond = QPolygonF([
                QPointF(kx,          cy - _DIA_R),
                QPointF(kx + _DIA_R, cy),
                QPointF(kx,          cy + _DIA_R),
                QPointF(kx - _DIA_R, cy),
            ])
            p.setBrush(col)
            p.setPen(QPen(col.darker(160) if not sel else QColor(200, 140, 0), 1))
            p.drawPolygon(diamond)

            # Transition-type dot below diamond
            dot_col = _TRANS_COLOURS.get(kf.transition, QColor(100, 100, 100))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(dot_col)
            p.drawEllipse(QPointF(kx, cy + _DIA_R + 5), 3, 3)

        p.end()

    # ── mouse ─────────────────────────────────────────────────────────────────

    def mousePressEvent(self, event) -> None:
        x = event.position().x()
        y = event.position().y()

        if event.button() == Qt.MouseButton.RightButton:
            idx = self._kf_at(x, y)
            if idx >= 0:
                self._show_context(idx, event.globalPosition().toPoint())
            return

        if event.button() != Qt.MouseButton.LeftButton:
            return

        idx = self._kf_at(x, y)
        if idx >= 0:
            self._selected = idx
            self._drag     = 'kf'
            self._drag_kf  = idx
            self.keyframe_selected.emit(idx)
            self.update()
        elif self._near_ph(x):
            self._drag = 'ph'
            self._scrub(x)
        else:
            # Empty track click → request new keyframe
            t = round(self._x2t(x), 3)
            self.keyframe_add_requested.emit(t)

    def mouseMoveEvent(self, event) -> None:
        if not (event.buttons() & Qt.MouseButton.LeftButton):
            return
        x = event.position().x()
        if self._drag == 'ph':
            self._scrub(x)
        elif self._drag == 'kf' and self._drag_kf >= 0:
            t = round(self._x2t(x), 3)
            if self._drag_kf == 0:
                t = 0.0   # first keyframe locked to t=0
            self._keyframes[self._drag_kf].time = t
            self.keyframe_moved.emit(self._drag_kf, t)
            self.update()

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag    = None
            self._drag_kf = -1

    def _scrub(self, x: float) -> None:
        t = self._x2t(x)
        self._playhead = t
        self.playhead_changed.emit(t)
        self.update()

    # ── context menu ─────────────────────────────────────────────────────────

    def _show_context(self, idx: int, global_pos) -> None:
        menu    = QMenu(self)
        del_act = menu.addAction('Delete keyframe')
        del_act.setEnabled(idx > 0)   # keyframe 0 is permanent

        sub = menu.addMenu('Transition')
        for name in ('linear', 'ease', 'hsv', 'instant'):
            a = sub.addAction(name.title())
            a.setCheckable(True)
            a.setChecked(self._keyframes[idx].transition == name)
            a.setData(name)

        action = menu.exec(global_pos)
        if action is None:
            return
        if action is del_act:
            self.keyframe_delete_requested.emit(idx)
        elif action.data() in ('linear', 'ease', 'hsv', 'instant'):
            self._keyframes[idx].transition = action.data()
            self.transition_changed.emit(idx, action.data())
            self.update()
