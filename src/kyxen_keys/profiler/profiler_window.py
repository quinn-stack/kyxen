"""
ProfilerWindow — 4-page wizard for creating a Kyxen keyboard driver.

Pages:
  0  SetupPage       — pick hidraw device, enter model name / G-key count
  1  KeyMapperPage   — LED probe (light each LED, user presses the key)
  2  LayoutEditorPage — table of key X/Y/W/H positions + visual preview
  3  DriverOutputPage — generated Python code, copy / save
"""
from __future__ import annotations
from pathlib import Path

from PySide6.QtCore    import Qt, Slot
from PySide6.QtGui     import QColor, QFont, QFontMetrics, QGuiApplication, QKeyEvent, QPainter
from PySide6.QtWidgets import (
    QApplication, QComboBox, QFileDialog, QFrame, QGroupBox, QHBoxLayout,
    QHeaderView, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMainWindow,
    QMessageBox, QProgressBar, QPushButton, QScrollArea, QSizePolicy,
    QSpinBox, QStackedWidget, QTableWidget, QTableWidgetItem, QTextEdit,
    QVBoxLayout, QWidget,
)

from . import hid_probe
from .probe_worker import ProbeWorker, key_event_to_name
from .driver_gen   import generate, suggested_filename
from ..keyboard_layout import LAYOUT as _G815_LAYOUT
from .. import config as cfg


# ── Helpers ───────────────────────────────────────────────────────────────────

def _sep() -> QFrame:
    f = QFrame()
    f.setFrameShape(QFrame.Shape.HLine)
    f.setFrameShadow(QFrame.Shadow.Sunken)
    return f


def _bold(text: str) -> QLabel:
    lbl = QLabel(text)
    f = lbl.font()
    f.setBold(True)
    lbl.setFont(f)
    return lbl


# ── Layout preview widget ─────────────────────────────────────────────────────

_PX_PER_U = 28   # pixels per key unit


