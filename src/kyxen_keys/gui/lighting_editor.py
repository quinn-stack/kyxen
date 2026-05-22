"""Lighting editor — separate window for per-key RGB, presets, and animation."""
from __future__ import annotations
import colorsys
import copy
import math
import time as _time

from PySide6.QtCore    import Qt, QTimer, Signal
from PySide6.QtGui     import QColor
from PySide6.QtWidgets import (
    QCheckBox, QColorDialog, QComboBox, QDialog, QDialogButtonBox,
    QDoubleSpinBox, QFormLayout, QFrame, QGroupBox, QHBoxLayout,
    QInputDialog, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QMainWindow, QMessageBox, QPushButton, QScrollArea, QSlider,
    QTabBar, QVBoxLayout, QWidget,
)

from kyxen_keys import config as cfg
from kyxen_keys.lighting_config import AnimationConfig, LightingConfig, PresetConfig, Slide
from kyxen_keys.gui.lighting_keyboard_widget import (
    LightingKeyboardWidget, _LAYOUT, _PX_RECTS,
)
from kyxen_keys.gui.filmstrip_widget import FilmstripWidget

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

_TRANSITIONS = [
    ('Cut',     'cut'),
    ('Fade',    'fade'),
    ('Ease',    'ease'),
    ('HSV',     'hsv'),
    ('Wipe →',  'wipe_left'),
    ('Wipe ←',  'wipe_right'),
    ('Wipe ↓',  'wipe_top'),
    ('Wipe ↑',  'wipe_bottom'),
    ('Blink',   'blink'),
]

_ANIM_DIR = cfg.CONFIG_DIR / 'animations'

