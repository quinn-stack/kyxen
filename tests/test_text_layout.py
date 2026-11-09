"""Tests for text-macro keyboard layouts.

The xkbcommon cross-check runs only where ``xkbcli`` is installed (it ships
with libxkbcommon). It asks xkbcommon how each character is typed on the real
layout and compares that with Kyxen's table, so layout bugs show up as test
failures instead of wrong characters in a game chat.
"""
from __future__ import annotations
import re
import shutil
import subprocess

import pytest
from evdev import ecodes

from kyxen_keys import text_layout
from kyxen_keys.text_layout import ALTGR, SHIFT, build_layout, parse_localectl
from kyxen_keys.macro import text_to_key_events

XKB_EVDEV_OFFSET = 8   # xkb keycode = evdev keycode + 8

_DEAD_KEYSYMS = {'^': 'dead_circumflex', '´': 'dead_acute', '`': 'dead_grave'}


def _xkb_ways(layout: str, variant: str, what: str, keysym: bool = False) -> set[tuple[int, int]]:
    """Return every (evdev keycode, mods) xkbcommon offers for a char/keysym."""
    cmd = ['xkbcli', 'how-to-type', '--layout', layout]
    if variant:
        cmd += ['--variant', variant]
    if keysym:
        cmd.append('--keysym')
    out = subprocess.run(cmd + [what], capture_output=True, text=True, check=True).stdout
    ways: set[tuple[int, int]] = set()
    direct = out.split('=== Access via Compose', 1)[0]
    for line in direct.splitlines():
        m = re.match(r'\s*(\d+)\s+\S+\s+1\s+.*\[(.*)\]\s*$', line)
        if not m:
            continue
        mods_txt = m.group(2).split()
        if 'Lock' in mods_txt:          # Caps Lock alternatives are irrelevant
            continue
        mods = 0
        if 'Shift' in mods_txt:
            mods |= SHIFT
        if 'Mod5' in mods_txt or 'LevelThree' in mods_txt:
            mods |= ALTGR
        ways.add((int(m.group(1)) - XKB_EVDEV_OFFSET, mods))
    return ways


@pytest.mark.skipif(shutil.which('xkbcli') is None, reason='xkbcli (libxkbcommon) not installed')
@pytest.mark.parametrize('layout,variant', [
    ('us', ''), ('gb', ''), ('de', ''), ('at', ''), ('de', 'nodeadkeys'), ('at', 'nodeadkeys'),
])
def test_layout_matches_xkbcommon(layout: str, variant: str) -> None:
    tl = build_layout(layout, variant)
    mismatches = []
    for ch, (code, mods) in sorted(tl.chars.items()):
        if ch in ('\n', '\t'):
            continue
        if tl.needs_space_after(ch):
            ways = _xkb_ways(layout, variant, _DEAD_KEYSYMS[ch], keysym=True)
        else:
            ways = _xkb_ways(layout, variant, ch)
        if (code, mods) not in ways:
            mismatches.append(f'{ch!r}: kyxen={(code, mods)} xkb={sorted(ways)}')
    assert not mismatches, '\n'.join(mismatches)


def test_austrian_maps_to_german() -> None:
    at = build_layout('at')
    assert at.lookup('z') == (ecodes.KEY_Y, 0)
    assert at.lookup('y') == (ecodes.KEY_Z, 0)
    assert at.lookup('@') == (ecodes.KEY_Q, ALTGR)
    assert at.lookup('ä') == (ecodes.KEY_APOSTROPHE, 0)
    assert at.lookup('?') == (ecodes.KEY_MINUS, SHIFT)


def test_unknown_layout_falls_back_to_us() -> None:
    assert build_layout('xx').name == 'us'


def test_dead_keys_get_space() -> None:
    events, skipped = text_to_key_events('^', build_layout('de'))
    assert skipped == []
    assert events == [
        (ecodes.KEY_GRAVE, 1), (ecodes.KEY_GRAVE, 0),
        (ecodes.KEY_SPACE, 1), (ecodes.KEY_SPACE, 0),
    ]
    events, _ = text_to_key_events('^', build_layout('de', 'nodeadkeys'))
    assert events == [(ecodes.KEY_GRAVE, 1), (ecodes.KEY_GRAVE, 0)]


def test_altgr_and_shift_wrap_the_key() -> None:
    events, _ = text_to_key_events('@A', build_layout('at'))
    assert events == [
        (ecodes.KEY_RIGHTALT, 1), (ecodes.KEY_Q, 1), (ecodes.KEY_Q, 0), (ecodes.KEY_RIGHTALT, 0),
        (ecodes.KEY_LEFTSHIFT, 1), (ecodes.KEY_A, 1), (ecodes.KEY_A, 0), (ecodes.KEY_LEFTSHIFT, 0),
    ]


def test_unmapped_chars_are_reported() -> None:
    _, skipped = text_to_key_events('a☃b', build_layout('us'))
    assert skipped == ['☃']


def test_parse_localectl() -> None:
    out = (
        '   System Locale: LANG=de_AT.UTF-8\n'
        '       VC Keymap: de-latin1\n'
        '      X11 Layout: at,us\n'
        '       X11 Model: pc105\n'
        '     X11 Variant: nodeadkeys,\n'
    )
    assert parse_localectl(out) == ('at', 'nodeadkeys')


def test_config_override_wins(monkeypatch) -> None:
    from kyxen_keys import config as cfg
    monkeypatch.setattr(cfg, 'load_global_config',
                        lambda: {'keyboard_layout': 'de', 'keyboard_variant': 'nodeadkeys'})
    assert text_layout.detect_layout() == ('de', 'nodeadkeys')


def test_combo_letters_follow_layout(monkeypatch) -> None:
    from kyxen_keys import macro
    monkeypatch.setattr(macro, '_layout', build_layout('at'))
    # ctrl+z must press the key that types "z" on QWERTZ (physical Y position)
    assert macro._resolve_keys(['ctrl', 'z']) == [ecodes.KEY_LEFTCTRL, ecodes.KEY_Y]
    # "[" needs AltGr on QWERTZ, so it keeps its US position
    assert macro._resolve_keys(['[']) == [ecodes.KEY_LEFTBRACE]
