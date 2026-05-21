# Kyxen

Open-source Logitech G-key macro manager for Linux.

Gives you per-profile macros on your G-keys — type text, run commands, fire key
combos, hold modifier keys, click mouse buttons, or repeat any action while the
key is held. RGB lighting is set per-profile. No Windows software, no cloud
account, no proprietary drivers required.

## Supported keyboards

| Model | G-keys | M-key profile switching | Lighting |
|-------|--------|------------------------|---------|
| Logitech G815 | G1–G5 | ✅ M1–M3 | ✅ Per-key RGB editor — static, presets (breathing/wave/rainbow wave/colour cycle), custom keyframe animations |

More models coming. PRs welcome — see [Adding keyboard support](#adding-keyboard-support).

## Requirements

- Linux (kernel ≥ 5.4)
- Python ≥ 3.11
- `python-evdev`
- `PySide6`
- User must be in the `input` group (most desktop distros already do this)

## Installation

### From source (recommended for now)

```bash
git clone https://github.com/quinn-stack/kyxen
cd kyxen
pip install -e .
```

### Arch / CachyOS

```bash
# Dependencies
sudo pacman -S python-evdev python-pyside6

# Clone and install
git clone https://github.com/quinn-stack/kyxen
cd kyxen
pip install --no-deps -e .
```

## Usage

### Start the daemon

```bash
kyxen-daemon
# or during development:
python3 kyxend.py
```

### Open the GUI

```bash
kyxen
# or during development:
python3 kyxen-gui.py
```

The GUI lives in your system tray. Click the tray icon to configure profiles
and macros.

### Auto-start with your session

Kyxen runs as a **systemd user service** — no root, no system-wide unit. One
command registers and starts it:

```bash
kyxen-daemon install-service
```

This writes `~/.config/systemd/user/kyxen.service`, reloads the user manager,
and runs `systemctl --user enable --now kyxen`. To uninstall:

```bash
kyxen-daemon uninstall-service
```

Useful flags: `--no-start` (install + enable without starting now),
`--no-enable` (install only, don't enable). To inspect the unit before
installing, run `kyxen-daemon print-service`.

### Show in your app launcher

```bash
kyxen-daemon install-desktop
```

Writes `~/.local/share/applications/kyxen.desktop` so Kyxen appears in your
desktop environment's app launcher. Remove with
`kyxen-daemon uninstall-desktop`, preview with `kyxen-daemon print-desktop`.

## Macro types

| Type | Description |
|------|-------------|
| **Type text** | Injects a string as keystrokes |
| **Run command** | Runs a shell command in the background |
| **Key combo** | Presses a set of keys simultaneously (e.g. Ctrl+Alt+T) |
| **Hold toggle** | First press holds keys down; second press releases them |
| **Mouse button** | Click, double-click, or hold-toggle a mouse button |

All types except Hold toggle support **Repeat while held** — the action fires
repeatedly at a configurable interval (10–5000 ms) for as long as the G-key is
held down.

## Permissions

Kyxen needs read/write access to `/dev/input/event*` (G-key interface) and
`/dev/uinput` (for injecting keystrokes and mouse events).

On most desktop Linux systems the active session user already has these via
`logind` ACLs. If not:

```bash
# input group covers /dev/input/*
sudo usermod -aG input $USER

# uinput group for text injection
sudo groupadd -f uinput
sudo usermod -aG uinput $USER
echo 'KERNEL=="uinput", GROUP="uinput", MODE="0660"' \
  | sudo tee /etc/udev/rules.d/99-uinput.rules
sudo udevadm control --reload-rules && sudo udevadm trigger
# Log out and back in
```

## Configuration

### Global config — `~/.config/kyxen/config.toml`

Controls the active profile and which Kyxen profile each M-key activates:

```toml
active_profile = "default"

[profile_slots]
m1 = "default"
m2 = "gaming"
m3 = "work"
```

If a slot is not set, pressing that M-key logs a warning and does nothing. Profile
names must match a `.toml` file in `~/.config/kyxen/profiles/`.

### Profiles — `~/.config/kyxen/profiles/<name>.toml`

Profiles are stored as plain TOML files. You can edit them by hand or use the GUI.

```toml
name = "default"
display_name = "Default"
tray_colour = "#00CC44"

[g1]
action = "combo"
keys = ["ctrl", "alt", "t"]

[g2]
action = "mouse_button"
mouse_btn = "left"
mouse_mode = "click"
repeat = true
repeat_rate = 50

[g3]
action = "type"
text = "Hello from G3!"

[g4]
action = "command"
cmd = "notify-send 'Kyxen' 'G4 pressed'"

[g5]
action = "none"

[lighting]
mode = "static"
base_colour = "#00CC44"
# Optional per-key overrides (static mode):
# [lighting.keys]
# A = "#ff0000"
# SPACE = "#0000ff"
```

## Lighting

Lighting is configured per profile and applied immediately when the active profile changes. The GUI provides an interactive per-key editor — click the **Lighting…** button on any profile.

### Modes

| Mode | Description |
|------|-------------|
| **Static** | All keys lit at `base_colour`. Optional per-key overrides in `[lighting.keys]`. |
| **Preset** | Built-in animated effects streamed from the daemon. |
| **Animation** | Custom keyframe animation built in the GUI editor. |

### Preset effects

| Preset | Description |
|--------|-------------|
| `breathing` | Pulse brightness up/down. Multiple colours cycle through. |
| `wave` | Colour washes across the keyboard. Supports `left_right`, `right_left`, `top_bottom`, `bottom_top`. |
| `rainbow_wave` | Full-spectrum rainbow travels across the keyboard. |
| `colour_cycle` | All keys cycle through colours in unison. |

All presets have a `speed` parameter (0.1 = slow, 5.0 = fast, default 1.0).

### TOML examples

```toml
# Breathing preset
[lighting]
mode = "preset"
base_colour = "#00CC44"

[lighting.preset]
name = "breathing"
colours = ["#ff0000", "#0000ff"]
speed = 1.5
```

```toml
# Rainbow wave
[lighting]
mode = "preset"
base_colour = "#000000"

[lighting.preset]
name = "rainbow_wave"
direction = "left_right"
speed = 1.0
```

## Developer tools

Several scripts in the repo root are useful when reverse-engineering a new keyboard
or debugging the HID++ protocol. Stop `kyxen-daemon` before running any of them.

| Script | Purpose |
|--------|---------|
| `probe_mkeys.py` | Physical key-press mapper — press each key in turn and it records the HID++ key ID. Used to build `g815_keymap.json`. |
| `probe_lighting.py` | Lighting protocol validator — tests both confirmed HID++ approaches (GHub/Wireshark and direct-mode) against each hidraw interface, asks you to confirm keys light up correctly. |
| `probe_gkeys.py` | G-key discovery — enables software mode on the HID++ interface and listens on both hidraw interfaces simultaneously so you can see the raw G-key events. |
| `probe_rgb_effects2.py` | HID++ feature 0x8071 (RGBEffects) and 0x8081 (PerKeyLightingV2) capability probe. Confirms which autonomous effect features are available and tests batch per-key writes. |
| `probe_batch_write.py` | Batch per-key write performance test. Validates that 3-key-per-packet batching works and measures packet throughput. |
| `probe_onboard.py` | Onboard profile sector probe — reads raw profile sectors via feature 0x8100 to understand what the keyboard stores on-device. |
| `sniff_hidraw.py` | Raw HID++ packet sniffer — dumps everything coming off a hidraw device. Useful for watching what G Hub sends. |

`g815_keymap.json` is the ground-truth key ID map for the G815, built from a
`probe_mkeys.py` session and confirmed correct. It is the canonical source for
key IDs in `lighting_engine.py`.

## Adding keyboard support

1. Create `src/kyxen_keys/keyboards/logitech_<model>.py`
2. Subclass `LogitechKeyboard`, fill in `PRODUCT_IDS`, `MODEL_NAME`, `GKEY_COUNT`
3. Implement `gkey_map()` (evdev keycode → 'gN' mapping)
4. Implement `apply_lighting()` (call into `lighting.py` or add model-specific code)
5. Register in `src/kyxen_keys/keyboards/__init__.py` `ALL_DRIVERS`
6. Open a PR

The USB product ID is in `lsusb` output. Use `probe_mkeys.py` to map G-key HID
codes and `probe_lighting.py` to validate lighting commands on a new model.

## A Note on AI Assistance

This project was heavily assisted by AI (Claude, by Anthropic) throughout its development — from architecture decisions and code review to debugging and documentation. That assistance is acknowledged openly and without hesitation.

The domain knowledge, real-world requirements, design decisions, and direction are entirely human. The AI was a tool, and a valuable one. The project would not have reached this point without it.

This feels worth stating plainly in an era where AI assistance is sometimes hidden or considered something to be embarrassed about. It isn't.

## Licence

GNU General Public License v3.0 or later — see [LICENSE](LICENSE).
