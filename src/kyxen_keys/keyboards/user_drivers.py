"""
user_drivers — dynamically loads keyboard drivers from ~/.config/kyxen/drivers/.

Any .py file dropped in that directory is imported at daemon startup.
Any LogitechKeyboard subclass with at least one PRODUCT_ID is registered.

This lets users install drivers created by kyxen-profiler without editing
the package source or using Git.
"""
from __future__ import annotations
import importlib.util
import sys
from pathlib import Path

from .base import LogitechKeyboard
from .. import config as cfg


def load_user_drivers() -> list[type[LogitechKeyboard]]:
    """
    Scan DRIVERS_DIR for .py files and return all LogitechKeyboard subclasses found.
    Errors in individual files are logged and skipped — a bad driver file won't
    prevent other drivers or the daemon from loading.
    """
    drivers_dir = cfg.DRIVERS_DIR
    if not drivers_dir.exists():
        return []

    result: list[type[LogitechKeyboard]] = []

    for path in sorted(drivers_dir.glob('*.py')):
        try:
            module_name = f'kyxen_user_driver_{path.stem}'

            # Don't re-import if already loaded (e.g. after a reload_drivers call)
            if module_name in sys.modules:
                module = sys.modules[module_name]
            else:
                spec = importlib.util.spec_from_file_location(module_name, path)
                if spec is None or spec.loader is None:
                    print(f'[kyxen] WARNING: could not load driver file {path.name}')
                    continue
                module = importlib.util.module_from_spec(spec)
                sys.modules[module_name] = module
                spec.loader.exec_module(module)  # type: ignore[union-attr]

            for attr_name in dir(module):
                attr = getattr(module, attr_name, None)
                if (
                    isinstance(attr, type)
                    and issubclass(attr, LogitechKeyboard)
                    and attr is not LogitechKeyboard
                    and bool(attr.PRODUCT_IDS)
                ):
                    result.append(attr)
                    print(f'[kyxen] user driver: {attr.MODEL_NAME}  ({path.name})')

        except Exception as e:
            print(f'[kyxen] WARNING: failed to load user driver {path.name}: {e}')

    return result
