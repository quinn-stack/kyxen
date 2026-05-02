"""G815 Manager — PySide6 GUI (system tray + editor window)."""
from __future__ import annotations
import sys
from pathlib import Path

from PySide6.QtCore    import Qt, QTimer, Signal, QObject
from PySide6.QtGui     import QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QApplication, QColorDialog, QDialog, QDialogButtonBox,
    QFormLayout, QHBoxLayout, QInputDialog, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QMainWindow, QMenu, QMessageBox,
    QPushButton, QRadioButton, QSizePolicy, QSplitter, QSystemTrayIcon,
    QTabWidget, QTextEdit, QVBoxLayout, QWidget, QComboBox,
    QButtonGroup, QGroupBox, QFrame,
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


# ── macro editor dialog ───────────────────────────────────────────────────────

class MacroDialog(QDialog):
    def __init__(self, gkey: str, action: cfg.MacroAction, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f'Edit {gkey.upper()} Macro')
        self.setMinimumWidth(420)
        self._gkey   = gkey
        self._action = cfg.MacroAction(
            action=action.action, text=action.text, cmd=action.cmd
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
        self._bg = QButtonGroup(self)
        for i, btn in enumerate([self._btn_none, self._btn_type, self._btn_command]):
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

        # buttons
        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self._accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

        # populate from existing action
        self._text_edit.setPlainText(self._action.text)
        self._cmd_edit.setText(self._action.cmd)
        {
            'none':    self._btn_none,
            'type':    self._btn_type,
            'command': self._btn_command,
        }.get(self._action.action, self._btn_none).setChecked(True)
        self._bg.idClicked.connect(self._update_visibility)
        self._update_visibility()

    def _update_visibility(self, _ = None):
        is_type = self._btn_type.isChecked()
        is_cmd  = self._btn_command.isChecked()
        self._type_group.setVisible(is_type)
        self._cmd_group.setVisible(is_cmd)
        self.adjustSize()

    def _accept(self):
        if self._btn_type.isChecked():
            self._action.action = 'type'
            self._action.text   = self._text_edit.toPlainText()
        elif self._btn_command.isChecked():
            self._action.action = 'command'
            self._action.cmd    = self._cmd_edit.text().strip()
        else:
            self._action.action = 'none'
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
            gkey_layout.addLayout(row)
        layout.addWidget(gkey_group)

        # trigger apps
        app_group = QGroupBox('Auto-switch when these apps are focused')
        app_layout = QVBoxLayout(app_group)
        self._app_list = QListWidget()
        self._app_list.setMaximumHeight(80)
        for app in self._profile.trigger_apps:
            self._app_list.addItem(app)
        app_btns = QHBoxLayout()
        add_btn = QPushButton('Add')
        add_btn.clicked.connect(self._add_app)
        del_btn = QPushButton('Remove')
        del_btn.clicked.connect(self._del_app)
        app_btns.addWidget(add_btn)
        app_btns.addWidget(del_btn)
        app_btns.addStretch()
        app_layout.addWidget(self._app_list)
        app_layout.addLayout(app_btns)
        layout.addWidget(app_group)

        layout.addStretch()

        # save button
        save_btn = QPushButton('💾  Save profile')
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
            btn.setText(self._macro_summary(self._profile.macros[gkey]))

    def _macro_summary(self, action: cfg.MacroAction) -> str:
        if action.action == 'type':
            preview = action.text[:40].replace('\n', '↵')
            return f'Type: {preview}' if preview else 'Type: (empty)'
        if action.action == 'command':
            return f'Run: {action.cmd[:40]}' if action.cmd else 'Run: (empty)'
        return '— unassigned —'

    def _add_app(self):
        text, ok = QInputDialog.getText(self, 'Add app trigger',
                                        'Window title or process name (partial match):')
        if ok and text.strip():
            self._app_list.addItem(text.strip())

    def _del_app(self):
        for item in self._app_list.selectedItems():
            self._app_list.takeItem(self._app_list.row(item))

    def _save(self):
        self._profile.display_name    = self._name_edit.text().strip() or self._profile.name
        self._profile.trigger_apps    = [
            self._app_list.item(i).text()
            for i in range(self._app_list.count())
        ]
        cfg.save_profile(self._profile)
        daemon.daemon_reload()
        self.profile_saved.emit(self._profile.name)


# ── main window ───────────────────────────────────────────────────────────────

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('G815 Key Manager')
        self.setMinimumSize(680, 520)
        self._build_ui()
        self._refresh_profiles()

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QHBoxLayout(central)

        # left: profile list
        left = QWidget()
        left.setFixedWidth(180)
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
            new_p.macros[k] = cfg.MacroAction(action=a.action, text=a.text, cmd=a.cmd)
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
        self.setToolTip('G815 Key Manager')
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
            self.setToolTip(f'G815 — {active}')

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
    app.setApplicationName('G815 Manager')

    cfg.ensure_default_profile()

    window = MainWindow()
    tray   = TrayIcon(app, window)

    if not QSystemTrayIcon.isSystemTrayAvailable():
        window.show()

    tray.show()
    sys.exit(app.exec())
