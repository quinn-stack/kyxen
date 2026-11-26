"""Keyboard driver registry."""
from __future__ import annotations
from .base import LogitechKeyboard, DevicePaths
from .logitech_g815 import LogitechG815
from .logitech_g15 import LogitechG15

# Built-in drivers — detection runs in list order, more specific models first.
ALL_DRIVERS: list[type[LogitechKeyboard]] = [
    LogitechG815,
    LogitechG15,
]


def detect_keyboard() -> LogitechKeyboard | None:
    """
    Try every registered driver (user drivers first, then built-ins).
    Returns the first that successfully detects a device, or None.
    """
    from .user_drivers import load_user_drivers
    drivers = load_user_drivers() + ALL_DRIVERS

    for driver_cls in drivers:
        kb = driver_cls.detect()
        if kb is not None:
            print(f'[kyxen] detected: {driver_cls.MODEL_NAME}')
            print(f'[kyxen] evdev:    {kb.paths.evdev}')
            print(f'[kyxen] hidraw:   {kb.paths.hidraw or "(not found)"}')
            return kb
    return None
