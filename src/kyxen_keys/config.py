from __future__ import annotations
import os
import pwd
import tomllib
from dataclasses import dataclass, field
from pathlib import Path


def _real_home() -> Path:
    """Return the actual user's home even when running under sudo."""
    sudo_user = os.environ.get('SUDO_USER')
    if sudo_user:
        return Path(pwd.getpwnam(sudo_user).pw_dir)
    return Path.home()


CONFIG_DIR   = _real_home() / '.config' / 'kyxen'
PROFILES_DIR = CONFIG_DIR / 'profiles'

G_KEYS = ('g1', 'g2', 'g3', 'g4', 'g5')


@dataclass
class MacroAction:
    action: str = 'none'   # 'none' | 'type' | 'command'
    text: str   = ''
    cmd: str    = ''

    def to_dict(self) -> dict:
        return {'action': self.action, 'text': self.text, 'cmd': self.cmd}


@dataclass
class Profile:
    name: str
    display_name: str          = ''
    tray_colour: str           = '#00CC44'
    trigger_apps: list[str]    = field(default_factory=list)
    macros: dict[str, MacroAction] = field(default_factory=dict)
    lighting_mode: str         = 'static'
    lighting_colour: str       = '#00CC44'

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
        d['lighting']  = {'mode': self.lighting_mode, 'colour': self.lighting_colour}
        return d


# ── serialisation ─────────────────────────────────────────────────────────────

def _toml_scalar(v) -> str:
    if isinstance(v, bool):   return 'true' if v else 'false'
    if isinstance(v, str):    return f'"{v}"'
    if isinstance(v, list):   return '[' + ', '.join(_toml_scalar(i) for i in v) + ']'
    return str(v)


def _write_toml(path: Path, data: dict) -> None:
    lines = []
    deferred = {}
    for k, v in data.items():
        if isinstance(v, dict):
            deferred[k] = v
        else:
            lines.append(f'{k} = {_toml_scalar(v)}')
    for section, inner in deferred.items():
        lines.append(f'\n[{section}]')
        for dk, dv in inner.items():
            lines.append(f'{dk} = {_toml_scalar(dv)}')
    path.write_text('\n'.join(lines) + '\n', encoding='utf-8')


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
            )
    return Profile(
        name=d.get('name', path.stem),
        display_name=d.get('display_name', d.get('name', path.stem)),
        tray_colour=d.get('tray_colour', '#00CC44'),
        trigger_apps=d.get('triggers', {}).get('apps', []),
        macros=macros,
        lighting_mode=d.get('lighting', {}).get('mode', 'static'),
        lighting_colour=d.get('lighting', {}).get('colour', '#00CC44'),
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
