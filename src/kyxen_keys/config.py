from __future__ import annotations
import os
import pwd
import tomllib
import tomli_w
from dataclasses import dataclass, field
from pathlib import Path

from .lighting_config import LightingConfig


def _real_home() -> Path:
    """Return the actual user's home even when running under sudo."""
    sudo_user = os.environ.get('SUDO_USER')
    if sudo_user:
        return Path(pwd.getpwnam(sudo_user).pw_dir)
    return Path.home()


CONFIG_DIR   = _real_home() / '.config' / 'kyxen'
PROFILES_DIR = CONFIG_DIR / 'profiles'
DRIVERS_DIR  = CONFIG_DIR / 'drivers'

G_KEYS = tuple(f'g{i}' for i in range(1, 19))


@dataclass
class MacroAction:
    action:      str       = 'none'  # 'none'|'type'|'command'|'combo'|'hold_toggle'|'mouse_button'
    text:        str       = ''
    cmd:         str       = ''
    keys:        list[str] = field(default_factory=list)
    mouse_btn:   str       = 'left'   # 'left'|'right'|'middle'|'button4'|'button5'
    mouse_mode:  str       = 'click'  # 'click'|'double_click'|'hold'
    repeat:      bool      = False
    repeat_rate: float     = 100.0   # interval in milliseconds

    def to_dict(self) -> dict:
        return {
            'action': self.action, 'text': self.text, 'cmd': self.cmd, 'keys': self.keys,
            'mouse_btn': self.mouse_btn, 'mouse_mode': self.mouse_mode,
            'repeat': self.repeat, 'repeat_rate': self.repeat_rate,
        }


@dataclass
class Profile:
    name: str
    display_name: str          = ''
    tray_colour: str           = '#00CC44'
    trigger_apps: list[str]    = field(default_factory=list)
    macros: dict[str, MacroAction] = field(default_factory=dict)
    lighting: LightingConfig   = field(default_factory=LightingConfig)

    def __post_init__(self):
        if not self.display_name:
            self.display_name = self.name
        for k in G_KEYS:
            if k not in self.macros:
                self.macros[k] = MacroAction()

    def to_dict(self) -> dict:
        d: dict = {
            'name':         self.name,
            'display_name': self.display_name,
            'tray_colour':  self.tray_colour,
        }
        for k in G_KEYS:
            d[k] = self.macros[k].to_dict()
        d['triggers'] = {'apps': self.trigger_apps}
        d['lighting'] = self.lighting.to_dict()
        return d


# ── serialisation ─────────────────────────────────────────────────────────────

def _write_toml(path: Path, data: dict) -> None:
    with open(path, 'wb') as f:
        tomli_w.dump(data, f)


# ── profile I/O ───────────────────────────────────────────────────────────────

def load_profile(path: Path) -> Profile:
    with open(path, 'rb') as f:
        d = tomllib.load(f)
    macros = {}
    for k in G_KEYS:
        if k in d:
            macros[k] = MacroAction(
                action=d[k].get('action', 'none'),
                text=d[k].get('text', ''),
                cmd=d[k].get('cmd', ''),
                keys=d[k].get('keys', []),
                mouse_btn=d[k].get('mouse_btn', 'left'),
                mouse_mode=d[k].get('mouse_mode', 'click'),
                repeat=d[k].get('repeat', False),
                repeat_rate=float(d[k].get('repeat_rate', 100.0)),
            )
    return Profile(
        name=d.get('name', path.stem),
        display_name=d.get('display_name', d.get('name', path.stem)),
        tray_colour=d.get('tray_colour', '#00CC44'),
        trigger_apps=d.get('triggers', {}).get('apps', []),
        macros=macros,
        lighting=LightingConfig.from_dict(d.get('lighting', {})),
    )


def save_profile(profile: Profile) -> None:
    PROFILES_DIR.mkdir(parents=True, exist_ok=True)
    _write_toml(PROFILES_DIR / f'{profile.name}.toml', profile.to_dict())


def delete_profile(name: str) -> None:
    path = PROFILES_DIR / f'{name}.toml'
    if path.exists():
        path.unlink()


def list_profiles() -> list[Profile]:
    if not PROFILES_DIR.exists():
        return []
    profiles = []
    for p in sorted(PROFILES_DIR.glob('*.toml')):
        try:
            profiles.append(load_profile(p))
        except Exception:
            pass
    return profiles


# ── global config ─────────────────────────────────────────────────────────────

def load_global_config() -> dict:
    cf = CONFIG_DIR / 'config.toml'
    if not cf.exists():
        return {'active_profile': 'default', 'profile_slots': {}}
    with open(cf, 'rb') as f:
        return tomllib.load(f)


def save_global_config(cfg: dict) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    _write_toml(CONFIG_DIR / 'config.toml', cfg)


def ensure_default_profile() -> Profile:
    PROFILES_DIR.mkdir(parents=True, exist_ok=True)
    path = PROFILES_DIR / 'default.toml'
    if not path.exists():
        p = Profile(name='default', display_name='Default')
        save_profile(p)
        return p
    return load_profile(path)
