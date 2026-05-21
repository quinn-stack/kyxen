"""
LightingEngine — daemon thread driving per-key RGB animations.

Holds a single hidraw fd open for the lifetime of the thread.
Config updates arrive via a SimpleQueue; the engine ticks at ~20fps.

  Static:    writes once on config change, idles until next change.
  Preset:    ticks at 20fps, computes frame from elapsed time + formula.
  Animation: ticks at 20fps, interpolates between keyframes.
"""
from __future__ import annotations
import colorsys
import math
import os
import queue
import select
import time
from collections.abc import Callable

from .lighting_config import LightingConfig, Keyframe
from .lighting import KEY_IDS
from .keyboard_layout import LAYOUT as _LAYOUT

_TICK = 0.05   # 20fps

# ── Key positions ─────────────────────────────────────────────────────────────
# Computed from LAYOUT at module load — normalised (x, y) with 0.0=top/left,
# 1.0=bottom/right based on key-centre coordinates. Single source of truth.

def _build_key_positions() -> dict[str, tuple[float, float]]:
    x_min = min(kr.x          for kr in _LAYOUT)
    x_max = max(kr.x + kr.w   for kr in _LAYOUT)
    y_min = min(kr.y          for kr in _LAYOUT)
    y_max = max(kr.y + kr.h   for kr in _LAYOUT)
    x_span = max(x_max - x_min, 0.001)
    y_span = max(y_max - y_min, 0.001)
    return {
        kr.name: (
            (kr.x + kr.w / 2 - x_min) / x_span,
            (kr.y + kr.h / 2 - y_min) / y_span,
        )
        for kr in _LAYOUT
    }

_KEY_POSITIONS: dict[str, tuple[float, float]] = _build_key_positions()


# ── Colour helpers ────────────────────────────────────────────────────────────

def _hex_to_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip('#')
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def _ease(t: float) -> float:
    return t * t * (3 - 2 * t)


def _interp_rgb(
    c1: tuple[int, int, int],
    c2: tuple[int, int, int],
    t: float,
    mode: str,
) -> tuple[int, int, int]:
    if mode == 'instant':
        return c1 if t < 1.0 else c2
    if mode == 'ease':
        t = _ease(t)
    if mode in ('linear', 'ease'):
        return (
            int(_lerp(c1[0], c2[0], t)),
            int(_lerp(c1[1], c2[1], t)),
            int(_lerp(c1[2], c2[2], t)),
        )
    if mode == 'hsv':
        h1, s1, v1 = colorsys.rgb_to_hsv(c1[0] / 255, c1[1] / 255, c1[2] / 255)
        h2, s2, v2 = colorsys.rgb_to_hsv(c2[0] / 255, c2[1] / 255, c2[2] / 255)
        dh = h2 - h1
        if dh > 0.5:
            dh -= 1.0
        elif dh < -0.5:
            dh += 1.0
        r, g, b = colorsys.hsv_to_rgb(
            (h1 + dh * t) % 1.0,
            _lerp(s1, s2, t),
            _lerp(v1, v2, t),
        )
        return int(r * 255), int(g * 255), int(b * 255)
    # fallback linear
    return (
        int(_lerp(c1[0], c2[0], t)),
        int(_lerp(c1[1], c2[1], t)),
        int(_lerp(c1[2], c2[2], t)),
    )


# ── HID++ frame writer ────────────────────────────────────────────────────────

def _write20(fd: int, data: bytes) -> None:
    os.write(fd, data + bytes(max(0, 20 - len(data))))


def _drain(fd: int, timeout: float = 0.15) -> None:
    while True:
        r, _, _ = select.select([fd], [], [], timeout)
        if not r:
            break
        os.read(fd, 64)


def _init(fd: int) -> None:
    _write20(fd, bytes([0x11, 0xff, 0x09, 0x0f]))   # software control
    _drain(fd)
    _write20(fd, bytes([0x11, 0xff, 0x03, 0x2e]))   # software lighting mode
    _drain(fd)


_COMMIT = bytes([0x11, 0xff, 0x10, 0x7e]) + bytes(16)   # 20-byte LONG report