# Common colour palette — shown as static swatches in the colour panel.
# Each inner list is one row of 8 swatches.
_COMMON_COLOURS: list[list[str]] = [
    # Spectrum
    ['#ff0000', '#ff6600', '#ffcc00', '#00ff00', '#00ffcc', '#0066ff', '#cc00ff', '#ff00aa'],
    # Softer / useful LED tones
    ['#ff4444', '#ff9933', '#ffff00', '#44ff44', '#44ffff', '#4488ff', '#aa44ff', '#ff44cc'],
    # Whites, greys, black
    ['#ffffff', '#cccccc', '#888888', '#444444', '#222222', '#000000', '#ff8800', '#00cc44'],
]


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

        layout.addWidget(QLabel('Common:'))
        common_grid = QWidget()
        common_layout = QVBoxLayout(common_grid)
        common_layout.setContentsMargins(0, 0, 0, 0)
        common_layout.setSpacing(2)
        for row_colours in _COMMON_COLOURS:
            row_w = QWidget()
            row_l = QHBoxLayout(row_w)
            row_l.setContentsMargins(0, 0, 0, 0)
            row_l.setSpacing(2)
            for hex_c in row_colours:
                col = QColor(hex_c)
                btn = QPushButton()
                btn.setFixedSize(20, 20)
                btn.setToolTip(hex_c)
                btn.setStyleSheet(f'background-color:{hex_c};border:1px solid #555;')
                btn.clicked.connect(lambda _, x=col: self.set_colour(x, emit=True))
                row_l.addWidget(btn)
            row_l.addStretch()
            common_layout.addWidget(row_w)
        layout.addWidget(common_grid)

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
        if any(x.name() == name for x in self._recent):
            return   # already present — don't reorder
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
        self._slide_sel   = -1

        self._apply_timer = QTimer(self)
        self._apply_timer.setSingleShot(True)
        self._apply_timer.setInterval(400)
        self._apply_timer.timeout.connect(self._do_auto_apply)

        self._preview_timer:          QTimer | None          = None
        self._preview_t0              = 0.0
        self._pre_preview_lighting:   LightingConfig | None = None

        self.setWindowTitle(f'Lighting — {profile.display_name}')
        self.setMinimumSize(1100, 720)
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
            ('fill_sel',   'Fill',       False, 'Fill selected keys (or all) with current colour'),
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

        # ── Top controls row ──────────────────────────────────────────────────
        top = QHBoxLayout()
        top.setSpacing(8)

        self._loop_chk = QCheckBox('Loop')
        self._loop_chk.setChecked(True)
        self._loop_chk.toggled.connect(self._on_anim_loop)
        top.addWidget(self._loop_chk)

        top.addStretch()

        self._btn_preview = QPushButton('▶  Preview')
        self._btn_preview.setCheckable(True)
        self._btn_preview.setFixedWidth(100)
        self._btn_preview.toggled.connect(self._on_preview_toggled)
        top.addWidget(self._btn_preview)

        sep = QFrame(); sep.setFrameShape(QFrame.Shape.VLine); sep.setFrameShadow(QFrame.Shadow.Sunken)
        top.addWidget(sep)

        self._btn_anim_save = QPushButton('Save to Library…')
        self._btn_anim_save.clicked.connect(self._on_anim_save_library)
        top.addWidget(self._btn_anim_save)

        self._btn_anim_load = QPushButton('Load from Library…')
        self._btn_anim_load.clicked.connect(self._on_anim_load_library)
        top.addWidget(self._btn_anim_load)

        layout.addLayout(top)

        # ── Slide property controls ───────────────────────────────────────────
        slide_row = QHBoxLayout()
        slide_row.setSpacing(6)

        self._btn_add_slide = QPushButton('+ Add Slide')
        self._btn_add_slide.setFixedWidth(100)
        self._btn_add_slide.clicked.connect(self._on_add_slide_btn)
        slide_row.addWidget(self._btn_add_slide)

        self._btn_blank_slide = QPushButton('+ Blank')
        self._btn_blank_slide.setFixedWidth(70)
        self._btn_blank_slide.setToolTip('Add a new blank slide (no inherited colours)')
        self._btn_blank_slide.clicked.connect(self._on_blank_slide_btn)
        slide_row.addWidget(self._btn_blank_slide)

        self._btn_del_slide = QPushButton('Delete')
        self._btn_del_slide.setFixedWidth(70)
        self._btn_del_slide.setEnabled(False)
        self._btn_del_slide.clicked.connect(self._on_del_slide_btn)
        slide_row.addWidget(self._btn_del_slide)

        slide_row.addSpacing(12)

        sep2 = QFrame(); sep2.setFrameShape(QFrame.Shape.VLine); sep2.setFrameShadow(QFrame.Shadow.Sunken)
        slide_row.addWidget(sep2)

        slide_row.addWidget(QLabel('Hold:'))
        self._slide_hold = QDoubleSpinBox()
        self._slide_hold.setRange(0.05, 60.0)
        self._slide_hold.setSingleStep(0.1)
        self._slide_hold.setSuffix(' s')
        self._slide_hold.setValue(0.5)
        self._slide_hold.setEnabled(False)
        self._slide_hold.valueChanged.connect(self._on_slide_hold)
        slide_row.addWidget(self._slide_hold)

        self._btn_hold_all = QPushButton('→ All')
        self._btn_hold_all.setFixedWidth(46)
        self._btn_hold_all.setToolTip('Apply this hold duration to every slide')
        self._btn_hold_all.setEnabled(False)
        self._btn_hold_all.clicked.connect(self._on_hold_all)
        slide_row.addWidget(self._btn_hold_all)

        slide_row.addSpacing(8)

        slide_row.addWidget(QLabel('Transition:'))
        self._slide_trans = QComboBox()
        for label, val in _TRANSITIONS:
            self._slide_trans.addItem(label, val)
        self._slide_trans.setEnabled(False)
        self._slide_trans.currentIndexChanged.connect(self._on_slide_trans)
        slide_row.addWidget(self._slide_trans)

        self._btn_trans_all = QPushButton('→ All')
        self._btn_trans_all.setFixedWidth(46)
        self._btn_trans_all.setToolTip('Apply this transition type to every slide')
        self._btn_trans_all.setEnabled(False)
        self._btn_trans_all.clicked.connect(self._on_trans_all)
        slide_row.addWidget(self._btn_trans_all)

        slide_row.addSpacing(4)

        self._trans_dur_lbl = QLabel('Duration:')
        slide_row.addWidget(self._trans_dur_lbl)
        self._slide_trans_dur = QDoubleSpinBox()
        self._slide_trans_dur.setRange(0.05, 10.0)
        self._slide_trans_dur.setSingleStep(0.1)
        self._slide_trans_dur.setSuffix(' s')
        self._slide_trans_dur.setValue(0.5)
        self._slide_trans_dur.setEnabled(False)
        self._slide_trans_dur.valueChanged.connect(self._on_slide_trans_dur)
        slide_row.addWidget(self._slide_trans_dur)

        self._btn_trans_dur_all = QPushButton('→ All')
        self._btn_trans_dur_all.setFixedWidth(46)
        self._btn_trans_dur_all.setToolTip('Apply this transition duration to every slide')
        self._btn_trans_dur_all.setEnabled(False)
        self._btn_trans_dur_all.clicked.connect(self._on_trans_dur_all)
        slide_row.addWidget(self._btn_trans_dur_all)

        slide_row.addStretch()
        layout.addLayout(slide_row)

        # ── Filmstrip ─────────────────────────────────────────────────────────
        self._filmstrip = FilmstripWidget()
        self._filmstrip.slide_selected.connect(self._on_slide_selected)
        self._filmstrip.slide_add_after.connect(self._on_slide_add_after)
        self._filmstrip.slide_delete.connect(self._on_slide_delete)

        fs_scroll = QScrollArea()
        fs_scroll.setWidget(self._filmstrip)
        fs_scroll.setWidgetResizable(False)
        fs_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        fs_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        fs_scroll.setFixedHeight(self._filmstrip.height() + 20)
        fs_scroll.setFrameShape(QFrame.Shape.NoFrame)
        layout.addWidget(fs_scroll)

        return panel

    # ── config load ───────────────────────────────────────────────────────────

    def _load_config(self) -> None:
        mode_idx = {'static': 0, 'preset': 1, 'animation': 2}.get(self._config.mode, 0)

        # Preset panel
        pc = self._config.preset or PresetConfig()
        for widget, val in (
            (self._preset_name, pc.name),
            (self._dir_combo,   pc.direction),
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
        anim = self._ensure_anim()
        self._loop_chk.setChecked(anim.loop)
        slides = anim.slides
        self._slide_sel = 0 if slides else -1
        self._refresh_filmstrip()
        self._update_slide_controls()
        if self._slide_sel >= 0:
            self._refresh_kbd_for_slide(self._slide_sel)

        # Mode tab
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

    def _refresh_kbd_for_slide(self, idx: int) -> None:
        slides = self._get_slides()
        if not slides or idx < 0 or idx >= len(slides):
            self._refresh_kbd()
            return
        slide = slides[idx]
        base  = QColor(self._config.base_colour)
        colours:   dict[str, QColor] = {}
        inherited: set[str] = set()
        for key in _ALL_KEYS:
            if key in slide.key_colours:
                colours[key] = QColor(slide.key_colours[key])
            else:
                colours[key] = base
                inherited.add(key)
        self._kbd.set_colours(colours, inherited)

    def _refresh_filmstrip(self) -> None:
        slides = self._get_slides()
        self._filmstrip.set_slides(
            [s.key_colours for s in slides],
            self._config.base_colour,
            self._slide_sel,
        )

    def _update_slide_controls(self) -> None:
        slides = self._get_slides()
        has    = self._slide_sel >= 0 and self._slide_sel < len(slides)

        self._btn_del_slide.setEnabled(has and len(slides) > 1)
        any_slides = len(slides) > 0
        self._slide_hold.setEnabled(has)
        self._btn_hold_all.setEnabled(any_slides)
        self._btn_trans_all.setEnabled(any_slides)
        self._btn_trans_dur_all.setEnabled(any_slides)
        self._slide_trans.setEnabled(has)
        self._slide_trans_dur.setEnabled(has)

        if not has:
            return

        slide = slides[self._slide_sel]

        self._slide_hold.blockSignals(True)
        self._slide_hold.setValue(slide.hold_duration)
        self._slide_hold.blockSignals(False)

        self._slide_trans.blockSignals(True)
        tidx = self._slide_trans.findData(slide.transition)
        if tidx >= 0:
            self._slide_trans.setCurrentIndex(tidx)
        self._slide_trans.blockSignals(False)

        self._slide_trans_dur.blockSignals(True)
        self._slide_trans_dur.setValue(slide.transition_duration)
        self._slide_trans_dur.blockSignals(False)

        self._trans_dur_lbl.setVisible(slide.transition != 'cut')
        self._slide_trans_dur.setVisible(slide.transition != 'cut')

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

        if idx == 2:
            self._stop_animation_preview()
            if self._slide_sel >= 0:
                self._refresh_kbd_for_slide(self._slide_sel)
            else:
                self._refresh_kbd()
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
        in_anim = (self._config.mode == 'animation' and self._slide_sel >= 0
                   and self._config.animation)
        if name == 'fill_sel':
            c = self._cpanel.colour()
            sel = list(self._kbd.selection) if self._kbd.selection else list(_ALL_KEYS)
            if in_anim:
                slide = self._config.animation.slides[self._slide_sel]
                for key in sel:
                    slide.key_colours[key] = c.name()
                self._refresh_kbd_for_slide(self._slide_sel)
                self._refresh_filmstrip()
            else:
                for key in sel:
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
            slide = self._config.animation.slides[self._slide_sel]
            slide.key_colours.update(result)
            self._refresh_kbd_for_slide(self._slide_sel)
            self._refresh_filmstrip()
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
        # In select mode only: sync colour panel to a single selected key.
        # Brush mode must NOT do this — selection_changed fires before key_entered,
        # so updating the panel here would overwrite the brush colour before painting.
        if self._tool == 'select' and len(keys) == 1:
            self._pick_colour_from_key(keys[0])

    def _pick_colour_from_key(self, key: str) -> None:
        if self._config.mode == 'animation' and self._slide_sel >= 0 and self._config.animation:
            slide = self._config.animation.slides[self._slide_sel]
            hex_c = slide.key_colours.get(key, self._config.base_colour)
        else:
            hex_c = self._config.key_colours.get(key, self._config.base_colour)
        self._cpanel.set_colour(QColor(hex_c))

    def _on_key_brush(self, key: str) -> None:
        c = self._cpanel.colour()
        if self._config.mode == 'animation' and self._slide_sel >= 0 and self._config.animation:
            slide = self._config.animation.slides[self._slide_sel]
            slide.key_colours[key] = c.name()
            self._kbd.set_key_colour(key, c, is_inherited=False)
            self._refresh_filmstrip()
        else:
            self._config.key_colours[key] = c.name()
            self._kbd.set_key_colour(key, c, is_inherited=False)

    def _on_colour(self, colour: QColor) -> None:
        """Colour panel changed — auto-paint selected keys (select tool) or update base colour."""
        if self._config.mode == 'preset':
            self._pc_colours[0] = colour.name()
            self._refresh_pc_btns()
            self._sync_preset_config()
            self._preview_t0 = _time.monotonic()
            self._schedule_auto_apply()
            return

        # Brush mode: panel is just the brush colour source — don't auto-paint.
        if self._tool == 'brush':
            return

        sel = self._kbd.selection

        if self._config.mode == 'animation' and self._slide_sel >= 0 and self._config.animation:
            slide = self._config.animation.slides[self._slide_sel]
            if sel:
                for key in sel:
                    slide.key_colours[key] = colour.name()
                self._refresh_kbd_for_slide(self._slide_sel)
                self._refresh_filmstrip()
            else:
                self._config.base_colour = colour.name()
                self._refresh_kbd_for_slide(self._slide_sel)
                self._refresh_filmstrip()
        elif self._config.mode == 'static':
            if sel:
                for key in sel:
                    self._config.key_colours[key] = colour.name()
                self._refresh_kbd()
            else:
                self._config.base_colour = colour.name()
                self._refresh_kbd()

    # ── preset controls ───────────────────────────────────────────────────────

    def _on_preset_param(self) -> None:
        self._sync_preset_config()
        self._refresh_pc_visibility()
        self._preview_t0 = _time.monotonic()
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

    # ── animation — slide management ──────────────────────────────────────────

    def _get_slides(self) -> list[Slide]:
        anim = self._ensure_anim()
        return anim.slides

    def _ensure_anim(self) -> AnimationConfig:
        if self._config.animation is None:
            self._config.animation = AnimationConfig()
        return self._config.animation

    def _on_add_slide_btn(self) -> None:
        slides = self._get_slides()
        # Append after current selection (or at end if none)
        after = self._slide_sel if self._slide_sel >= 0 else len(slides) - 1
        self._on_slide_add_after(after)

    def _on_blank_slide_btn(self) -> None:
        """Insert a completely blank slide after the current selection."""
        slides    = self._get_slides()
        insert_at = (self._slide_sel + 1) if self._slide_sel >= 0 else len(slides)
        slides.insert(insert_at, Slide())
        self._slide_sel = insert_at
        self._refresh_filmstrip()
        self._update_slide_controls()
        self._refresh_kbd_for_slide(self._slide_sel)

    def _on_hold_all(self) -> None:
        val = self._slide_hold.value()
        for slide in self._get_slides():
            slide.hold_duration = val

    def _on_trans_all(self) -> None:
        trans = self._slide_trans.currentData()
        for slide in self._get_slides():
            slide.transition = trans
        self._update_slide_controls()   # refresh visibility of duration widgets

    def _on_trans_dur_all(self) -> None:
        dur = self._slide_trans_dur.value()
        for slide in self._get_slides():
            slide.transition_duration = dur

    def _on_del_slide_btn(self) -> None:
        self._on_slide_delete(self._slide_sel)

    def _on_slide_selected(self, idx: int) -> None:
        self._stop_animation_preview()
        self._slide_sel = idx
        self._filmstrip.set_selected(idx)
        self._update_slide_controls()
        self._refresh_kbd_for_slide(idx)

    def _on_slide_add_after(self, after_idx: int) -> None:
        """Insert a new slide after after_idx (-1 = prepend)."""
        slides = self._get_slides()
        # Inherit colours from the slide at after_idx (if any)
        if after_idx >= 0 and after_idx < len(slides):
            prev = slides[after_idx]
            new_slide = Slide(
                key_colours=dict(prev.key_colours),
                hold_duration=prev.hold_duration,
                transition=prev.transition,
                transition_duration=prev.transition_duration,
            )
        else:
            # First slide or prepend: blank slate
            new_slide = Slide()

        insert_at = after_idx + 1
        slides.insert(insert_at, new_slide)
        self._slide_sel = insert_at
        self._refresh_filmstrip()
        self._update_slide_controls()
        self._refresh_kbd_for_slide(self._slide_sel)

    def _on_slide_delete(self, idx: int) -> None:
        slides = self._get_slides()
        if len(slides) <= 1:
            return
        del slides[idx]
        self._slide_sel = min(idx, len(slides) - 1)
        self._refresh_filmstrip()
        self._update_slide_controls()
        self._refresh_kbd_for_slide(self._slide_sel)

    def _on_anim_loop(self, checked: bool) -> None:
        self._ensure_anim().loop = checked

    def _on_slide_hold(self, val: float) -> None:
        slides = self._get_slides()
        if 0 <= self._slide_sel < len(slides):
            slides[self._slide_sel].hold_duration = val

    def _on_slide_trans(self) -> None:
        slides = self._get_slides()
        if 0 <= self._slide_sel < len(slides):
            slides[self._slide_sel].transition = self._slide_trans.currentData()
            is_cut = (self._slide_trans.currentData() == 'cut')
            self._trans_dur_lbl.setVisible(not is_cut)
            self._slide_trans_dur.setVisible(not is_cut)

    def _on_slide_trans_dur(self, val: float) -> None:
        slides = self._get_slides()
        if 0 <= self._slide_sel < len(slides):
            slides[self._slide_sel].transition_duration = val

    # ── animation preview ─────────────────────────────────────────────────────

    def _on_preview_toggled(self, checked: bool) -> None:
        if checked:
            slides = self._get_slides()
            if not slides:
                self._btn_preview.setChecked(False)
                return
            self._btn_preview.setText('■  Stop')
            self._start_animation_preview()
        else:
            self._btn_preview.setText('▶  Preview')
            self._stop_animation_preview()

    def _start_animation_preview(self) -> None:
        # Push animation config to hardware for live keyboard preview
        self._pre_preview_lighting = copy.deepcopy(self._profile.lighting)
        self._profile.lighting = copy.deepcopy(self._config)
        cfg.save_profile(self._profile)
        try:
            from kyxen_keys import daemon
            daemon.daemon_reload()
        except Exception:
            pass

        if self._preview_timer is None:
            self._preview_timer = QTimer(self)
            self._preview_timer.timeout.connect(self._tick_anim_preview)
        self._preview_t0 = _time.monotonic()
        self._preview_timer.start(50)   # ~20fps matches hardware engine

    def _stop_animation_preview(self) -> None:
        if self._preview_timer is not None:
            self._preview_timer.stop()
        if self._btn_preview.isChecked():
            self._btn_preview.blockSignals(True)
            self._btn_preview.setChecked(False)
            self._btn_preview.setText('▶  Preview')
            self._btn_preview.blockSignals(False)

        # Restore the pre-preview hardware state
        if self._pre_preview_lighting is not None:
            self._profile.lighting = self._pre_preview_lighting
            self._pre_preview_lighting = None
            cfg.save_profile(self._profile)
            try:
                from kyxen_keys import daemon
                daemon.daemon_reload()
            except Exception:
                pass

        # Restore keyboard widget to selected slide
        if self._slide_sel >= 0:
            self._refresh_kbd_for_slide(self._slide_sel)

    def _tick_anim_preview(self) -> None:
        from kyxen_keys.lighting_engine import _build_animation

        anim = self._config.animation
        if not anim or not anim.slides:
            self._stop_animation_preview()
            return

        t     = _time.monotonic() - self._preview_t0
        frame = _build_animation(self._config, t)
        colours = {k: QColor(*v) for k, v in frame.items() if k in _PX_RECTS}
        self._kbd.set_colours(colours)

    # ── animation library ─────────────────────────────────────────────────────

    def _on_anim_save_library(self) -> None:
        import tomli_w
        anim = self._ensure_anim()
        if not anim.slides:
            QMessageBox.warning(self, 'Nothing to save', 'Add at least one slide first.')
            return
        name, ok = QInputDialog.getText(self, 'Save Animation', 'Animation name:')
        if not ok or not name.strip():
            return
        name = name.strip()
        _ANIM_DIR.mkdir(parents=True, exist_ok=True)
        path = _ANIM_DIR / f'{name}.toml'
        with open(path, 'wb') as f:
            tomli_w.dump(anim.to_dict(), f)

    def _on_anim_load_library(self) -> None:
        import tomllib
        _ANIM_DIR.mkdir(parents=True, exist_ok=True)
        files = sorted(_ANIM_DIR.glob('*.toml'))
        if not files:
            QMessageBox.information(self, 'Library empty',
                                    'No saved animations found.\nSave one first.')
            return
        names = [f.stem for f in files]
        dlg   = _LibraryDialog(names, self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        chosen = dlg.selected_name()
        if not chosen:
            return
        path = _ANIM_DIR / f'{chosen}.toml'
        with open(path, 'rb') as f:
            data = tomllib.load(f)
        self._config.animation = AnimationConfig.from_dict(data)
        self._config.mode = 'animation'
        self._slide_sel = 0 if self._config.animation.slides else -1
        self._loop_chk.setChecked(self._config.animation.loop)
        self._refresh_filmstrip()
        self._update_slide_controls()
        if self._slide_sel >= 0:
            self._refresh_kbd_for_slide(self._slide_sel)

    # ── preset preview (runs in editor only, no hardware) ────────────────────

    def _start_preset_preview(self) -> None:
        if not hasattr(self, '_preset_timer'):
            self._preset_timer = QTimer(self)
            self._preset_timer.timeout.connect(self._tick_preset)
        self._preview_t0 = _time.monotonic()
        self._preset_timer.start(16)

    def _stop_preset_preview(self) -> None:
        if hasattr(self, '_preset_timer'):
            self._preset_timer.stop()

    def _tick_preset(self) -> None:
        pc = self._config.preset
        if not pc:
            return
        t     = _time.monotonic() - self._preview_t0
        speed = max(pc.speed, 0.01)
        colours: dict[str, QColor] = {}

        if pc.name == 'breathing':
            base  = QColor(pc.colours[0] if pc.colours else self._config.base_colour)
            br    = (math.sin(t * speed * 0.25 * math.pi * 2 - math.pi / 2) + 1) / 2
            for key in _ALL_KEYS:
                colours[key] = QColor(
                    int(base.red() * br), int(base.green() * br), int(base.blue() * br)
                )

        elif pc.name == 'wave':
            base   = QColor(pc.colours[0] if pc.colours else self._config.base_colour)
            use_y  = pc.direction in ('top_bottom', 'bottom_top')
            pos    = {kr.name: kr.y for kr in _LAYOUT} if use_y else {kr.name: kr.x for kr in _LAYOUT}
            mn, mx = min(pos.values()), max(pos.values())
            span   = max(mx - mn, 0.001)
            wt     = (t * speed * 0.25) % 1.0
            if pc.direction in ('right_left', 'bottom_top'):
                wt = 1.0 - wt
            for key in _ALL_KEYS:
                kp   = (pos.get(key, mn) - mn) / span
                dist = min(abs(kp - wt), 1.0 - abs(kp - wt))
                br   = max(0.0, 1.0 - dist * 6)
                colours[key] = QColor(
                    int(base.red() * br), int(base.green() * br), int(base.blue() * br)
                )

        elif pc.name == 'rainbow_wave':
            use_y  = pc.direction in ('top_bottom', 'bottom_top')
            pos    = {kr.name: kr.y for kr in _LAYOUT} if use_y else {kr.name: kr.x for kr in _LAYOUT}
            mn, mx = min(pos.values()), max(pos.values())
            span   = max(mx - mn, 0.001)
            wt     = (t * speed * 0.1) % 1.0
            rev    = pc.direction in ('right_left', 'bottom_top')
            for key in _ALL_KEYS:
                kp  = (pos.get(key, mn) - mn) / span
                hue = ((1.0 - kp if rev else kp) - wt) % 1.0
                r, g, b = colorsys.hsv_to_rgb(hue, 1.0, 1.0)
                colours[key] = QColor(int(r * 255), int(g * 255), int(b * 255))

        elif pc.name == 'colour_cycle':
            clrs  = pc.colours if pc.colours else [self._config.base_colour]
            n     = len(clrs)
            phase = (t * speed) % n
            i0, i1 = int(phase) % n, (int(phase) + 1) % n
            frac  = phase - int(phase)
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

    # ── auto-apply (preset live preview on hardware) ──────────────────────────

    def _schedule_auto_apply(self) -> None:
        self._apply_timer.start()

    def _do_auto_apply(self) -> None:
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
            if anim and not anim.slides:
                anim.slides = [Slide()]
        self._profile.lighting = copy.deepcopy(self._config)
        cfg.save_profile(self._profile)
        from kyxen_keys import daemon
        daemon.daemon_reload()

    def _revert(self) -> None:
        self._apply_timer.stop()
        self._stop_animation_preview()
        self._stop_preset_preview()
        self._config      = copy.deepcopy(self._profile.lighting)
        self._slide_sel   = -1
        self._load_config()

    def closeEvent(self, event) -> None:
        self._apply_timer.stop()
        self._stop_preset_preview()
        self._stop_animation_preview()
        self.closed.emit()
        super().closeEvent(event)


# ── Library selection dialog ──────────────────────────────────────────────────

class _LibraryDialog(QDialog):
    def __init__(self, names: list[str], parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle('Load Animation')
        self.setMinimumWidth(300)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel('Choose a saved animation:'))
        self._list = QListWidget()
        for n in names:
            self._list.addItem(QListWidgetItem(n))
        if names:
            self._list.setCurrentRow(0)
        self._list.itemDoubleClicked.connect(self.accept)
        layout.addWidget(self._list)
        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    def selected_name(self) -> str | None:
        item = self._list.currentItem()
        return item.text() if item else None