class LayoutPreview(QWidget):
    """Draws key rectangles based on (name, x, y, w, h) rows in key units."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._rows: list[tuple[str, float, float, float, float]] = []
        self.setMinimumSize(300, 100)

    def set_rows(self, rows: list[tuple[str, float, float, float, float]]) -> None:
        self._rows = rows
        self._recompute()
        self.update()

    def _recompute(self) -> None:
        if not self._rows:
            self.setFixedSize(300, 100)
            return
        max_x = max(x + w for _, x, y, w, h in self._rows)
        max_y = max(y + h for _, x, y, w, h in self._rows)
        self.setFixedSize(
            int(max_x * _PX_PER_U) + 20,
            int(max_y * _PX_PER_U) + 20,
        )

    def paintEvent(self, _evt) -> None:
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(30, 30, 30))
        p.setFont(QFont('monospace', 5))
        fm = QFontMetrics(p.font())
        margin = 10
        for name, x, y, w, h in self._rows:
            rx = margin + int(x * _PX_PER_U)
            ry = margin + int(y * _PX_PER_U)
            rw = max(1, int(w * _PX_PER_U) - 2)
            rh = max(1, int(h * _PX_PER_U) - 2)
            p.fillRect(rx, ry, rw, rh, QColor(60, 60, 80))
            p.setPen(QColor(140, 140, 200))
            p.drawRect(rx, ry, rw - 1, rh - 1)
            p.setPen(QColor(200, 200, 220))
            label = name if fm.horizontalAdvance(name) < rw - 2 else name[:3]
            p.drawText(rx + 1, ry + 1, rw - 2, rh - 2, Qt.AlignCenter, label)
        p.end()


# ── Page 0: Setup ─────────────────────────────────────────────────────────────

class SetupPage(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        layout.addWidget(_bold('Step 1 of 4 — Device Setup'))
        layout.addWidget(_sep())

        warn = QLabel(
            '⚠  Stop <b>kyxen-daemon</b> before running the profiler, otherwise '
            'it holds the device and probe commands may be ignored.<br>'
            'Run: <tt>kyxen-daemon stop</tt>  or  <tt>systemctl --user stop kyxen</tt>'
        )
        warn.setWordWrap(True)
        warn.setStyleSheet('background:#3a2800;padding:6px;border-radius:4px;')
        layout.addWidget(warn)

        layout.addSpacing(6)

        # HID device row
        row1 = QHBoxLayout()
        row1.addWidget(QLabel('HID device:'))
        self._combo = QComboBox()
        self._combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        row1.addWidget(self._combo)
        refresh_btn = QPushButton('Refresh')
        refresh_btn.clicked.connect(self._refresh_devices)
        row1.addWidget(refresh_btn)
        layout.addLayout(row1)

        self._pid_label = QLabel('Product ID: —')
        layout.addWidget(self._pid_label)
        self._combo.currentIndexChanged.connect(self._on_combo_change)

        layout.addSpacing(4)

        # Model name
        row2 = QHBoxLayout()
        row2.addWidget(QLabel('Model name:'))
        self._name_edit = QLineEdit()
        self._name_edit.setPlaceholderText('e.g. G512, G910 Orion Spark')
        row2.addWidget(self._name_edit)
        layout.addLayout(row2)

        # G-key count
        row3 = QHBoxLayout()
        row3.addWidget(QLabel('G-key count:'))
        self._gkey_spin = QSpinBox()
        self._gkey_spin.setRange(0, 20)
        self._gkey_spin.setValue(0)
        row3.addWidget(self._gkey_spin)
        row3.addStretch()
        layout.addLayout(row3)

        layout.addStretch()
        self._refresh_devices()

    def _refresh_devices(self) -> None:
        self._combo.clear()
        self._devices: list[tuple[str, int, int]] = hid_probe.find_logitech_hidraw()
        for path, vid, pid in self._devices:
            self._combo.addItem(f'{path}  —  Logitech  PID 0x{pid:04X}')
        if not self._devices:
            self._combo.addItem('(no Logitech HID devices found)')
        self._on_combo_change()

    def _on_combo_change(self) -> None:
        idx = self._combo.currentIndex()
        if 0 <= idx < len(self._devices):
            _, vid, pid = self._devices[idx]
            self._pid_label.setText(f'Product ID: 0x{pid:04X}')
        else:
            self._pid_label.setText('Product ID: —')

    @property
    def hidraw_path(self) -> str:
        idx = self._combo.currentIndex()
        if 0 <= idx < len(self._devices):
            return self._devices[idx][0]
        return ''

    @property
    def product_id(self) -> int:
        idx = self._combo.currentIndex()
        if 0 <= idx < len(self._devices):
            return self._devices[idx][2]
        return 0

    @property
    def model_name(self) -> str:
        return self._name_edit.text().strip()

    @property
    def gkey_count(self) -> int:
        return self._gkey_spin.value()


# ── Page 1: Key Mapper ────────────────────────────────────────────────────────

class KeyMapperPage(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        layout.addWidget(_bold('Step 2 of 4 — LED → Key Mapping'))
        layout.addWidget(_sep())

        self._status_lbl = QLabel('Press Start to begin the probe.')
        self._status_lbl.setWordWrap(True)
        layout.addWidget(self._status_lbl)

        self._progress = QProgressBar()
        self._progress.setRange(0, 255)
        self._progress.setValue(0)
        layout.addWidget(self._progress)

        instr = QLabel(
            '<b>When you see a key light up:</b> press that key on your keyboard.<br>'
            'If nothing is visibly lit, click <i>Skip</i>.'
        )
        instr.setWordWrap(True)
        layout.addWidget(instr)

        btn_row = QHBoxLayout()
        self._start_btn = QPushButton('▶  Start probe')
        self._skip_btn  = QPushButton('Skip — no key lit')
        self._stop_btn  = QPushButton('Stop probe')
        self._skip_btn.setEnabled(False)
        self._stop_btn.setEnabled(False)
        btn_row.addWidget(self._start_btn)
        btn_row.addWidget(self._skip_btn)
        btn_row.addWidget(self._stop_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        layout.addWidget(_sep())

        count_row = QHBoxLayout()
        count_row.addWidget(QLabel('Mapped keys:'))
        self._count_lbl = QLabel('0')
        count_row.addWidget(self._count_lbl)
        count_row.addStretch()
        layout.addLayout(count_row)

        self._list = QListWidget()
        self._list.setMaximumHeight(160)
        layout.addWidget(self._list)

        layout.addStretch()

        self._worker: ProbeWorker | None = None
        self._mapping: dict[int, str] = {}

    def prepare(self, hidraw_path: str) -> None:
        self._hidraw_path = hidraw_path
        self._mapping.clear()
        self._list.clear()
        self._count_lbl.setText('0')
        self._progress.setValue(0)
        self._status_lbl.setText('Click  ▶ Start probe  to begin.')
        self._start_btn.setEnabled(True)
        self._skip_btn.setEnabled(False)
        self._stop_btn.setEnabled(False)

        try:
            self._start_btn.clicked.disconnect()
        except RuntimeError:
            pass
        self._start_btn.clicked.connect(self._start)

    def _start(self) -> None:
        self._mapping.clear()
        self._list.clear()
        self._count_lbl.setText('0')
        self._progress.setValue(0)

        self._worker = ProbeWorker(self._hidraw_path)
        self._worker.led_testing.connect(self._on_led_testing)
        self._worker.key_mapped.connect(self._on_key_mapped)
        self._worker.led_skipped.connect(self._on_led_skipped)
        self._worker.probe_done.connect(self._on_done)
        self._worker.probe_error.connect(self._on_error)

        self._skip_btn.clicked.connect(self._worker.skip_current)
        self._stop_btn.clicked.connect(self._worker.stop_probe)

        self._start_btn.setEnabled(False)
        self._skip_btn.setEnabled(True)
        self._stop_btn.setEnabled(True)
        self._worker.start()

    @Slot(int)
    def _on_led_testing(self, led_id: int) -> None:
        self._progress.setValue(led_id)
        self._status_lbl.setText(
            f'Testing LED 0x{led_id:02X} ({led_id}/255) — '
            f'press the lit key or click Skip.'
        )

    @Slot(int, str)
    def _on_key_mapped(self, led_id: int, name: str) -> None:
        self._mapping[led_id] = name
        self._list.insertItem(0, f'LED 0x{led_id:02X}  →  {name}')
        self._count_lbl.setText(str(len(self._mapping)))

    @Slot(int)
    def _on_led_skipped(self, led_id: int) -> None:
        pass   # silently skip — only show mapped ones

    @Slot(dict)
    def _on_done(self, mapping: dict) -> None:
        self._mapping = dict(mapping)
        try:
            self._skip_btn.clicked.disconnect(self._worker.skip_current)
            self._stop_btn.clicked.disconnect(self._worker.stop_probe)
        except RuntimeError:
            pass
        self._start_btn.setEnabled(True)
        self._skip_btn.setEnabled(False)
        self._stop_btn.setEnabled(False)
        self._status_lbl.setText(
            f'Probe complete. {len(self._mapping)} keys mapped. '
            f'Click Next to edit the layout.'
        )
        self._progress.setValue(255)

    @Slot(str)
    def _on_error(self, msg: str) -> None:
        self._start_btn.setEnabled(True)
        self._skip_btn.setEnabled(False)
        self._stop_btn.setEnabled(False)
        self._status_lbl.setText(f'Error: {msg}')

    def receive_key(self, name: str) -> None:
        if self._worker and self._worker.isRunning():
            self._worker.receive_key(name)

    def stop_worker_if_running(self) -> None:
        if self._worker and self._worker.isRunning():
            self._worker.stop_probe()
            self._worker.wait()

    @property
    def mapping(self) -> dict[int, str]:
        return dict(self._mapping)


# ── Page 2: Layout Editor ─────────────────────────────────────────────────────

_LAYOUT_COLS = ('Key name', 'X', 'Y', 'W', 'H')


class LayoutEditorPage(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setSpacing(6)

        layout.addWidget(_bold('Step 3 of 4 — Key Layout'))
        layout.addWidget(_sep())

        help_lbl = QLabel(
            'Assign position and size to each mapped key. Units are "key units" '
            '(1u = standard key width ≈ 18 mm).  X=0, Y=0 = top-left of keyboard.'
        )
        help_lbl.setWordWrap(True)
        layout.addWidget(help_lbl)

        btn_row = QHBoxLayout()
        load_btn  = QPushButton('Load G815 positions for matching keys')
        clear_btn = QPushButton('Clear all positions')
        add_btn   = QPushButton('+ Add row')
        del_btn   = QPushButton('Remove selected')
        for b in (load_btn, clear_btn, add_btn, del_btn):
            btn_row.addWidget(b)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        # Table
        self._table = QTableWidget(0, len(_LAYOUT_COLS))
        self._table.setHorizontalHeaderLabels(list(_LAYOUT_COLS))
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for col in range(1, len(_LAYOUT_COLS)):
            self._table.horizontalHeader().setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)
        self._table.setMaximumHeight(220)
        layout.addWidget(self._table)

        # Preview
        layout.addWidget(QLabel('Layout preview:'))
        scroll = QScrollArea()
        self._preview = LayoutPreview()
        scroll.setWidget(self._preview)
        scroll.setWidgetResizable(False)
        scroll.setMaximumHeight(200)
        layout.addWidget(scroll)

        layout.addStretch()

        load_btn.clicked.connect(self._load_g815)
        clear_btn.clicked.connect(self._clear_positions)
        add_btn.clicked.connect(self._add_row)
        del_btn.clicked.connect(self._del_row)
        self._table.itemChanged.connect(self._refresh_preview)

    # ── G815 template: position lookup by key name ─────────────────────────────
    _G815_POS: dict[str, tuple[float, float, float, float]] = {
        kr.name: (kr.x, kr.y, kr.w, kr.h) for kr in _G815_LAYOUT
    }

    def populate(self, mapping: dict[int, str]) -> None:
        """Fill table from led_id→name mapping (only names; positions start blank)."""
        self._table.itemChanged.disconnect(self._refresh_preview)
        self._table.setRowCount(0)
        for led_id in sorted(mapping):
            name = mapping[led_id]
            self._append_row(name, 0.0, 0.0, 1.0, 1.0)
        self._table.itemChanged.connect(self._refresh_preview)
        self._refresh_preview()

    def _append_row(self, name: str, x: float, y: float, w: float, h: float) -> None:
        row = self._table.rowCount()
        self._table.insertRow(row)
        self._table.setItem(row, 0, QTableWidgetItem(name))
        for col, val in enumerate((x, y, w, h), start=1):
            self._table.setItem(row, col, QTableWidgetItem(str(round(val, 4))))

    def _load_g815(self) -> None:
        self._table.itemChanged.disconnect(self._refresh_preview)
        for row in range(self._table.rowCount()):
            name = (self._table.item(row, 0) or QTableWidgetItem('')).text().strip()
            pos  = self._G815_POS.get(name)
            if pos:
                x, y, w, h = pos
                for col, val in enumerate((x, y, w, h), start=1):
                    self._table.setItem(row, col, QTableWidgetItem(str(round(val, 4))))
        self._table.itemChanged.connect(self._refresh_preview)
        self._refresh_preview()

    def _clear_positions(self) -> None:
        self._table.itemChanged.disconnect(self._refresh_preview)
        for row in range(self._table.rowCount()):
            for col in range(1, len(_LAYOUT_COLS)):
                item = self._table.item(row, col)
                if item:
                    item.setText('0')
        self._table.itemChanged.connect(self._refresh_preview)
        self._refresh_preview()

    def _add_row(self) -> None:
        self._append_row('KEY', 0.0, 0.0, 1.0, 1.0)

    def _del_row(self) -> None:
        rows = sorted({idx.row() for idx in self._table.selectedIndexes()}, reverse=True)
        for r in rows:
            self._table.removeRow(r)
        self._refresh_preview()

    @Slot()
    def _refresh_preview(self) -> None:
        rows = self._get_rows()
        valid = [(n, x, y, w, h) for n, x, y, w, h in rows if x > 0 or y > 0 or w > 0 or h > 0]
        self._preview.set_rows(valid or rows)

    def _get_rows(self) -> list[tuple[str, float, float, float, float]]:
        result = []
        for row in range(self._table.rowCount()):
            try:
                name = (self._table.item(row, 0) or QTableWidgetItem('')).text().strip()
                x = float((self._table.item(row, 1) or QTableWidgetItem('0')).text())
                y = float((self._table.item(row, 2) or QTableWidgetItem('0')).text())
                w = float((self._table.item(row, 3) or QTableWidgetItem('1')).text())
                h = float((self._table.item(row, 4) or QTableWidgetItem('1')).text())
                if name:
                    result.append((name, x, y, w, h))
            except ValueError:
                pass
        return result

    @property
    def layout_rows(self) -> list[tuple[str, float, float, float, float]]:
        return self._get_rows()


# ── Page 3: Driver Output ─────────────────────────────────────────────────────

class DriverOutputPage(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setSpacing(6)

        layout.addWidget(_bold('Step 4 of 4 — Generated Driver'))
        layout.addWidget(_sep())

        self._editor = QTextEdit()
        self._editor.setReadOnly(True)
        self._editor.setFont(QFont('monospace', 9))
        layout.addWidget(self._editor)

        # Install path label
        self._install_lbl = QLabel()
        self._install_lbl.setWordWrap(True)
        self._install_lbl.setStyleSheet('color:#aaffaa;font-style:italic;')
        layout.addWidget(self._install_lbl)

        btn_row = QHBoxLayout()
        self._install_btn = QPushButton('⬇  Install to Kyxen drivers')
        self._install_btn.setToolTip(f'Save to {cfg.DRIVERS_DIR}')
        copy_btn  = QPushButton('Copy to clipboard')
        save_btn  = QPushButton('Save as…')
        btn_row.addWidget(self._install_btn)
        btn_row.addWidget(copy_btn)
        btn_row.addWidget(save_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        self._install_btn.clicked.connect(self._install)
        copy_btn.clicked.connect(self._copy)
        save_btn.clicked.connect(self._save)

        self._code     = ''
        self._filename = 'driver.py'

    def set_code(self, code: str, model_name: str = '') -> None:
        self._code     = code
        self._filename = suggested_filename(model_name) if model_name else 'driver.py'
        self._editor.setPlainText(code)
        dest = cfg.DRIVERS_DIR / self._filename
        self._install_lbl.setText(f'Install path: {dest}')

    @Slot()
    def _install(self) -> None:
        dest = cfg.DRIVERS_DIR / self._filename
        try:
            cfg.DRIVERS_DIR.mkdir(parents=True, exist_ok=True)
            dest.write_text(self._code, encoding='utf-8')
            QMessageBox.information(
                self, 'Driver installed',
                f'Driver saved to:\n{dest}\n\n'
                'The daemon will pick it up within 10 seconds — no restart needed.'
            )
        except Exception as e:
            QMessageBox.critical(self, 'Install failed', str(e))

    @Slot()
    def _copy(self) -> None:
        QGuiApplication.clipboard().setText(self._code)

    @Slot()
    def _save(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, 'Save driver', str(Path.home() / self._filename), 'Python files (*.py)'
        )
        if path:
            Path(path).write_text(self._code, encoding='utf-8')


# ── Main window ───────────────────────────────────────────────────────────────

class ProfilerWindow(QMainWindow):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle('Kyxen Profiler')
        self.setMinimumSize(700, 520)

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setSpacing(8)

        # Page title
        self._title_lbl = QLabel()
        self._title_lbl.setFont(QFont('', 13, QFont.Weight.Bold))
        root.addWidget(self._title_lbl)

        # Stack
        self._stack = QStackedWidget()
        self._setup_page  = SetupPage()
        self._mapper_page = KeyMapperPage()
        self._layout_page = LayoutEditorPage()
        self._output_page = DriverOutputPage()
        for p in (self._setup_page, self._mapper_page, self._layout_page, self._output_page):
            self._stack.addWidget(p)
        root.addWidget(self._stack, stretch=1)

        root.addWidget(_sep())

        # Navigation
        nav = QHBoxLayout()
        self._back_btn   = QPushButton('← Back')
        self._next_btn   = QPushButton('Next →')
        self._finish_btn = QPushButton('Finish')
        nav.addWidget(self._back_btn)
        nav.addStretch()
        nav.addWidget(self._next_btn)
        nav.addWidget(self._finish_btn)
        root.addLayout(nav)

        self._back_btn.clicked.connect(self._go_back)
        self._next_btn.clicked.connect(self._go_next)
        self._finish_btn.clicked.connect(self.close)

        self._go_to(0)

    def _go_to(self, idx: int) -> None:
        self._stack.setCurrentIndex(idx)
        titles = [
            'Step 1 of 4 — Device Setup',
            'Step 2 of 4 — LED → Key Mapping',
            'Step 3 of 4 — Key Layout',
            'Step 4 of 4 — Generated Driver',
        ]
        self._title_lbl.setText(titles[idx])
        self._back_btn.setEnabled(idx > 0)
        last = idx == self._stack.count() - 1
        self._next_btn.setVisible(not last)
        self._finish_btn.setVisible(last)

    @Slot()
    def _go_back(self) -> None:
        if self._stack.currentIndex() == 1:
            self._mapper_page.stop_worker_if_running()
        self._go_to(self._stack.currentIndex() - 1)

    @Slot()
    def _go_next(self) -> None:
        cur = self._stack.currentIndex()

        if cur == 0:
            if not self._validate_setup():
                return
            self._mapper_page.prepare(self._setup_page.hidraw_path)

        elif cur == 1:
            self._layout_page.populate(self._mapper_page.mapping)

        elif cur == 2:
            self._generate_driver()

        self._go_to(cur + 1)

    def _validate_setup(self) -> bool:
        if not self._setup_page.hidraw_path:
            QMessageBox.warning(self, 'Setup', 'No HID device selected.')
            return False
        if not self._setup_page.model_name:
            QMessageBox.warning(self, 'Setup', 'Enter a model name.')
            return False
        return True

    def _generate_driver(self) -> None:
        model = self._setup_page.model_name
        code  = generate(
            model_name=model,
            product_id=self._setup_page.product_id,
            gkey_count=self._setup_page.gkey_count,
            key_ids=self._mapper_page.mapping,
            layout=self._layout_page.layout_rows,
        )
        self._output_page.set_code(code, model_name=model)

    # ── Key forwarding to the probe ───────────────────────────────────────────

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if self._stack.currentIndex() == 1:
            name = key_event_to_name(event)
            if name:
                self._mapper_page.receive_key(name)
                event.accept()
                return
        super().keyPressEvent(event)
