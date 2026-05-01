# OpenLogiKey

Open-source Logitech G-key macro manager for Linux.

Gives you per-profile macros, native Wayland text injection, automatic profile
switching based on the focused application, and RGB lighting control — with no
Windows software, no cloud account, and no proprietary drivers required.

## Supported keyboards

| Model | G-keys | Lighting |
|-------|--------|---------|
| Logitech G815 | G1–G5 | ✅ Zone effects |

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
git clone https://github.com/quinn-stack/openlogikey
cd openlogikey
pip install -e .
```

### Arch / CachyOS

```bash
# Dependencies
sudo pacman -S python-evdev python-pyside6

# Clone and install
git clone https://github.com/quinn-stack/openlogikey
cd openlogikey
pip install --no-deps -e .
```

## Usage

### Start the daemon

```bash
openlogikey-daemon
# or during development:
python3 -m openlogikey
```

### Open the GUI

```bash
openlogikey
# or:
python3 -m openlogikey.gui
```

The GUI lives in your system tray. Click it to configure profiles and macros.

### Auto-start with your session

```bash
systemctl --user enable --now openlogikey-daemon
```

## Permissions

OpenLogiKey needs read/write access to `/dev/input/event*` (G-key interface)
and `/dev/uinput` (for injecting typed text).

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

Profiles are stored in `~/.config/openlogikey/profiles/` as plain TOML files.
You can edit them by hand or use the GUI.

```toml
name = "DJ Set"
display_name = "DJ Set"
tray_colour = "#FF6600"
lighting_mode = "static"
lighting_colour = "#FF6600"

[g1]
action = "type"
text = "cue point note"

[g2]
action = "command"
cmd = "/home/wade/scripts/bpm-tap.sh"

[g3]
action = "none"

[triggers]
apps = ["mixxx", "rekordbox"]
```

## Adding keyboard support

1. Create `src/openlogikey/keyboards/logitech_<model>.py`
2. Subclass `LogitechKeyboard`, fill in `PRODUCT_IDS`, `MODEL_NAME`, `GKEY_COUNT`
3. Implement `gkey_map()` (evdev keycode → 'gN' mapping)
4. Implement `apply_lighting()` (call into `lighting.py` or add model-specific code)
5. Register in `src/openlogikey/keyboards/__init__.py` `ALL_DRIVERS`
6. Open a PR

The USB product ID is in `lsusb` output. The G-key evdev codes can be found
with `sudo evtest`.

## Licence

GNU General Public License v2.0 or later — see [LICENSE](LICENSE).
