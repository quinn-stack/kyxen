"""Install/uninstall the Kyxen GUI as an XDG desktop entry."""
from __future__ import annotations
import os
import shutil
import subprocess
import sys
from importlib import resources
from pathlib import Path

ENTRY_NAME = 'kyxen.desktop'


def _user_apps_dir() -> Path:
    base = os.environ.get('XDG_DATA_HOME') or os.path.expanduser('~/.local/share')
    return Path(base) / 'applications'


def _resolve_exec() -> str:
    """Return the Exec= command for the desktop entry.

    Prefer the installed `kyxen` script, fall back to `<python> -m kyxen_keys.gui.app`.
    """
    path = shutil.which('kyxen')
    if path:
        return path
    return f'{sys.executable} -m kyxen_keys.gui.app'


def _load_template() -> str:
    return resources.files('kyxen_keys._assets').joinpath(ENTRY_NAME).read_text()


def _render_entry() -> str:
    return _load_template().replace('__EXEC__', _resolve_exec())


def _update_database(apps_dir: Path) -> None:
    if shutil.which('update-desktop-database') is None:
        return
    subprocess.run(['update-desktop-database', str(apps_dir)], check=False)


def install() -> int:
    target_dir = _user_apps_dir()
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / ENTRY_NAME
    target.write_text(_render_entry())
    target.chmod(0o644)
    print(f'[kyxen] wrote {target}')
    _update_database(target_dir)
    return 0


def uninstall() -> int:
    target_dir = _user_apps_dir()
    target = target_dir / ENTRY_NAME
    if target.exists():
        target.unlink()
        print(f'[kyxen] removed {target}')
        _update_database(target_dir)
    else:
        print(f'[kyxen] no desktop entry at {target}')
    return 0


def print_entry() -> int:
    sys.stdout.write(_render_entry())
    return 0
