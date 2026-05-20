"""Kyxen — PySide6 GUI (system tray + editor window)."""
from __future__ import annotations
import sys
from pathlib import Path

from PySide6.QtCore    import Qt, QTimer, Signal, QObject, QEvent
from PySide6.QtGui     import QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QApplication, QColorDialog, QDialog, QDialogButtonBox,
    QFormLayout, QHBoxLayout, QInputDialog, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QMainWindow, QMenu, QMessageBox,
    QPushButton, QRadioButton, QSizePolicy, QSplitter, QSystemTrayIcon,
    QTabWidget, QTextEdit, QVBoxLayout, QWidget, QComboBox,
    QButtonGroup, QGroupBox, QFrame, QSpinBox,
)

from kyxen_keys import config as cfg
from kyxen_keys import daemon

# ── helpers ───────────────────────────────────────────────────────────────────

def make_colour_icon(hex_colour: str, size: int = 16) -> QIcon:
    px = QPixmap(size, size)
    px.fill(QColor(hex_colour))
    return QIcon(px)


def make_tray_icon(hex_colour: str) -> QIcon:
    px = QPixmap(22, 22)
    px.fill(Qt.transparent)
    p = QPainter(px)
    p.setBrush(QColor(hex_colour))
    p.setPen(Qt.NoPen)
    p.drawEllipse(2, 2, 18, 18)
    p.end()
    return QIcon(px)


# ── keyboard widget ───────────────────────────────────────────────────────────

_UNIT     = 28   # px per 1 key unit
_KH       = 22   # standard key height px
_KH_FN    = 18   # function-row key height px
_RGAP     =  3   # gap between rows px
_MARGIN   =  6   # outer margin px
_FN_EXTRA =  5   # extra gap below function row
_FN_ROWS  =  2   # number of rows at the top using _KH_FN height

# Qt key code → macro key name
_QT_TO_NAME: dict[int, str] = {
    int(Qt.Key_Control):    'ctrl',
    int(Qt.Key_Alt):        'alt',
    int(Qt.Key_Shift):      'shift',
    int(Qt.Key_Meta):       'super',
    int(Qt.Key_Return):     'enter',
    int(Qt.Key_Enter):      'enter',
    int(Qt.Key_Tab):        'tab',
    int(Qt.Key_Backspace):  'backspace',
    int(Qt.Key_Escape):     'escape',
    int(Qt.Key_Space):      'space',
    int(Qt.Key_CapsLock):   'caps_lock',
    int(Qt.Key_Up):         'up',
    int(Qt.Key_Down):       'down',
    int(Qt.Key_Left):       'left',
    int(Qt.Key_Right):      'right',
    int(Qt.Key_Home):       'home',
    int(Qt.Key_End):        'end',
    int(Qt.Key_PageUp):     'pageup',
    int(Qt.Key_PageDown):   'pagedown',
    int(Qt.Key_Insert):     'insert',
    int(Qt.Key_Delete):     'delete',
    int(Qt.Key_Menu):       'menu',
    **{int(getattr(Qt, f'Key_F{i}')): f'f{i}' for i in range(1, 25)},
    int(Qt.Key_Minus):        '-',
    int(Qt.Key_Equal):        '=',
    int(Qt.Key_BracketLeft):  '[',
    int(Qt.Key_BracketRight): ']',
    int(Qt.Key_Backslash):    '\\',
    int(Qt.Key_Semicolon):    ';',
    int(Qt.Key_Apostrophe):   "'",
    int(Qt.Key_Comma):        ',',
    int(Qt.Key_Period):       '.',
    int(Qt.Key_Slash):        '/',
    int(Qt.Key_QuoteLeft):    '`',
}
for _ch in 'abcdefghijklmnopqrstuvwxyz':
    _QT_TO_NAME[ord(_ch.upper())] = _ch
for _ch in '0123456789':
    _QT_TO_NAME[ord(_ch)] = _ch

