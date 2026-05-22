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
    loop = true

    [[lighting.animation.slides]]
    hold = 1.0
    transition = "cut"
    transition_duration = 0.5
    [lighting.animation.slides.keys]
    A = "#ff0000"
    SPACE = "#ffffff"
"""
from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class Slide:
    """A single animation slide — full keyboard state plus hold/transition metadata."""
    key_colours: dict[str, str] = field(default_factory=dict)
    hold_duration: float = 0.5
    transition: str = 'cut'             # 'cut'|'fade'|'ease'|'hsv'|'wipe_left'|'wipe_right'|'wipe_top'|'wipe_bottom'|'blink'
    transition_duration: float = 0.5   # ignored for 'cut'

    def to_dict(self) -> dict:
        return {
            'keys':                dict(self.key_colours),
            'hold':                self.hold_duration,
            'transition':          self.transition,
            'transition_duration': self.transition_duration,
        }

    @classmethod
    def from_dict(cls, d: dict) -> 'Slide':
        return cls(
            key_colours=dict(d.get('keys', {})),
            hold_duration=float(d.get('hold', 1.0)),
            transition=str(d.get('transition', 'cut')),
            transition_duration=float(d.get('transition_duration', 0.5)),
        )


@dataclass
class AnimationConfig:
    loop: bool = True
    slides: list[Slide] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            'loop':   self.loop,
            'slides': [s.to_dict() for s in self.slides],
        }

    @classmethod
    def from_dict(cls, d: dict) -> 'AnimationConfig':
        return cls(
            loop=bool(d.get('loop', True)),
            slides=[Slide.from_dict(s) for s in d.get('slides', [])],
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
