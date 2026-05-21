"""Lighting editor — separate window for per-key RGB, presets, and animation."""
from __future__ import annotations
import colorsys
import copy
import math
import time as _time

from PySide6.QtCore   import Qt, QTimer, Signal
from PySide6.QtGui    import QColor
from PySide6.QtWidgets import (
    QCheckBox, QColorDialog, QComboBox, QDoubleSpinBox, QFormLayout,
    QFrame, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QMainWindow,
    QPushButton, QScrollArea, QSlider, QTabBar, QVBoxLayout, QWidget,
)

from kyxen_keys import config as cfg
from kyxen_keys.lighting_config import AnimationConfig, Keyframe, LightingConfig, PresetConfig
from kyxen_keys.gui.lighting_keyboard_widget import (
    LightingKeyboardWidget, _LAYOUT, _PX_RECTS,
)
from kyxen_keys.gui.timeline_widget import TimelineWidget

_ALL_KEYS = list(_PX_RECTS.keys())

_PRESETS = [
    ('Breathing',    'breathing'),
    ('Wave',         'wave'),
    ('Rainbow Wave', 'rainbow_wave'),
    ('Colour Cycle', 'colour_cycle'),
]
_DIRECTIONS = [
    ('Left → Right', 'left_right'),
    ('Right → Left', 'right_left'),
    ('Top → Bottom', 'top_bottom'),
    ('Bottom → Top', 'bottom_top'),
    ('Radial',       'radial'),
]
_PRESET_COLOUR_N = {'breathing': 1, 'wave': 1, 'rainbow_wave': 0, 'colour_cycle': 4}


# ── Colour panel ──────────────────────────────────────────────────────────────

class ColourPanel(QWidget):
    """Docked left panel: colour swatch, hex input, HSV sliders, recent colours."""

    colour_changed = Signal(QColor)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFixedWidth(190)
        self._colour   = QColor('#00CC44')
        self._recent:  list[QColor] = []
        self._updating = False
        self._build_ui()

    # ── public ────────────────────────────────────────────────────────────────

    def colour(self) -> QColor:
        return QColor(self._colour)

    def set_colour(self, c: QColor, *, emit: bool = False) -> None:
        self._colour = QColor(c)
        self._sync_ui()
        if emit:
            self._push_recent(c)
            self.colour_changed.emit(QColor(c))

    # ── build ─────────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 8, 6, 6)
        layout.setSpacing(6)

        self._swatch = QPushButton()
        self._swatch.setFixedHeight(48)
        self._swatch.setToolTip('Click to open colour picker')
        self._swatch.clicked.connect(self._open_picker)
        layout.addWidget(self._swatch)

        hex_row = QHBoxLayout()
        hex_row.addWidget(QLabel('#'))
        self._hex = QLineEdit()
        self._hex.setMaxLength(6)
        self._hex.setPlaceholderText('RRGGBB')
        self._hex.editingFinished.connect(self._on_hex)
        hex_row.addWidget(self._hex)
        layout.addLayout(hex_row)

        grp = QGroupBox('HSV')
        fl  = QFormLayout(grp)
        fl.setSpacing(3)
        self._h = QSlider(Qt.Orientation.Horizontal); self._h.setRange(0, 359)
        self._s = QSlider(Qt.Orientation.Horizontal); self._s.setRange(0, 255)
        self._v = QSlider(Qt.Orientation.Horizontal); self._v.setRange(0, 255)
        fl.addRow('H', self._h)
        fl.addRow('S', self._s)
        fl.addRow('V', self._v)
        for sl in (self._h, self._s, self._v):
            sl.valueChanged.connect(self._on_hsv)
        layout.addWidget(grp)

        layout.addWidget(QLabel('Recent:'))
        self._recent_widget = QWidget()
        self._recent_row    = QHBoxLayout(self._recent_widget)
        self._recent_row.setContentsMargins(0, 0, 0, 0)
        self._recent_row.setSpacing(2)
        layout.addWidget(self._recent_widget)

        layout.addStretch()
        self._sync_ui()

    # ── internal ──────────────────────────────────────────────────────────────

    def _open_picker(self) -> None:
        c = QColorDialog.getColor(self._colour, self, 'Pick colour')
        if c.isValid():
            self.set_colour(c, emit=True)

    def _on_hex(self) -> None:
        text = self._hex.text().strip().lstrip('#')
        if len(text) == 6:
            c = QColor(f'#{text}')
            if c.isValid():
                self.set_colour(c, emit=True)

    def _on_hsv(self) -> None:
        if self._updating:
            return
        c = QColor.fromHsv(self._h.value(), self._s.value(), self._v.value())
        self._colour = c
        self._updating = True
        self._swatch.setStyleSheet(
            f'background-color:{c.name()};border:1px solid #444;border-radius:3px;'
        )
        self._hex.setText(c.name().lstrip('#'))
        self._updating = False
        self.colour_changed.emit(QColor(c))

    def _sync_ui(self) -> None:
        self._updating = True
        h, s, v, _ = self._colour.getHsv()
        self._h.setValue(max(0, h))
        self._s.setValue(s)
        self._v.setValue(v)
        self._swatch.setStyleSheet(
            f'background-color:{self._colour.name()};border:1px solid #444;border-radius:3px;'
        )
        self._hex.setText(self._colour.name().lstrip('#'))
        self._updating = False

    def _push_recent(self, c: QColor) -> None:
        name = c.name()
        self._recent = [x for x in self._recent if x.name() != name]
        self._recent.insert(0, QColor(c))
        self._recent = self._recent[:12]
        self._rebuild_recent()

    def _rebuild_recent(self) -> None:
        while self._recent_row.count():
            item = self._recent_row.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        for c in self._recent:
            col = QColor(c)
            btn = QPushButton()
            btn.setFixedSize(20, 20)
            btn.setToolTip(col.name())
            btn.setStyleSheet(f'background-color:{col.name()};border:1px solid #444;')
            btn.clicked.connect(lambda _, x=col: self.set_colour(x, emit=True))
            self._recent_row.addWidget(btn)
        self._recent_row.addStretch()