def _write_frame(
    fd: int,
    frame: dict[str, tuple[int, int, int]],
    prev: dict[str, tuple[int, int, int]] | None,
) -> None:
    """Write changed keys batched 3 per packet ([key_id, key_id, r, g, b] × 3), then commit."""
    changed: list[tuple[int, int, int, int]] = []
    for key_name, (r, g, b) in frame.items():
        key_id = KEY_IDS.get(key_name)
        if key_id is None:
            continue
        if prev is not None and prev.get(key_name) == (r, g, b):
            continue
        changed.append((key_id, r, g, b))
    if not changed:
        return
    p = bytearray(20)
    p[0], p[1], p[2], p[3] = 0x11, 0xff, 0x10, 0x5e
    for i in range(0, len(changed), 3):
        p[4:20] = b'\x00' * 16
        for slot, (kid, r, g, b) in enumerate(changed[i:i + 3]):
            off = 4 + slot * 5
            p[off] = p[off + 1] = kid
            p[off + 2], p[off + 3], p[off + 4] = r, g, b
        os.write(fd, bytes(p))
    os.write(fd, _COMMIT)


# ── Frame builders ────────────────────────────────────────────────────────────

def _base_frame(config: LightingConfig) -> dict[str, tuple[int, int, int]]:
    base = _hex_to_rgb(config.base_colour)
    frame = {k: base for k in KEY_IDS}
    for key_name, hex_col in config.key_colours.items():
        if key_name in KEY_IDS:
            frame[key_name] = _hex_to_rgb(hex_col)
    return frame


def _coord_for_key(key_name: str, direction: str) -> float:
    x, y = _KEY_POSITIONS.get(key_name, (0.5, 0.5))
    if direction == 'left_right':  return x
    if direction == 'right_left':  return 1.0 - x
    if direction == 'top_bottom':  return y
    if direction == 'bottom_top':  return 1.0 - y
    # radial from centre
    return min(1.0, math.hypot(x - 0.5, y - 0.5) * 2)


def _build_static(config: LightingConfig) -> dict[str, tuple[int, int, int]]:
    return _base_frame(config)


def _build_breathing(config: LightingConfig, t: float) -> dict[str, tuple[int, int, int]]:
    speed = config.preset.speed  # type: ignore[union-attr]
    brightness = (math.sin(t * math.pi * speed * 0.5) + 1) / 2
    r0, g0, b0 = _hex_to_rgb(config.preset.colours[0])  # type: ignore[union-attr]
    c = (int(r0 * brightness), int(g0 * brightness), int(b0 * brightness))
    return {k: c for k in KEY_IDS}


def _build_wave(config: LightingConfig, t: float) -> dict[str, tuple[int, int, int]]:
    preset = config.preset  # type: ignore[union-attr]
    c1 = _hex_to_rgb(preset.colours[0])
    c2 = _hex_to_rgb(preset.colours[1]) if len(preset.colours) > 1 else (0, 0, 0)
    frame: dict[str, tuple[int, int, int]] = {}
    for key_name in KEY_IDS:
        coord = _coord_for_key(key_name, preset.direction)
        phase = (coord - t * preset.speed * 0.25) % 1.0
        bright = (math.sin(phase * 2 * math.pi) + 1) / 2
        frame[key_name] = (
            int(c1[0] * bright + c2[0] * (1 - bright)),
            int(c1[1] * bright + c2[1] * (1 - bright)),
            int(c1[2] * bright + c2[2] * (1 - bright)),
        )
    return frame


def _build_rainbow_wave(config: LightingConfig, t: float) -> dict[str, tuple[int, int, int]]:
    preset = config.preset  # type: ignore[union-attr]
    frame: dict[str, tuple[int, int, int]] = {}
    for key_name in KEY_IDS:
        coord = _coord_for_key(key_name, preset.direction)
        hue = (coord - t * preset.speed * 0.1) % 1.0
        r, g, b = colorsys.hsv_to_rgb(hue, 1.0, 1.0)
        frame[key_name] = (int(r * 255), int(g * 255), int(b * 255))
    return frame


def _build_colour_cycle(config: LightingConfig, t: float) -> dict[str, tuple[int, int, int]]:
    preset = config.preset  # type: ignore[union-attr]
    hue = (t * preset.speed * 0.05) % 1.0
    r, g, b = colorsys.hsv_to_rgb(hue, 1.0, 1.0)
    c = (int(r * 255), int(g * 255), int(b * 255))
    return {k: c for k in KEY_IDS}


def _resolve_keyframe_state(
    keyframes: list[Keyframe],
    idx: int,
    base: dict[str, tuple[int, int, int]],
) -> dict[str, tuple[int, int, int]]:
    """Full per-key state at keyframe[idx] by merging overrides from frame 0 → idx."""
    state = dict(base)
    for i in range(idx + 1):
        for key_name, hex_col in keyframes[i].key_colours.items():
            if key_name in KEY_IDS:
                state[key_name] = _hex_to_rgb(hex_col)
    return state


