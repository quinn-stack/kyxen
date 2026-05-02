"""Keyboard driver registry."""
from __future__ import annotations
from .base import LogitechKeyboard, DevicePaths
from .logitech_g815 import LogitechG815

# Register all supported keyboards here.
# Detection runs in list order — put more specific models first.
ALL_DRIVERS: list[type[LogitechKeyboard]] = [
    LogitechG815,
]


def detect_keyboard() -> LogitechKeyboard | None:
    """Try every registered driver; return the first that finds a device."""
    for driver_cls in ALL_DRIVERS:
        kb = driver_cls.detect()
        if kb is not None:
            print(f'[kyxen] detected: {driver_cls.MODEL_NAME}')
            print(f'[kyxen] evdev:  {kb.paths.evdev}')
            print(f'[kyxen] hidraw: {kb.paths.hidraw or "(not found)"}')
            return kb
    return None
