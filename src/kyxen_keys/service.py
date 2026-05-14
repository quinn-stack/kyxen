"""Install/uninstall the Kyxen daemon as a systemd user service."""
from __future__ import annotations
import os
import shutil
import subprocess
import sys
from importlib import resources
from pathlib import Path

UNIT_NAME = 'kyxen.service'


def _user_unit_dir() -> Path:
    base = os.environ.get('XDG_CONFIG_HOME') or os.path.expanduser('~/.config')
    return Path(base) / 'systemd' / 'user'


def _resolve_exec_start() -> str:
    """Return the command systemd should run to launch the daemon.

    Prefer the installed `kyxen-daemon` script (absolute path), so the unit
    works even if PATH differs in the user-systemd environment. Fall back to
    `<python> -m kyxen_keys` when the script can't be located.
    """
    path = shutil.which('kyxen-daemon')
    if path:
        return path
    return f'{sys.executable} -m kyxen_keys'


def _load_template() -> str:
    return resources.files('kyxen_keys._assets').joinpath(UNIT_NAME).read_text()


def _render_unit() -> str:
    return _load_template().replace('__EXEC_START__', _resolve_exec_start())


def _systemctl(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(['systemctl', '--user', *args], check=check)


def install(enable: bool = True, start: bool = True) -> int:
    target_dir = _user_unit_dir()
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / UNIT_NAME
    target.write_text(_render_unit())
    print(f'[kyxen] wrote {target}')

    try:
        _systemctl('daemon-reload')
    except FileNotFoundError:
        print('[kyxen] systemctl not found — unit file installed, but not loaded')
        return 1

    if enable:
        flags = ['enable']
        if start:
            flags.append('--now')
        flags.append(UNIT_NAME)
        _systemctl(*flags)
        print(f'[kyxen] systemd user service {"enabled and started" if start else "enabled"}')
    elif start:
        _systemctl('start', UNIT_NAME)
        print('[kyxen] systemd user service started')
    else:
        print('[kyxen] unit installed; run `systemctl --user enable --now kyxen` to activate')
    return 0


def uninstall() -> int:
    try:
        _systemctl('disable', '--now', UNIT_NAME, check=False)
    except FileNotFoundError:
        pass
    target = _user_unit_dir() / UNIT_NAME
    if target.exists():
        target.unlink()
        print(f'[kyxen] removed {target}')
    else:
        print(f'[kyxen] no unit file at {target}')
    try:
        _systemctl('daemon-reload', check=False)
    except FileNotFoundError:
        pass
    return 0


def print_unit() -> int:
    sys.stdout.write(_render_unit())
    return 0