# (display_label, key_name_or_None_for_gap, width_units)
# Rows with kh == _KH_FN use the shorter function-row height (see _build).
_KB_ROWS: list[list[tuple[str, str | None, float]]] = [
    # Function row
    [('Esc', 'escape', 1), ('', None, 0.5),
     ('F1', 'f1', 1), ('F2', 'f2', 1), ('F3', 'f3', 1), ('F4', 'f4', 1), ('', None, 0.5),
     ('F5', 'f5', 1), ('F6', 'f6', 1), ('F7', 'f7', 1), ('F8', 'f8', 1), ('', None, 0.5),
     ('F9', 'f9', 1), ('F10', 'f10', 1), ('F11', 'f11', 1), ('F12', 'f12', 1)],
    # Extended function row — F13–F20 (aligned under F5–F12)
    [('', None, 6),
     ('F13', 'f13', 1), ('F14', 'f14', 1), ('F15', 'f15', 1), ('F16', 'f16', 1), ('', None, 0.5),
     ('F17', 'f17', 1), ('F18', 'f18', 1), ('F19', 'f19', 1), ('F20', 'f20', 1)],
    # Number row
    [('`', '`', 1), ('1', '1', 1), ('2', '2', 1), ('3', '3', 1), ('4', '4', 1), ('5', '5', 1),
     ('6', '6', 1), ('7', '7', 1), ('8', '8', 1), ('9', '9', 1), ('0', '0', 1),
     ('-', '-', 1), ('=', '=', 1), ('Bsp', 'backspace', 2)],
    # QWERTY
    [('Tab', 'tab', 1.5), ('Q', 'q', 1), ('W', 'w', 1), ('E', 'e', 1), ('R', 'r', 1), ('T', 't', 1),
     ('Y', 'y', 1), ('U', 'u', 1), ('I', 'i', 1), ('O', 'o', 1), ('P', 'p', 1),
     ('[', '[', 1), (']', ']', 1), ('\\', '\\', 1.5)],
    # ASDF
    [('Caps', 'caps_lock', 1.75), ('A', 'a', 1), ('S', 's', 1), ('D', 'd', 1), ('F', 'f', 1),
     ('G', 'g', 1), ('H', 'h', 1), ('J', 'j', 1), ('K', 'k', 1), ('L', 'l', 1),
     (';', ';', 1), ("'", "'", 1), ('Ent', 'enter', 2.25)],
    # ZXCV
    [('Shift', 'shift', 2.25), ('Z', 'z', 1), ('X', 'x', 1), ('C', 'c', 1), ('V', 'v', 1),
     ('B', 'b', 1), ('N', 'n', 1), ('M', 'm', 1), (',', ',', 1), ('.', '.', 1), ('/', '/', 1),
     ('Shift', 'shift', 2.75)],
    # Bottom row
    [('Ctrl', 'ctrl', 1.25), ('⊞', 'super', 1.25), ('Alt', 'alt', 1.25),
     ('Space', 'space', 6.25),
     ('Alt', 'alt', 1.25), ('⊞', 'super', 1.25), ('≡', 'menu', 1.25), ('Ctrl', 'ctrl', 1.25)],
]

_ARROW_ROWS: list[list[tuple[str, str | None, float]]] = [
    [('', None, 1), ('▲', 'up', 1), ('', None, 1)],
    [('◄', 'left', 1), ('▼', 'down', 1), ('►', 'right', 1)],
]

_MODIFIER_ORDER = {'ctrl': 0, 'shift': 1, 'alt': 2, 'super': 3}


class _RecordFilter(QObject):
    """Event filter that captures keyboard input during record mode.

    Only intercepts QKeyEvent — mouse events pass through untouched, so the
    user can always click the Stop button to end recording.
    """
    captured     = Signal(list)    # list[str] emitted when all keys released
    held_changed = Signal(object)  # set[str]  emitted on every press/release

    def __init__(self, parent=None):
        super().__init__(parent)
        self._held:     set[str]  = set()
        self._captured: list[str] = []

    def reset(self):
        self._held.clear()
        self._captured.clear()

    def eventFilter(self, obj, event) -> bool:
        t = event.type()
        if t == QEvent.Type.KeyPress and not event.isAutoRepeat():
            name = _QT_TO_NAME.get(int(event.key()))
            if name and name not in self._held:
                self._held.add(name)
                if name not in self._captured:
                    self._captured.append(name)
            self.held_changed.emit(set(self._held))
            return True
        if t == QEvent.Type.KeyRelease and not event.isAutoRepeat():
            name = _QT_TO_NAME.get(int(event.key()))
            if name:
                self._held.discard(name)
            self.held_changed.emit(set(self._held))
            if not self._held and self._captured:
                self.captured.emit(list(self._captured))
                self._captured.clear()
            return True
        return False