def _build_animation(config: LightingConfig, t: float) -> dict[str, tuple[int, int, int]]:
    anim = config.animation  # type: ignore[union-attr]
    if not anim.keyframes:
        return _build_static(config)

    duration = max(anim.duration, anim.keyframes[-1].time if anim.keyframes else 1.0)
    if anim.loop:
        t = t % duration
    else:
        t = min(t, duration)

    keyframes = anim.keyframes
    base = _base_frame(config)

    # Before first keyframe
    if t <= keyframes[0].time:
        return _resolve_keyframe_state(keyframes, 0, base)

    # After last keyframe
    if t >= keyframes[-1].time:
        return _resolve_keyframe_state(keyframes, len(keyframes) - 1, base)

    # Find surrounding keyframes
    for i in range(len(keyframes) - 1):
        kf_a, kf_b = keyframes[i], keyframes[i + 1]
        if kf_a.time <= t <= kf_b.time:
            span = kf_b.time - kf_a.time
            frac = (t - kf_a.time) / span if span > 0 else 1.0
            state_a = _resolve_keyframe_state(keyframes, i,     base)
            state_b = _resolve_keyframe_state(keyframes, i + 1, base)
            return {
                k: _interp_rgb(state_a[k], state_b[k], frac, kf_a.transition)
                for k in KEY_IDS
            }

    return _resolve_keyframe_state(keyframes, len(keyframes) - 1, base)


# ── Engine ────────────────────────────────────────────────────────────────────

class LightingEngine:
    """
    Run in a daemon thread via threading.Thread(target=engine.run, daemon=True).
    Push config changes with set_config(); the thread picks them up on next tick.
    """

    def __init__(self, hidraw_path: str, stop_flag: Callable[[], bool]) -> None:
        self._hidraw_path = hidraw_path
        self._stop_flag   = stop_flag
        self._queue: queue.SimpleQueue[LightingConfig] = queue.SimpleQueue()

    def set_config(self, config: LightingConfig) -> None:
        self._queue.put(config)

    def run(self) -> None:
        # config survives across reconnects so animation resumes after hardware events
        config:  LightingConfig | None = None
        t_start: float                 = time.monotonic()

        while not self._stop_flag():
            try:
                fd = os.open(self._hidraw_path, os.O_RDWR | os.O_NONBLOCK)
            except OSError as e:
                print(f'[lighting] cannot open {self._hidraw_path}: {e}')
                time.sleep(2.0)
                continue

            needs_write = True   # force full redraw on every (re)connect
            prev_frame: dict[str, tuple[int, int, int]] | None = None

            try:
                _init(fd)

                while not self._stop_flag():
                    tick_start = time.monotonic()

                    # Drain queue — keep only the latest config.
                    new_config: LightingConfig | None = None
                    try:
                        while True:
                            new_config = self._queue.get_nowait()
                    except queue.Empty:
                        pass

                    if new_config is not None:
                        config      = new_config
                        needs_write = True
                        prev_frame  = None   # force full write on config change
                        t_start     = time.monotonic()

                    if config is None:
                        time.sleep(_TICK)
                        continue

                    t = time.monotonic() - t_start

                    if config.mode == 'static':
                        if needs_write:
                            frame = _build_static(config)
                            _write_frame(fd, frame, prev_frame)
                            prev_frame  = frame
                            needs_write = False
                        time.sleep(_TICK)

                    elif config.mode == 'preset' and config.preset is not None:
                        name = config.preset.name
                        if name == 'breathing':
                            frame = _build_breathing(config, t)
                        elif name == 'wave':
                            frame = _build_wave(config, t)
                        elif name == 'rainbow_wave':
                            frame = _build_rainbow_wave(config, t)
                        elif name == 'colour_cycle':
                            frame = _build_colour_cycle(config, t)
                        else:
                            frame = _build_static(config)
                        _write_frame(fd, frame, prev_frame)
                        prev_frame = frame
                        elapsed = time.monotonic() - tick_start
                        time.sleep(max(0.0, _TICK - elapsed))

                    elif config.mode == 'animation' and config.animation is not None:
                        frame = _build_animation(config, t)
                        _write_frame(fd, frame, prev_frame)
                        prev_frame = frame
                        elapsed = time.monotonic() - tick_start
                        time.sleep(max(0.0, _TICK - elapsed))

                    else:
                        # Unknown mode — treat as static
                        if needs_write:
                            frame = _build_static(config)
                            _write_frame(fd, frame, prev_frame)
                            prev_frame  = frame
                            needs_write = False
                        time.sleep(_TICK)

            except OSError as e:
                print(f'[lighting] fd error ({e}), reconnecting in 300ms...')
            finally:
                try:
                    os.close(fd)
                except OSError:
                    pass

            if not self._stop_flag():
                time.sleep(0.3)