# ── Lighting editor window ────────────────────────────────────────────────────

class LightingEditorWindow(QMainWindow):
    """Per-key lighting editor, opened as a separate window from ProfilePanel."""

    closed = Signal()

    def __init__(self, profile: cfg.Profile, parent=None) -> None:
        super().__init__(parent)
        self._profile     = profile
        self._config      = copy.deepcopy(profile.lighting)
        self._tool        = 'select'
        self._anim_kf_sel = -1

        self._apply_timer = QTimer(self)
        self._apply_timer.setSingleShot(True)
        self._apply_timer.setInterval(400)
        self._apply_timer.timeout.connect(self._do_auto_apply)

        self.setWindowTitle(f'Lighting — {profile.display_name}')
        self.setMinimumSize(1100, 680)
        self._build_ui()
        self._load_config()

    # ── build ─────────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = QWidget()
        self.setCentralWidget(root)
        outer = QHBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self._cpanel = ColourPanel()
        self._cpanel.colour_changed.connect(self._on_colour)
        outer.addWidget(self._cpanel)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.VLine)
        sep.setFrameShadow(QFrame.Shadow.Sunken)
        outer.addWidget(sep)

        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(8, 8, 8, 8)
        rl.setSpacing(6)
        outer.addWidget(right, stretch=1)

        # Mode tab bar
        mode_row = QHBoxLayout()
        self._tabs = QTabBar()
        self._tabs.addTab('Static')
        self._tabs.addTab('Preset')
        self._tabs.addTab('Animation')
        self._tabs.currentChanged.connect(self._on_mode_tab)
        mode_row.addWidget(self._tabs)
        mode_row.addStretch()
        rl.addLayout(mode_row)

        # Tool bar (hidden in Preset mode)
        self._toolbar = self._build_toolbar()
        rl.addWidget(self._toolbar)

        # Keyboard widget
        self._kbd = LightingKeyboardWidget()
        self._kbd.selection_changed.connect(self._on_selection)
        self._kbd.key_entered.connect(self._on_key_brush)
        kbd_scroll = QScrollArea()
        kbd_scroll.setWidget(self._kbd)
        kbd_scroll.setWidgetResizable(False)
        kbd_scroll.setFrameShape(QFrame.Shape.NoFrame)
        rl.addWidget(kbd_scroll, stretch=1)

        # Mode-specific panels (one visible at a time)
        self._static_extra = QWidget()
        self._preset_panel = self._build_preset_panel()
        self._anim_panel   = self._build_anim_panel()
        for w in (self._static_extra, self._preset_panel, self._anim_panel):
            rl.addWidget(w)

        # Bottom buttons
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self._btn_save   = QPushButton('Save')
        self._btn_revert = QPushButton('Revert')
        self._btn_close  = QPushButton('Close')
        self._btn_save.setDefault(True)
        for b in (self._btn_save, self._btn_revert, self._btn_close):
            btn_row.addWidget(b)
        self._btn_save.clicked.connect(self._save)
        self._btn_revert.clicked.connect(self._revert)
        self._btn_close.clicked.connect(self.close)
        rl.addLayout(btn_row)

    def _build_toolbar(self) -> QWidget:
        bar = QWidget()
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        self._tool_btns: dict[str, QPushButton] = {}
        specs = [
            ('select',     'Select',     True,  'Click / rubber-band to select keys'),
            ('brush',      'Brush',      True,  'Click-drag to paint keys'),
            (None,         None,         False, None),
            ('fill_all',   'Fill All',   False, 'Fill all keys with the current colour'),
            ('gradient',   'Gradient',   False, 'Paint a gradient across the selection (or all keys)'),
            ('eyedropper', 'Eyedropper', True,  'Click a key to pick its colour'),
        ]
        for name, label, checkable, tip in specs:
            if name is None:
                s = QFrame()
                s.setFrameShape(QFrame.Shape.VLine)
                s.setFrameShadow(QFrame.Shadow.Sunken)
                layout.addWidget(s)
                continue
            btn = QPushButton(label)
            btn.setToolTip(tip)
            btn.setCheckable(checkable)
            btn.setFixedWidth(88)
            if checkable:
                btn.clicked.connect(lambda _, n=name: self._set_tool(n))
            else:
                btn.clicked.connect(lambda _, n=name: self._run_tool(n))
            self._tool_btns[name] = btn
            layout.addWidget(btn)

        layout.addStretch()
        return bar

    def _build_preset_panel(self) -> QWidget:
        panel = QWidget()
        fl    = QFormLayout(panel)
        fl.setContentsMargins(0, 4, 0, 0)
        fl.setSpacing(6)
        self._preset_fl = fl

        self._preset_name = QComboBox()
        for label, val in _PRESETS:
            self._preset_name.addItem(label, val)
        self._preset_name.currentIndexChanged.connect(self._on_preset_param)
        fl.addRow('Effect:', self._preset_name)

        speed_w = QWidget()
        speed_l = QHBoxLayout(speed_w)
        speed_l.setContentsMargins(0, 0, 0, 0)
        self._speed_slider = QSlider(Qt.Orientation.Horizontal)
        self._speed_slider.setRange(1, 50)
        self._speed_slider.setValue(10)
        self._speed_lbl = QLabel('1.0×')
        self._speed_lbl.setFixedWidth(36)
        self._speed_slider.valueChanged.connect(self._on_speed)
        speed_l.addWidget(self._speed_slider)
        speed_l.addWidget(self._speed_lbl)
        fl.addRow('Speed:', speed_w)

        self._dir_combo = QComboBox()
        for label, val in _DIRECTIONS:
            self._dir_combo.addItem(label, val)
        self._dir_combo.currentIndexChanged.connect(self._on_preset_param)
        fl.addRow('Direction:', self._dir_combo)

        colours_w = QWidget()
        colours_l = QHBoxLayout(colours_w)
        colours_l.setContentsMargins(0, 0, 0, 0)
        colours_l.setSpacing(4)
        self._pc_btns: list[QPushButton] = []
        self._pc_colours: list[str] = ['#00CC44', '#00CC44', '#0044CC', '#CC0044']
        for i in range(4):
            btn = QPushButton()
            btn.setFixedSize(28, 28)
            btn.clicked.connect(lambda _, idx=i: self._pick_pc(idx))
            self._pc_btns.append(btn)
            colours_l.addWidget(btn)
        colours_l.addStretch()
        fl.addRow('Colours:', colours_w)

        return panel

    def _build_anim_panel(self) -> QWidget:
        panel  = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 4, 0, 0)
        layout.setSpacing(4)

        # Controls row
        ctrl = QHBoxLayout()
        ctrl.setSpacing(8)

        ctrl.addWidget(QLabel('Duration:'))
        self._dur_spin = QDoubleSpinBox()
        self._dur_spin.setRange(0.1, 60.0)
        self._dur_spin.setSingleStep(0.5)
        self._dur_spin.setSuffix(' s')
        self._dur_spin.setValue(2.0)
        self._dur_spin.valueChanged.connect(self._on_anim_duration)
        ctrl.addWidget(self._dur_spin)

        self._loop_chk = QCheckBox('Loop')
        self._loop_chk.setChecked(True)
        self._loop_chk.toggled.connect(self._on_anim_loop)
        ctrl.addWidget(self._loop_chk)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.VLine)
        sep.setFrameShadow(QFrame.Shadow.Sunken)
        ctrl.addWidget(sep)

        self._btn_add_kf = QPushButton('+ Keyframe')
        self._btn_add_kf.setToolTip('Add keyframe at playhead position')
        self._btn_add_kf.clicked.connect(self._on_kf_add_btn)
        ctrl.addWidget(self._btn_add_kf)

        self._btn_del_kf = QPushButton('Delete')
        self._btn_del_kf.setEnabled(False)
        self._btn_del_kf.clicked.connect(self._on_kf_del_btn)
        ctrl.addWidget(self._btn_del_kf)

        ctrl.addWidget(QLabel('Transition:'))
        self._trans_combo = QComboBox()
        for label, val in (('Linear', 'linear'), ('Ease', 'ease'),
                            ('HSV hue', 'hsv'), ('Instant', 'instant')):
            self._trans_combo.addItem(label, val)
        self._trans_combo.setEnabled(False)
        self._trans_combo.currentIndexChanged.connect(self._on_kf_transition)
        ctrl.addWidget(self._trans_combo)

        ctrl.addStretch()
        layout.addLayout(ctrl)

        # Timeline
        self._timeline = TimelineWidget()
        self._timeline.keyframe_selected.connect(self._on_kf_selected)
        self._timeline.keyframe_add_requested.connect(self._on_kf_add)
        self._timeline.keyframe_delete_requested.connect(self._on_kf_del)
        self._timeline.keyframe_moved.connect(self._on_kf_moved)
        self._timeline.transition_changed.connect(self._on_kf_trans_ext)
        self._timeline.playhead_changed.connect(self._on_playhead_scrub)
        layout.addWidget(self._timeline)

        return panel

    # ── config load ───────────────────────────────────────────────────────────

    def _load_config(self) -> None:
        mode_idx = {'static': 0, 'preset': 1, 'animation': 2}.get(self._config.mode, 0)

        # Preset panel (suppress signals during load)
        pc = self._config.preset or PresetConfig()
        for widget, val in (
            (self._preset_name,  pc.name),
            (self._dir_combo,    pc.direction),
        ):
            widget.blockSignals(True)
            idx = widget.findData(val)
            if idx >= 0:
                widget.setCurrentIndex(idx)
            widget.blockSignals(False)
        self._speed_slider.blockSignals(True)
        self._speed_slider.setValue(int(pc.speed * 10))
        self._speed_lbl.setText(f'{pc.speed:.1f}×')
        self._speed_slider.blockSignals(False)
        for i, hex_c in enumerate(pc.colours[:4]):
            self._pc_colours[i] = hex_c
        self._refresh_pc_btns()
        self._refresh_pc_visibility()

        # Animation panel
        anim = self._config.animation or AnimationConfig()
        self._dur_spin.blockSignals(True)
        self._dur_spin.setValue(anim.duration)
        self._dur_spin.blockSignals(False)
        self._loop_chk.setChecked(anim.loop)
        kfs = anim.keyframes if anim.keyframes else [Keyframe(time=0.0)]
        self._timeline.set_animation(anim.duration, kfs)
        self._anim_kf_sel = 0 if kfs else -1
        self._timeline.set_selected(self._anim_kf_sel)
        self._update_anim_controls()

        # Mode tab (no signal — call handler directly)
        self._tabs.blockSignals(True)
        self._tabs.setCurrentIndex(mode_idx)
        self._tabs.blockSignals(False)
        self._on_mode_tab(mode_idx)

        self._refresh_kbd()
        self._set_tool('select')

    def _refresh_kbd(self) -> None:
        base = QColor(self._config.base_colour)
        colours:   dict[str, QColor] = {}
        inherited: set[str] = set()
        for key in _ALL_KEYS:
            if key in self._config.key_colours:
                colours[key] = QColor(self._config.key_colours[key])
            else:
                colours[key] = base
                inherited.add(key)
        self._kbd.set_colours(colours, inherited)

    def _refresh_kbd_for_kf(self, kf_idx: int) -> None:
        """Show accumulated key colours through keyframe kf_idx."""
        anim = self._config.animation
        if not anim or not anim.keyframes or kf_idx < 0:
            self._refresh_kbd()
            return
        resolved: dict[str, str] = {}
        for i in range(min(kf_idx + 1, len(anim.keyframes))):
            resolved.update(anim.keyframes[i].key_colours)
        base = QColor(self._config.base_colour)
        colours:   dict[str, QColor] = {}
        inherited: set[str] = set()
        for key in _ALL_KEYS:
            if key in resolved:
                colours[key] = QColor(resolved[key])
            else:
                colours[key] = base
                inherited.add(key)
        self._kbd.set_colours(colours, inherited)

    # ── mode switching ────────────────────────────────────────────────────────

    def _on_mode_tab(self, idx: int) -> None:
        modes = ['static', 'preset', 'animation']
        self._config.mode = modes[idx] if idx < len(modes) else 'static'
        self._toolbar.setVisible(idx != 1)
        self._static_extra.setVisible(idx == 0)
        self._preset_panel.setVisible(idx == 1)
        self._anim_panel.setVisible(idx == 2)
        self._kbd.setEnabled(idx != 1)

        if idx == 1:
            self._kbd.clear_selection()
            self._sync_preset_config()
            self._start_preset_preview()
        else:
            self._stop_preset_preview()

        if idx == 2 and self._anim_kf_sel >= 0:
            self._refresh_kbd_for_kf(self._anim_kf_sel)
        elif idx == 0:
            self._refresh_kbd()

    # ── tool bar ──────────────────────────────────────────────────────────────

    def _set_tool(self, name: str) -> None:
        self._tool = name
        self._kbd.brush_mode = (name == 'brush')
        for n, btn in self._tool_btns.items():
            if btn.isCheckable():
                btn.setChecked(n == name)
        if name == 'eyedropper':
            self._kbd.setCursor(Qt.CursorShape.CrossCursor)
        else:
            self._kbd.unsetCursor()

    def _run_tool(self, name: str) -> None:
        in_anim = (self._config.mode == 'animation' and self._anim_kf_sel >= 0
                   and self._config.animation)
        if name == 'fill_all':
            c = self._cpanel.colour()
            if in_anim:
                kf = self._config.animation.keyframes[self._anim_kf_sel]
                for key in _ALL_KEYS:
                    kf.key_colours[key] = c.name()
                self._refresh_kbd_for_kf(self._anim_kf_sel)
            else:
                for key in _ALL_KEYS:
                    self._config.key_colours[key] = c.name()
                self._refresh_kbd()
        elif name == 'gradient':
            self._apply_gradient(in_anim)

    def _apply_gradient(self, in_anim: bool) -> None:
        c1 = self._cpanel.colour()
        c2 = QColorDialog.getColor(QColor('#000000'), self, 'Gradient — end colour')
        if not c2.isValid():
            return
        target = list(self._kbd.selection) if self._kbd.selection else list(_ALL_KEYS)
        if not target:
            return
        pos = {kr.name: kr.x for kr in _LAYOUT}
        xs  = [pos.get(k, 0.0) for k in target]
        mn, mx = min(xs), max(xs)
        result: dict[str, str] = {}
        for key in target:
            t  = (pos.get(key, mn) - mn) / (mx - mn) if mx > mn else 0.0
            r  = int(c1.red()   + (c2.red()   - c1.red())   * t)
            g  = int(c1.green() + (c2.green() - c1.green()) * t)
            b  = int(c1.blue()  + (c2.blue()  - c1.blue())  * t)
            result[key] = QColor(r, g, b).name()
        if in_anim:
            kf = self._config.animation.keyframes[self._anim_kf_sel]
            kf.key_colours.update(result)
            self._refresh_kbd_for_kf(self._anim_kf_sel)
        else:
            self._config.key_colours.update(result)
            self._refresh_kbd()

    # ── keyboard callbacks ────────────────────────────────────────────────────

    def _on_selection(self, keys: list[str]) -> None:
        if self._tool == 'eyedropper':
            if len(keys) == 1:
                self._pick_colour_from_key(keys[0])
                self._set_tool('select')
            return
        if len(keys) == 1:
            self._pick_colour_from_key(keys[0])

    def _pick_colour_from_key(self, key: str) -> None:
        if self._config.mode == 'animation' and self._anim_kf_sel >= 0 and self._config.animation:
            resolved: dict[str, str] = {}
            for i in range(min(self._anim_kf_sel + 1, len(self._config.animation.keyframes))):
                resolved.update(self._config.animation.keyframes[i].key_colours)
            hex_c = resolved.get(key, self._config.base_colour)
        else:
            hex_c = self._config.key_colours.get(key, self._config.base_colour)
        self._cpanel.set_colour(QColor(hex_c))

    def _on_key_brush(self, key: str) -> None:
        c = self._cpanel.colour()
        if self._config.mode == 'animation' and self._anim_kf_sel >= 0 and self._config.animation:
            kf = self._config.animation.keyframes[self._anim_kf_sel]
            kf.key_colours[key] = c.name()
            self._kbd.set_key_colour(key, c, is_inherited=False)
        else:
            self._config.key_colours[key] = c.name()
            self._kbd.set_key_colour(key, c, is_inherited=False)

    def _on_colour(self, colour: QColor) -> None:
        sel = self._kbd.selection
        if self._config.mode == 'preset':
            # Colour panel drives preset slot 0 (primary colour)
            self._pc_colours[0] = colour.name()
            self._refresh_pc_btns()
            self._sync_preset_config()
            self._preview_t0 = _time.monotonic()
            self._schedule_auto_apply()
            return
        if self._config.mode == 'animation' and self._anim_kf_sel >= 0 and self._config.animation:
            kf = self._config.animation.keyframes[self._anim_kf_sel]
            if sel:
                for key in sel:
                    kf.key_colours[key] = colour.name()
            else:
                self._config.base_colour = colour.name()
            self._refresh_kbd_for_kf(self._anim_kf_sel)
        else:
            if sel:
                for key in sel:
                    self._config.key_colours[key] = colour.name()
            else:
                self._config.base_colour = colour.name()
            self._refresh_kbd()

    # ── preset controls ───────────────────────────────────────────────────────

    def _on_preset_param(self) -> None:
        self._sync_preset_config()
        self._refresh_pc_visibility()
        self._preview_t0 = _time.monotonic()   # restart animation on param change
        self._schedule_auto_apply()

    def _on_speed(self, val: int) -> None:
        self._speed_lbl.setText(f'{val / 10:.1f}×')
        self._sync_preset_config()
        self._schedule_auto_apply()

    def _sync_preset_config(self) -> None:
        if self._config.preset is None:
            self._config.preset = PresetConfig()
        self._config.preset.name      = self._preset_name.currentData()
        self._config.preset.speed     = self._speed_slider.value() / 10.0
        self._config.preset.direction = self._dir_combo.currentData()
        n = _PRESET_COLOUR_N.get(self._config.preset.name, 1)
        self._config.preset.colours   = self._pc_colours[:n] if n > 0 else [self._config.base_colour]

    def _pick_pc(self, idx: int) -> None:
        c = QColorDialog.getColor(QColor(self._pc_colours[idx]), self, f'Colour {idx + 1}')
        if c.isValid():
            self._pc_colours[idx] = c.name()
            self._refresh_pc_btns()
            self._sync_preset_config()
            # Sync colour panel to the picked colour so HSV sliders are live
            self._cpanel.set_colour(c)
            self._preview_t0 = _time.monotonic()
            self._schedule_auto_apply()

    def _refresh_pc_btns(self) -> None:
        for i, btn in enumerate(self._pc_btns):
            btn.setStyleSheet(
                f'background-color:{self._pc_colours[i]};border:1px solid #444;border-radius:3px;'
            )

    def _refresh_pc_visibility(self) -> None:
        preset = self._preset_name.currentData()
        n = _PRESET_COLOUR_N.get(preset, 1)
        for i, btn in enumerate(self._pc_btns):
            btn.setVisible(i < n)
        show_dir = preset in ('wave', 'rainbow_wave')
        try:
            self._preset_fl.setRowVisible(self._dir_combo, show_dir)
        except Exception:
            self._dir_combo.setVisible(show_dir)

    # ── animation controls ────────────────────────────────────────────────────

    def _on_anim_duration(self, val: float) -> None:
        anim = self._ensure_anim()
        anim.duration = val
        self._timeline.set_animation(anim.duration, anim.keyframes)

    def _on_anim_loop(self, checked: bool) -> None:
        self._ensure_anim().loop = checked

    def _on_kf_selected(self, idx: int) -> None:
        self._anim_kf_sel = idx
        self._update_anim_controls()
        if idx >= 0:
            self._refresh_kbd_for_kf(idx)

    def _on_kf_add_btn(self) -> None:
        t = self._timeline._playhead
        self._on_kf_add(round(t, 3))

    def _on_kf_add(self, t: float) -> None:
        anim = self._ensure_anim()
        # Skip if very close to an existing keyframe
        for kf in anim.keyframes:
            if abs(kf.time - t) < 0.02:
                return
        anim.keyframes.append(Keyframe(time=t))
        anim.keyframes.sort(key=lambda k: k.time)
        new_idx = next(i for i, kf in enumerate(anim.keyframes)
                       if abs(kf.time - t) < 0.02)
        self._timeline.set_animation(anim.duration, anim.keyframes)
        self._timeline.set_selected(new_idx)
        self._on_kf_selected(new_idx)

    def _on_kf_del_btn(self) -> None:
        if self._anim_kf_sel > 0:
            self._on_kf_del(self._anim_kf_sel)

    def _on_kf_del(self, idx: int) -> None:
        anim = self._config.animation
        if not anim or not anim.keyframes or idx == 0:
            return
        del anim.keyframes[idx]
        new_sel = min(idx, len(anim.keyframes) - 1)
        self._timeline.set_animation(anim.duration, anim.keyframes)
        self._timeline.set_selected(new_sel)
        self._on_kf_selected(new_sel)

    def _on_kf_moved(self, idx: int, new_time: float) -> None:
        anim = self._config.animation
        if not anim:
            return
        anim.keyframes.sort(key=lambda k: k.time)
        new_idx = next(
            (i for i, kf in enumerate(anim.keyframes) if abs(kf.time - new_time) < 0.01),
            idx,
        )
        self._anim_kf_sel = new_idx
        self._timeline.set_selected(new_idx)

    def _on_kf_transition(self) -> None:
        if self._anim_kf_sel < 0:
            return
        anim = self._config.animation
        if not anim or self._anim_kf_sel >= len(anim.keyframes):
            return
        anim.keyframes[self._anim_kf_sel].transition = self._trans_combo.currentData()
        self._timeline.update()

    def _on_kf_trans_ext(self, idx: int, trans: str) -> None:
        if idx == self._anim_kf_sel:
            self._trans_combo.blockSignals(True)
            tidx = self._trans_combo.findData(trans)
            if tidx >= 0:
                self._trans_combo.setCurrentIndex(tidx)
            self._trans_combo.blockSignals(False)

    def _ensure_anim(self) -> AnimationConfig:
        if self._config.animation is None:
            self._config.animation = AnimationConfig(
                duration=self._dur_spin.value(),
                keyframes=[Keyframe(time=0.0)],
            )
        return self._config.animation

    def _update_anim_controls(self) -> None:
        idx = self._anim_kf_sel
        has = idx >= 0
        self._btn_del_kf.setEnabled(has and idx > 0)
        self._trans_combo.setEnabled(has)
        if has and self._config.animation and idx < len(self._config.animation.keyframes):
            trans = self._config.animation.keyframes[idx].transition
            self._trans_combo.blockSignals(True)
            tidx = self._trans_combo.findData(trans)
            if tidx >= 0:
                self._trans_combo.setCurrentIndex(tidx)
            self._trans_combo.blockSignals(False)

    # ── preset preview (runs in editor only, no hardware) ────────────────────

    def _start_preset_preview(self) -> None:
        if not hasattr(self, '_preview_timer'):
            self._preview_timer = QTimer(self)
            self._preview_timer.timeout.connect(self._tick_preset)
        self._preview_t0 = _time.monotonic()
        self._preview_timer.start(16)   # ~60 fps target

    def _stop_preset_preview(self) -> None:
        if hasattr(self, '_preview_timer'):
            self._preview_timer.stop()

    def _tick_preset(self) -> None:
        pc = self._config.preset
        if not pc:
            return
        t      = _time.monotonic() - self._preview_t0
        speed  = max(pc.speed, 0.01)
        colours: dict[str, QColor] = {}

        if pc.name == 'breathing':
            base = QColor(pc.colours[0] if pc.colours else self._config.base_colour)
            phase = (t * speed * 0.25) % 1.0   # match engine: period = 4/speed seconds
            br = (math.sin(phase * math.pi * 2 - math.pi / 2) + 1) / 2
            for key in _ALL_KEYS:
                colours[key] = QColor(
                    int(base.red() * br), int(base.green() * br), int(base.blue() * br)
                )

        elif pc.name == 'wave':
            base    = QColor(pc.colours[0] if pc.colours else self._config.base_colour)
            use_y   = pc.direction in ('top_bottom', 'bottom_top')
            pos     = {kr.name: kr.y for kr in _LAYOUT} if use_y else {kr.name: kr.x for kr in _LAYOUT}
            mn, mx  = min(pos.values()), max(pos.values())
            span    = max(mx - mn, 0.001)
            wave_t  = (t * speed * 0.25) % 1.0   # match engine coefficient
            if pc.direction in ('right_left', 'bottom_top'):
                wave_t = 1.0 - wave_t
            for key in _ALL_KEYS:
                key_pos = (pos.get(key, mn) - mn) / span
                dist = min(abs(key_pos - wave_t), 1.0 - abs(key_pos - wave_t))
                br = max(0.0, 1.0 - dist * 6)
                colours[key] = QColor(
                    int(base.red() * br), int(base.green() * br), int(base.blue() * br)
                )

        elif pc.name == 'rainbow_wave':
            use_y  = pc.direction in ('top_bottom', 'bottom_top')
            pos    = {kr.name: kr.y for kr in _LAYOUT} if use_y else {kr.name: kr.x for kr in _LAYOUT}
            mn, mx = min(pos.values()), max(pos.values())
            span   = max(mx - mn, 0.001)
            wave_t = (t * speed * 0.1) % 1.0   # match engine coefficient
            rev    = pc.direction in ('right_left', 'bottom_top')
            for key in _ALL_KEYS:
                key_pos = (pos.get(key, mn) - mn) / span
                hue = ((1.0 - key_pos if rev else key_pos) - wave_t) % 1.0
                r, g, b = colorsys.hsv_to_rgb(hue, 1.0, 1.0)
                colours[key] = QColor(int(r * 255), int(g * 255), int(b * 255))

        elif pc.name == 'colour_cycle':
            clrs = pc.colours if pc.colours else [self._config.base_colour]
            n    = len(clrs)
            phase = (t * speed) % n
            i0, i1 = int(phase) % n, (int(phase) + 1) % n
            frac = phase - int(phase)
            c0, c1 = QColor(clrs[i0]), QColor(clrs[i1])
            col = QColor(
                int(c0.red()   + (c1.red()   - c0.red())   * frac),
                int(c0.green() + (c1.green() - c0.green()) * frac),
                int(c0.blue()  + (c1.blue()  - c0.blue())  * frac),
            )
            for key in _ALL_KEYS:
                colours[key] = col

        if colours:
            self._kbd.set_colours(colours)

    # ── animation playhead scrub ──────────────────────────────────────────────

    def _on_playhead_scrub(self, t: float) -> None:
        if self._config.mode != 'animation':
            return
        anim = self._config.animation
        if not anim or not anim.keyframes:
            return
        # Find the last keyframe at or before t
        kfs = anim.keyframes  # already sorted
        kf_idx = 0
        for i, kf in enumerate(kfs):
            if kf.time <= t + 1e-9:
                kf_idx = i
        self._refresh_kbd_for_kf(kf_idx)

    # ── auto-apply (preset live preview on hardware) ──────────────────────────

    def _schedule_auto_apply(self) -> None:
        """Debounce-restart the auto-apply timer; fires 400 ms after last change."""
        self._apply_timer.start()

    def _do_auto_apply(self) -> None:
        """Push current preset config to hardware; no-op if no longer in preset mode."""
        if self._config.mode != 'preset':
            return
        self._sync_preset_config()
        self._profile.lighting = copy.deepcopy(self._config)
        cfg.save_profile(self._profile)
        from kyxen_keys import daemon
        daemon.daemon_reload()

    # ── save / revert ─────────────────────────────────────────────────────────

    def _save(self) -> None:
        if self._config.mode == 'preset':
            self._sync_preset_config()
        if self._config.mode == 'animation':
            anim = self._config.animation
            if anim and not anim.keyframes:
                anim.keyframes = [Keyframe(time=0.0)]
        self._profile.lighting = copy.deepcopy(self._config)
        cfg.save_profile(self._profile)
        from kyxen_keys import daemon
        daemon.daemon_reload()

    def _revert(self) -> None:
        self._apply_timer.stop()
        self._config      = copy.deepcopy(self._profile.lighting)
        self._anim_kf_sel = -1
        self._load_config()

    def closeEvent(self, event) -> None:
        self._apply_timer.stop()
        self._stop_preset_preview()
        self.closed.emit()
        super().closeEvent(event)
