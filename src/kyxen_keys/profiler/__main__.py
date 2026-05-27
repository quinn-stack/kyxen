import sys
from PySide6.QtWidgets import QApplication
from .profiler_window import ProfilerWindow


def main() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName('Kyxen Profiler')
    app.setApplicationDisplayName('Kyxen Profiler')
    w = ProfilerWindow()
    w.show()
    sys.exit(app.exec())


if __name__ == '__main__':
    main()
