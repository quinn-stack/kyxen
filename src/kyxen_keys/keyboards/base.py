"""Abstract base class for all supported Logitech keyboard drivers."""
from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import ClassVar


@dataclass
class DevicePaths:
    evdev:        str   # /dev/input/eventX — G-key evdev interface (grabbed for suppression)
    hidraw:       str   # /dev/hidrawX      — HID++ lighting/control interface
    hidraw_gkeys: str = ''  # /dev/hidrawY  — G-key boot-protocol interface (may differ from hidraw)


class LogitechKeyboard(ABC):
    """
    Base driver for a supported Logitech keyboard model.

    To add a new keyboard, subclass this, fill in the class variables,
    implement apply_lighting(), then register in keyboards/__init__.py ALL_DRIVERS.
    """

    VENDOR_ID:   ClassVar[int]       = 0x046D
    PRODUCT_IDS: ClassVar[list[int]] = []
    MODEL_NAME:  ClassVar[str]       = ''
    GKEY_COUNT:  ClassVar[int]       = 0

    # HID++ 2.0 feature index for GKEYS on this model (None = no HID++ G-key support).
    GKEYS_FEATURE_IDX: ClassVar[int | None] = None

    # Evdev codes emitted by the G-key interface that must be suppressed.
    # The daemon grabs the interface and drops these so they never reach apps.
    GKEY_SUPPRESS_CODES: ClassVar[frozenset[int]] = frozenset()

    def __init__(self, paths: DevicePaths) -> None:
        self.paths = paths

    # ── required overrides ────────────────────────────────────────────────────

    @abstractmethod
    def apply_lighting(self, mode: str, colour: str, active_mkey: int | None = None) -> None:
        """Push a lighting state to the keyboard (mode: 'static'|'breathing'|'wave'|'off').
        active_mkey: 0-indexed M-key to highlight (0=M1, 1=M2, 2=M3), or None."""
        ...

    # ── detection helpers (override _is_gkey_interface if needed) ────────────

    @classmethod
    def detect(cls) -> 'LogitechKeyboard | None':
        """Auto-detect this keyboard model; return a driver instance or None."""
        from .detect import find_evdev, find_hidraw
        evdev_path  = find_evdev(cls.VENDOR_ID, cls.PRODUCT_IDS, cls._is_gkey_interface)
        hidraw_path = find_hidraw(cls.VENDOR_ID, cls.PRODUCT_IDS)
        if evdev_path is None:
            return None
        return cls(DevicePaths(evdev=evdev_path, hidraw=hidraw_path or ''))

    @classmethod
    def _is_gkey_interface(cls, device) -> bool:
        """
        Return True if this evdev device is the G-key interface (not the main
        keyboard or mouse interface). Override per-model if needed.
        """
        name = device.name
        return not any(name.endswith(s) for s in
                       (' Keyboard', ' Mouse', ' Consumer Control', ' System Control'))