class KeyboardWidget(QWidget):
    """Visual keyboard — click keys to toggle them on/off."""

    key_clicked = Signal(str, bool)  # name, is_now_checked

    def __init__(self, parent=None):
        super().__init__(parent)
        self._buttons: dict[str, list[QPushButton]] = {}
        self._build()

    def _build(self):
        f = self.font()
        f.setPointSize(8)

        y = _MARGIN
        main_row_w = 0
        for row_idx, row in enumerate(_KB_ROWS):
            is_fn = row_idx < _FN_ROWS
            kh = _KH_FN if is_fn else _KH
            x  = _MARGIN
            for label, name, w in row:
                px_w = int(w * _UNIT)
                if name is not None:
                    btn = QPushButton(label, self)
                    btn.setGeometry(x, y, px_w - 2, kh)
                    btn.setCheckable(True)
                    btn.setFont(f)
                    btn.setProperty('kname', name)
                    btn.clicked.connect(self._btn_clicked)
                    self._buttons.setdefault(name, []).append(btn)
                x += px_w
            main_row_w = max(main_row_w, x)
            extra = _FN_EXTRA if row_idx == _FN_ROWS - 1 else 0
            y += kh + _RGAP + extra

        last_main_bottom = y - _RGAP
        total_h = last_main_bottom + _MARGIN

        # Arrow keys: right of main keyboard, aligned with ZXCV + bottom rows
        zxcv_y  = (_MARGIN + _FN_ROWS * (_KH_FN + _RGAP) + _FN_EXTRA + 3 * (_KH + _RGAP))
        arrow_x = main_row_w + 8
        for i, row in enumerate(_ARROW_ROWS):
            ay = zxcv_y + i * (_KH + _RGAP)
            x  = arrow_x
            for label, name, w in row:
                px_w = int(w * _UNIT)
                if name is not None:
                    btn = QPushButton(label, self)
                    btn.setGeometry(x, ay, px_w - 2, _KH)
                    btn.setCheckable(True)
                    btn.setFont(f)
                    btn.setProperty('kname', name)
                    btn.clicked.connect(self._btn_clicked)
                    self._buttons.setdefault(name, []).append(btn)
                x += px_w

        self.setFixedSize(arrow_x + 3 * _UNIT + _MARGIN, total_h)

    def _btn_clicked(self):
        btn  = self.sender()
        name = btn.property('kname')
        chk  = btn.isChecked()
        for b in self._buttons.get(name, []):
            b.setChecked(chk)
        self._apply_styles()
        self.key_clicked.emit(name, chk)

    def _apply_styles(self, held: set | None = None):
        if held is None:
            held = set()
        for name, btns in self._buttons.items():
            checked = any(b.isChecked() for b in btns)
            if name in held:
                style = ('QPushButton{background:#7a6020;color:white;'
                         'border:1px solid #5a4010;border-radius:3px;}')
            elif checked:
                style = ('QPushButton{background:#2a7a2a;color:white;'
                         'border:1px solid #1a5a1a;border-radius:3px;}')
            else:
                style = ''
            for btn in btns:
                btn.setStyleSheet(style)

    def set_selected(self, names: list[str]):
        name_set = set(names)
        for name, btns in self._buttons.items():
            for btn in btns:
                btn.setChecked(name in name_set)
        self._apply_styles()

    def get_selected(self) -> list[str]:
        result = [n for n, btns in self._buttons.items()
                  if any(b.isChecked() for b in btns)]
        result.sort(key=lambda n: (_MODIFIER_ORDER.get(n, 99), n))
        return result

    def set_held(self, held: set):
        self._apply_styles(held)

    def set_clickable(self, enabled: bool):
        for btns in self._buttons.values():
            for btn in btns:
                btn.setEnabled(enabled)


