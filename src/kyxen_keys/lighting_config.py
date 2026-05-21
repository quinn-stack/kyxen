"""
Lighting configuration data model.

Key names throughout use the KEY_IDS naming convention from lighting.py:
uppercase letters (A, B, ...), uppercase specials (SPACE, L_SHIFT, F1, NUM_0, etc.).

TOML structure inside a profile file:

    [lighting]
    mode = "static"          # "static" | "preset" | "animation"
    base_colour = "#00CC44"

    [lighting.keys]          # per-key overrides (static mode only)
    A = "#ff0000"
    SPACE = "#ffffff"

    [lighting.preset]        # present when mode = "preset"
    name = "breathing"
    colours = ["#00CC44"]
    speed = 1.0
    direction = "left_right"

    [lighting.animation]     # present when mode = "animation"
    duration = 4.0
    loop = true

    [[lighting.animation.keyframes]]
    time = 0.0
    transition = "linear"
    keys = {A = "#ff0000", SPACE = "#ffffff"}

Backwards compatible: old profiles with [lighting] mode/colour keys load fine.
"""
from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class Keyframe:
    time: float
    key_colours: dict[str, str] = field(default_factory=dict)
    transition: str = 'linear'  # 'instant' | 'linear' | 'ease' | 'hsv'

    def to_dict(self) -> dict:
        return {
            'time':       self.time,
            'keys':       dict(self.key_colours),
            'transition': self.transition,
        }

    @classmethod
    def from_dict(cls, d: dict) -> 'Keyframe':
        return cls(
            time=float(d.get('time', 0.0)),
            key_colours=dict(d.get('keys', {})),
            transition=str(d.get('transition', 'linear')),
        )


@dataclass
class AnimationConfig:
    duration: float = 2.0
    loop: bool = True
    keyframes: list[Keyframe] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            'duration':  self.duration,
            'loop':      self.loop,
            'keyframes': [kf.to_dict() for kf in self.keyframes],
        }

    @classmethod
    def from_dict(cls, d: dict) -> 'AnimationConfig':
        return cls(
            duration=float(d.get('duration', 2.0)),
            loop=bool(d.get('loop', True)),
            keyframes=[Keyframe.from_dict(kf) for kf in d.get('keyframes', [])],
        )


@dataclass
class PresetConfig:
    name: str = 'breathing'          # 'breathing'|'wave'|'rainbow_wave'|'colour_cycle'
    colours: list[str] = field(default_factory=lambda: ['#00CC44'])
    speed: float = 1.0               # 0.1 (slow) → 5.0 (fast)
    direction: str = 'left_right'    # 'left_right'|'right_left'|'top_bottom'|'bottom_top'|'radial'

    def to_dict(self) -> dict:
        return {
            'name':      self.name,
            'colours':   list(self.colours),
            'speed':     self.speed,
            'direction': self.direction,
        }

    @classmethod
    def from_dict(cls, d: dict) -> 'PresetConfig':
        return cls(
            name=str(d.get('name', 'breathing')),
            colours=list(d.get('colours', ['#00CC44'])),
            speed=float(d.get('speed', 1.0)),
            direction=str(d.get('direction', 'left_right')),
        )


@dataclass
class LightingConfig:
    mode: str = 'static'             # 'static' | 'preset' | 'animation'
    base_colour: str = '#00CC44'
    key_colours: dict[str, str] = field(default_factory=dict)  # per-key overrides (static mode)
    preset: PresetConfig | None = None
    animation: AnimationConfig | None = None

    def to_dict(self) -> dict:
        d: dict = {
            'mode':         self.mode,
            'base_colour':  self.base_colour,
        }
        if self.key_colours:
            d['keys'] = dict(self.key_colours)
        if self.preset is not None:
            d['preset'] = self.preset.to_dict()
        if self.animation is not None:
            d['animation'] = self.animation.to_dict()
        return d

    @classmethod
    def from_dict(cls, d: dict) -> 'LightingConfig':
        # Backwards compat: old profiles stored {mode, colour} instead of {mode, base_colour}
        base = str(d.get('base_colour') or d.get('colour') or '#00CC44')
        preset = PresetConfig.from_dict(d['preset']) if 'preset' in d else None
        animation = AnimationConfig.from_dict(d['animation']) if 'animation' in d else None
        return cls(
            mode=str(d.get('mode', 'static')),
            base_colour=base,
            key_colours=dict(d.get('keys', {})),
            preset=preset,
            animation=animation,
        )

    @classmethod
    def default(cls, colour: str = '#00CC44') -> 'LightingConfig':
        return cls(mode='static', base_colour=colour)