class KeyPickerWidget(QWidget):
    """Summary label + Record button + visual KeyboardWidget."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._filter = _RecordFilter()
        self._filter.captured.connect(self._on_captured)
        self._build_ui()
        self._filter.held_changed.connect(self._kb.set_held)

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        top = QHBoxLayout()
        self._summary = QLabel('(none)')
        self._summary.setStyleSheet('font-weight: bold;')
        top.addWidget(self._summary)
        top.addStretch()
        self._rec_btn = QPushButton('⏺  Record')
        self._rec_btn.setCheckable(True)
        self._rec_btn.setFixedWidth(100)
        self._rec_btn.clicked.connect(self._toggle_record)
        top.addWidget(self._rec_btn)
        layout.addLayout(top)

        self._kb = KeyboardWidget()
        self._kb.key_clicked.connect(self._on_key_clicked)
        layout.addWidget(self._kb)

        self._rec_hint = QLabel('Press keys, then release all to capture.  Click ⏹ Stop to cancel.')
        self._rec_hint.setStyleSheet('color: #888; font-size: 11px;')
        self._rec_hint.setVisible(False)
        layout.addWidget(self._rec_hint)

    def _toggle_record(self, checked: bool):
        if checked:
            dlg = self._find_dialog()
            if dlg:
                dlg.installEventFilter(self._filter)
            self._filter.reset()
            self._kb.set_clickable(False)
            self._kb.set_held(set())
            self._rec_btn.setText('⏹  Stop')
            self._rec_hint.setVisible(True)
        else:
            self._stop_recording()

    def _stop_recording(self):
        dlg = self._find_dialog()
        if dlg:
            dlg.removeEventFilter(self._filter)
        self._kb.set_clickable(True)
        self._kb.set_held(set())
        self._rec_btn.setChecked(False)
        self._rec_btn.setText('⏺  Record')
        self._rec_hint.setVisible(False)

    def _on_captured(self, keys: list[str]):
        self._stop_recording()
        self._kb.set_selected(keys)
        self._update_summary()

    def _on_key_clicked(self, name: str, checked: bool):
        self._update_summary()

    def _update_summary(self):
        keys = self._kb.get_selected()
        self._summary.setText(' + '.join(keys) if keys else '(none)')

    def _find_dialog(self):
        w = self.parent()
        while w:
            if isinstance(w, QDialog):
                return w
            w = w.parent()
        return None

    def set_keys(self, keys: list[str]):
        self._kb.set_selected(keys)
        self._update_summary()

    def get_keys(self) -> list[str]:
        return self._kb.get_selected()


# ── macro editor dialog ───────────────────────────────────────────────────────

class MacroDialog(QDialog):
    def __init__(self, gkey: str, action: cfg.MacroAction, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f'Edit {gkey.upper()} Macro')
        self.setMinimumWidth(570)
        self._gkey   = gkey
        self._action = cfg.MacroAction(
            action=action.action, text=action.text,
            cmd=action.cmd, keys=list(action.keys),
            mouse_btn=action.mouse_btn, mouse_mode=action.mouse_mode,
            repeat=action.repeat, repeat_rate=action.repeat_rate,
        )
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        # action type selector
        type_group = QGroupBox('Action type')
        type_layout = QHBoxLayout(type_group)
        self._btn_none    = QRadioButton('None')
        self._btn_type    = QRadioButton('Type text')
        self._btn_command = QRadioButton('Run command')
        self._btn_combo   = QRadioButton('Key combo')
        self._btn_hold    = QRadioButton('Hold toggle')
        self._btn_mouse   = QRadioButton('Mouse button')
        self._bg = QButtonGroup(self)
        for i, btn in enumerate([self._btn_none, self._btn_type, self._btn_command,
                                  self._btn_combo, self._btn_hold, self._btn_mouse]):
            self._bg.addButton(btn, i)
            type_layout.addWidget(btn)
        layout.addWidget(type_group)

        # type text area
        self._type_group = QGroupBox('Text to type')
        tg_layout = QVBoxLayout(self._type_group)
        self._text_edit = QTextEdit()
        self._text_edit.setMaximumHeight(80)
        self._text_edit.setPlaceholderText('Text that will be typed when key is pressed…')
        tg_layout.addWidget(self._text_edit)
        layout.addWidget(self._type_group)

        # command area
        self._cmd_group = QGroupBox('Shell command')
        cg_layout = QVBoxLayout(self._cmd_group)
        self._cmd_edit = QLineEdit()
        self._cmd_edit.setPlaceholderText('e.g.  notify-send "G1 pressed"')
        cg_layout.addWidget(self._cmd_edit)
        layout.addWidget(self._cmd_group)

        # keys area (combo + hold_toggle)
        self._keys_group = QGroupBox('Keys')
        kg_layout = QVBoxLayout(self._keys_group)
        self._keys_mode_hint = QLabel()
        self._keys_mode_hint.setStyleSheet('color: #888; font-size: 11px;')
        self._keys_mode_hint.setWordWrap(True)
        kg_layout.addWidget(self._keys_mode_hint)
        self._key_picker = KeyPickerWidget()
        self._key_picker.set_keys(self._action.keys)
        kg_layout.addWidget(self._key_picker)
        layout.addWidget(self._keys_group)

        # mouse button area
        self._mouse_group = QGroupBox('Mouse button')
        mg_layout = QFormLayout(self._mouse_group)
        self._mouse_btn_combo = QComboBox()
        for label, val in [('Left', 'left'), ('Right', 'right'), ('Middle', 'middle'),
                            ('Button 4', 'button4'), ('Button 5', 'button5')]:
            self._mouse_btn_combo.addItem(label, val)
        self._mouse_mode_combo = QComboBox()
        for label, val in [('Click', 'click'), ('Double-click', 'double_click'), ('Hold toggle', 'hold')]:
            self._mouse_mode_combo.addItem(label, val)
        mg_layout.addRow('Button:', self._mouse_btn_combo)
        mg_layout.addRow('Mode:', self._mouse_mode_combo)
        layout.addWidget(self._mouse_group)

        # repeat while held
        self._repeat_group = QGroupBox('Repeat while held')
        self._repeat_group.setCheckable(True)
        self._repeat_group.setChecked(self._action.repeat)
        rg_layout = QHBoxLayout(self._repeat_group)
        rg_layout.addWidget(QLabel('Rate:'))
        self._repeat_rate_spin = QSpinBox()
        self._repeat_rate_spin.setRange(10, 5000)
        self._repeat_rate_spin.setSingleStep(10)
        self._repeat_rate_spin.setSuffix(' ms')
        self._repeat_rate_spin.setValue(int(self._action.repeat_rate))
        rg_layout.addWidget(self._repeat_rate_spin)
        rg_layout.addStretch()
        layout.addWidget(self._repeat_group)

        # buttons
        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self._accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

        # populate from existing action
        self._text_edit.setPlainText(self._action.text)
        self._cmd_edit.setText(self._action.cmd)
        btn_idx = self._mouse_btn_combo.findData(self._action.mouse_btn)
        if btn_idx >= 0:
            self._mouse_btn_combo.setCurrentIndex(btn_idx)
        mode_idx = self._mouse_mode_combo.findData(self._action.mouse_mode)
        if mode_idx >= 0:
            self._mouse_mode_combo.setCurrentIndex(mode_idx)
        {
            'none':         self._btn_none,
            'type':         self._btn_type,
            'command':      self._btn_command,
            'combo':        self._btn_combo,
            'hold_toggle':  self._btn_hold,
            'mouse_button': self._btn_mouse,
        }.get(self._action.action, self._btn_none).setChecked(True)
        self._bg.idClicked.connect(self._update_visibility)
        self._update_visibility()

    def _update_visibility(self, _ = None):
        is_type  = self._btn_type.isChecked()
        is_cmd   = self._btn_command.isChecked()
        is_combo = self._btn_combo.isChecked()
        is_hold  = self._btn_hold.isChecked()
        is_mouse = self._btn_mouse.isChecked()
        self._type_group.setVisible(is_type)
        self._cmd_group.setVisible(is_cmd)
        self._keys_group.setVisible(is_combo or is_hold)
        self._mouse_group.setVisible(is_mouse)
        self._repeat_group.setVisible(not (is_hold or self._btn_none.isChecked()))
        if is_combo:
            self._keys_mode_hint.setText(
                'All selected keys are pressed together, then released.'
            )
        elif is_hold:
            self._keys_mode_hint.setText(
                'First G-key press holds the keys down.  Second press releases them.'
            )
        self.adjustSize()

    def _accept(self):
        if self._btn_type.isChecked():
            self._action.action = 'type'
            self._action.text   = self._text_edit.toPlainText()
        elif self._btn_command.isChecked():
            self._action.action = 'command'
            self._action.cmd    = self._cmd_edit.text().strip()
        elif self._btn_combo.isChecked():
            self._action.action = 'combo'
            self._action.keys   = self._key_picker.get_keys()
        elif self._btn_hold.isChecked():
            self._action.action = 'hold_toggle'
            self._action.keys   = self._key_picker.get_keys()
        elif self._btn_mouse.isChecked():
            self._action.action     = 'mouse_button'
            self._action.mouse_btn  = self._mouse_btn_combo.currentData()
            self._action.mouse_mode = self._mouse_mode_combo.currentData()
        else:
            self._action.action = 'none'
        if self._repeat_group.isVisible():
            self._action.repeat      = self._repeat_group.isChecked()
            self._action.repeat_rate = float(self._repeat_rate_spin.value())
        else:
            self._action.repeat = False
        self.accept()

    def result_action(self) -> cfg.MacroAction:
        return self._action


# ── profile editor panel ──────────────────────────────────────────────────────

class ProfilePanel(QWidget):
    profile_saved = Signal(str)

    def __init__(self, profile: cfg.Profile, parent=None):
        super().__init__(parent)
        self._profile = profile
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        # display name
        name_row = QHBoxLayout()
        name_row.addWidget(QLabel('Profile name:'))
        self._name_edit = QLineEdit(self._profile.display_name)
        name_row.addWidget(self._name_edit)
        layout.addLayout(name_row)

        # colour
        colour_row = QHBoxLayout()
        colour_row.addWidget(QLabel('Colour:'))
        self._colour_btn = QPushButton()
        self._colour_btn.setFixedWidth(48)
        self._set_colour_btn(self._profile.lighting_colour)
        self._colour_btn.clicked.connect(self._pick_colour)
        colour_row.addWidget(self._colour_btn)
        colour_row.addStretch()
        layout.addLayout(colour_row)

        # g-key buttons
        gkey_group = QGroupBox('G-key macros')
        gkey_layout = QVBoxLayout(gkey_group)
        self._gkey_buttons: dict[str, QPushButton] = {}
        for k in cfg.G_KEYS:
            row = QHBoxLayout()
            lbl = QLabel(k.upper())
            lbl.setFixedWidth(30)
            row.addWidget(lbl)
            btn = QPushButton(self._macro_summary(self._profile.macros[k]))
            btn.setProperty('gkey', k)
            btn.clicked.connect(self._edit_macro)
            btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            self._gkey_buttons[k] = btn
            row.addWidget(btn)
            clr = QPushButton('×')
            clr.setFixedWidth(26)
            clr.setToolTip('Clear macro')
            clr.setProperty('gkey', k)
            clr.clicked.connect(self._clear_macro)
            row.addWidget(clr)
            gkey_layout.addLayout(row)
        layout.addWidget(gkey_group)

        layout.addStretch()

        # save button
        save_btn = QPushButton('\U0001f4be  Save profile')
        save_btn.clicked.connect(self._save)
        layout.addWidget(save_btn)

    # ── actions ───────────────────────────────────────────────────────────────

    def _pick_colour(self):
        c = QColorDialog.getColor(QColor(self._profile.lighting_colour), self, 'Profile colour')
        if c.isValid():
            self._profile.lighting_colour = c.name()
            self._profile.tray_colour     = c.name()
            self._set_colour_btn(c.name())

    def _set_colour_btn(self, hex_colour: str):
        self._colour_btn.setStyleSheet(
            f'background-color: {hex_colour}; border: 1px solid #555;'
        )

    def _edit_macro(self):
        btn  = self.sender()
        gkey = btn.property('gkey')
        dlg  = MacroDialog(gkey, self._profile.macros[gkey], self)
        if dlg.exec() == QDialog.Accepted:
            self._profile.macros[gkey] = dlg.result_action()
            self._gkey_buttons[gkey].setText(self._macro_summary(self._profile.macros[gkey]))

    def _clear_macro(self):
        gkey = self.sender().property('gkey')
        self._profile.macros[gkey] = cfg.MacroAction()
        self._gkey_buttons[gkey].setText(self._macro_summary(self._profile.macros[gkey]))

    def _macro_summary(self, action: cfg.MacroAction) -> str:
        if action.action == 'type':
            preview = action.text[:40].replace('\n', '↵')
            return f'Type: {preview}' if preview else 'Type: (empty)'
        if action.action == 'command':
            return f'Run: {action.cmd[:40]}' if action.cmd else 'Run: (empty)'
        if action.action == 'combo':
            keys = ' + '.join(action.keys) if action.keys else '(no keys)'
            return f'Combo: {keys}'
        if action.action == 'hold_toggle':
            keys = ' + '.join(action.keys) if action.keys else '(no keys)'
            return f'Hold: {keys}'
        if action.action == 'mouse_button':
            mode = {'click': 'Click', 'double_click': 'Dbl-click', 'hold': 'Hold'}.get(action.mouse_mode, action.mouse_mode)
            return f'Mouse: {action.mouse_btn} ({mode})'
        return '— unassigned —'

    def _save(self):
        self._profile.display_name = self._name_edit.text().strip() or self._profile.name
        cfg.save_profile(self._profile)
        daemon.daemon_reload()
        self.profile_saved.emit(self._profile.name)


# ── M-key slot assignment widget ─────────────────────────────────────────────

class MKeySlotsWidget(QGroupBox):
    """Three dropdowns assigning profiles to M1/M2/M3."""

    def __init__(self, parent=None):
        super().__init__('M-key slots', parent)
        self._combos: dict[str, QComboBox] = {}
        self._build_ui()

    def _build_ui(self):
        layout = QFormLayout(self)
        layout.setContentsMargins(4, 6, 4, 4)
        layout.setSpacing(4)
        for key in ('m1', 'm2', 'm3'):
            cb = QComboBox()
            layout.addRow(key.upper() + ':', cb)
            self._combos[key] = cb
        save_btn = QPushButton('Save slots')
        save_btn.clicked.connect(self._save)
        layout.addRow(save_btn)

    def refresh(self, profiles: list[cfg.Profile]):
        gcfg  = cfg.load_global_config()
        slots = gcfg.get('profile_slots', {})
        for key, cb in self._combos.items():
            cb.blockSignals(True)
            cb.clear()
            cb.addItem('(none)', '')
            for p in profiles:
                cb.addItem(p.display_name, p.name)
            current = slots.get(key, '')
            idx = cb.findData(current)
            cb.setCurrentIndex(idx if idx >= 0 else 0)
            cb.blockSignals(False)

    def _save(self):
        gcfg  = cfg.load_global_config()
        slots = {}
        for key, cb in self._combos.items():
            val = cb.currentData()
            if val:
                slots[key] = val
        gcfg['profile_slots'] = slots
        cfg.save_global_config(gcfg)
        daemon.daemon_reload()


# ── main window ───────────────────────────────────────────────────────────────

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('Kyxen')
        self.setMinimumSize(680, 520)
        self._build_ui()
        self._refresh_profiles()

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QHBoxLayout(central)

        # left: profile list
        left = QWidget()
        left.setFixedWidth(200)
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(4, 4, 4, 4)

        left_layout.addWidget(QLabel('Profiles'))
        self._profile_list = QListWidget()
        self._profile_list.currentRowChanged.connect(self._on_profile_selected)
        left_layout.addWidget(self._profile_list)

        btn_row = QHBoxLayout()
        new_btn = QPushButton('New')
        new_btn.clicked.connect(self._new_profile)
        dup_btn = QPushButton('Duplicate')
        dup_btn.clicked.connect(self._duplicate_profile)
        del_btn = QPushButton('Delete')
        del_btn.clicked.connect(self._delete_profile)
        for b in (new_btn, dup_btn, del_btn):
            b.setMaximumWidth(70)
            btn_row.addWidget(b)
        left_layout.addLayout(btn_row)

        # M-key slot assignment
        self._mkey_slots = MKeySlotsWidget()
        left_layout.addWidget(self._mkey_slots)

        # daemon status indicator
        self._status_label = QLabel()
        self._status_label.setAlignment(Qt.AlignCenter)
        left_layout.addWidget(self._status_label)

        # right: profile editor
        self._right_stack = QWidget()
        self._right_layout = QVBoxLayout(self._right_stack)
        self._right_layout.setContentsMargins(0, 0, 0, 0)

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(left)
        splitter.addWidget(self._right_stack)
        splitter.setStretchFactor(1, 1)
        main_layout.addWidget(splitter)

        # status update timer
        self._status_timer = QTimer(self)
        self._status_timer.timeout.connect(self._update_status)
        self._status_timer.start(2000)
        self._update_status()

    def _refresh_profiles(self):
        self._profiles = cfg.list_profiles()
        if not self._profiles:
            self._profiles = [cfg.ensure_default_profile()]
        self._profile_list.clear()
        gcfg  = cfg.load_global_config()
        active = gcfg.get('active_profile', 'default')
        for i, p in enumerate(self._profiles):
            item = QListWidgetItem(make_colour_icon(p.tray_colour), p.display_name)
            item.setData(Qt.UserRole, p.name)
            self._profile_list.addItem(item)
            if p.name == active:
                self._profile_list.setCurrentRow(i)
        if self._profile_list.currentRow() < 0 and self._profiles:
            self._profile_list.setCurrentRow(0)
        self._mkey_slots.refresh(self._profiles)

    def _on_profile_selected(self, row: int):
        for i in reversed(range(self._right_layout.count())):
            w = self._right_layout.itemAt(i).widget()
            if w:
                w.deleteLater()
        if row < 0 or row >= len(self._profiles):
            return
        panel = ProfilePanel(self._profiles[row])
        panel.profile_saved.connect(self._on_profile_saved)
        self._right_layout.addWidget(panel)

    def _on_profile_saved(self, name: str):
        self._refresh_profiles()

    def _new_profile(self):
        text, ok = QInputDialog.getText(self, 'New profile', 'Profile ID (no spaces):')
        if not ok or not text.strip():
            return
        name = text.strip().replace(' ', '_').lower()
        p = cfg.Profile(name=name, display_name=text.strip())
        cfg.save_profile(p)
        self._refresh_profiles()

    def _duplicate_profile(self):
        item = self._profile_list.currentItem()
        if not item:
            return
        src_name = item.data(Qt.UserRole)
        src = next((p for p in self._profiles if p.name == src_name), None)
        if not src:
            return
        text, ok = QInputDialog.getText(self, 'Duplicate profile', 'New profile ID:')
        if not ok or not text.strip():
            return
        name = text.strip().replace(' ', '_').lower()
        new_p = cfg.Profile(
            name=name,
            display_name=text.strip(),
            tray_colour=src.tray_colour,
            trigger_apps=list(src.trigger_apps),
            lighting_mode=src.lighting_mode,
            lighting_colour=src.lighting_colour,
        )
        for k in cfg.G_KEYS:
            a = src.macros[k]
            new_p.macros[k] = cfg.MacroAction(
                action=a.action, text=a.text, cmd=a.cmd, keys=list(a.keys),
                mouse_btn=a.mouse_btn, mouse_mode=a.mouse_mode,
                repeat=a.repeat, repeat_rate=a.repeat_rate,
            )
        cfg.save_profile(new_p)
        self._refresh_profiles()

    def _delete_profile(self):
        item = self._profile_list.currentItem()
        if not item:
            return
        name = item.data(Qt.UserRole)
        if name == 'default':
            QMessageBox.warning(self, 'Cannot delete', 'The default profile cannot be deleted.')
            return
        if QMessageBox.question(self, 'Delete profile',
                                f'Delete profile "{item.text()}"?') != QMessageBox.Yes:
            return
        cfg.delete_profile(name)
        daemon.daemon_reload()
        self._refresh_profiles()

    def _update_status(self):
        if daemon.daemon_running():
            status = daemon.daemon_status()
            active = status.get('active_profile', '?') if status else '?'
            self._status_label.setText(f'● Daemon running\nProfile: {active}')
            self._status_label.setStyleSheet('color: #44cc44;')
        else:
            self._status_label.setText('○ Daemon not running')
            self._status_label.setStyleSheet('color: #cc4444;')


# ── system tray ───────────────────────────────────────────────────────────────

class TrayIcon(QSystemTrayIcon):
    def __init__(self, app: QApplication, window: MainWindow):
        super().__init__()
        self._app    = app
        self._window = window
        self._menu   = QMenu()
        self._profile_section: list[QAction] = []

        self.setIcon(make_tray_icon('#00CC44'))
        self.setToolTip('Kyxen')
        self.activated.connect(self._on_activated)

        self._refresh_menu()

        self._poll = QTimer()
        self._poll.timeout.connect(self._refresh_menu)
        self._poll.start(3000)

    def _refresh_menu(self):
        self._menu.clear()

        status = daemon.daemon_status()
        active = status.get('active_profile') if status else None
        profiles = cfg.list_profiles()

        if profiles:
            for p in profiles:
                action = self._menu.addAction(
                    make_colour_icon(p.tray_colour), p.display_name
                )
                action.setCheckable(True)
                action.setChecked(p.name == active)
                action.setData(p.name)
                action.triggered.connect(self._switch_profile)

            self._menu.addSeparator()

        if active:
            col = next((p.tray_colour for p in profiles if p.name == active), '#00CC44')
            self.setIcon(make_tray_icon(col))
            self.setToolTip(f'Kyxen — {active}')

        edit_action = self._menu.addAction('⚙  Configure…')
        edit_action.triggered.connect(self._show_window)
        self._menu.addSeparator()
        quit_action = self._menu.addAction('Quit')
        quit_action.triggered.connect(self._app.quit)

        self.setContextMenu(self._menu)

    def _switch_profile(self):
        action = self.sender()
        name   = action.data()
        daemon.daemon_switch_profile(name)
        self._refresh_menu()

    def _on_activated(self, reason):
        if reason == QSystemTrayIcon.Trigger:
            self._show_window()

    def _show_window(self):
        self._window._refresh_profiles()
        self._window.show()
        self._window.raise_()
        self._window.activateWindow()


# ── entry point ───────────────────────────────────────────────────────────────

def main():
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    app.setApplicationName('Kyxen')

    cfg.ensure_default_profile()

    window = MainWindow()
    tray   = TrayIcon(app, window)

    if not QSystemTrayIcon.isSystemTrayAvailable():
        window.show()

    tray.show()
    sys.exit(app.exec())
