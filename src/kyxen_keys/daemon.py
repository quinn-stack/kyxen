"""
Kyxen daemon — detects keyboard, grabs G-key evdev interface (suppression only),
reads G-key events via HID++ notifications, executes macros, forwards all
other input via uinput passthrough.
"""
from __future__ import annotations
import json
import os
import queue
import socket
import threading
import time
from pathlib import Path

import evdev
from evdev import UInput, ecodes

from . import config as cfg
from . import macro as macro_runner
from . import gkeys as gkeys_reader
from .lighting_engine import LightingEngine
from .keyboards import detect_keyboard, LogitechKeyboard

IPC_SOCKET = Path('/tmp/kyxen.sock')


class KyxenDaemon:
    def __init__(self) -> None:
        self._lock           = threading.Lock()
        self._keyboard: LogitechKeyboard | None = None
        self._device:   evdev.InputDevice | None = None
        self._uinput:       UInput | None = None
        self._mouse_uinput: UInput | None = None
        self._active_profile = ''
        self._profiles:  dict[str, cfg.Profile] = {}
        self._running    = False
        # gkey → MacroAction currently held down (hold_toggle state)
        self._toggle_held:  dict[str, cfg.MacroAction]    = {}
        # gkey → stop Event for active repeat loops
        self._repeat_stops: dict[str, threading.Event]    = {}
        # M-key LED control — bitmask updates sent to run_mkey_listener's fd.
        # Queue carries bitmask values: 0x00=off, 0x01=M1, 0x02=M2, 0x04=M3.
        self._mkey_led_queue: queue.SimpleQueue | None = None
        self._lighting_engine: LightingEngine | None = None

    # ── startup / shutdown ────────────────────────────────────────────────────

    def start(self) -> None:
        self._keyboard = detect_keyboard()
        if self._keyboard is None:
            print('[kyxen] no supported keyboard found — exiting')
            return

        # Remap must happen before grab: setProfile causes a brief USB state
        # flush that invalidates any hidraw fd already open on the G-key interface.
        wrote_remap = self._ensure_gkey_remap()
        if wrote_remap:
            print('[kyxen] waiting for keyboard to settle after profile write...')
            time.sleep(1.5)

        self._open_device()
        self._load_profiles()
        self._running = True

        threading.Thread(target=self._event_loop,   daemon=True).start()
        threading.Thread(target=self._ipc_loop,     daemon=True).start()
        threading.Thread(target=self._config_watch, daemon=True).start()

        gkeys_hidraw = self._keyboard.paths.hidraw_gkeys
        if gkeys_hidraw:
            threading.Thread(target=self._gkey_hid_loop, daemon=True).start()
            print(f'[kyxen] G-key detection: boot-protocol on {gkeys_hidraw}')
        else:
            print('[kyxen] WARNING: no G-key hidraw path found')

        hidraw = self._keyboard.paths.hidraw
        if hidraw:
            try:
                from . import onboard_profiles
                feat_8010     = onboard_profiles.get_feature_index(hidraw, 0x8010)
                feat_8020     = onboard_profiles.get_feature_index(hidraw, 0x8020)
                feat_profiles = onboard_profiles.get_feature_index(hidraw, 0x8100)
                self._mkey_led_queue = queue.SimpleQueue()
                threading.Thread(
                    target=self._mkey_hid_loop, args=(feat_8010, feat_8020, feat_profiles), daemon=True
                ).start()
                print(f'[kyxen] M-key detection: 0x8010=0x{feat_8010:02x} 0x8020=0x{feat_8020:02x} 0x8100=0x{feat_profiles:02x} on {hidraw}')
            except Exception as e:
                print(f'[kyxen] WARNING: M-key listener not started: {e}')

        # Start lighting engine and apply the active profile's lighting config.
        if hidraw:
            self._lighting_engine = LightingEngine(hidraw, lambda: not self._running)
            threading.Thread(target=self._lighting_engine.run, daemon=True).start()
            if self._active_profile in self._profiles:
                self._lighting_engine.set_config(
                    self._profiles[self._active_profile].lighting
                )
        self._push_mkey_bitmask(self._active_mkey_for(self._active_profile))
        print(f'[kyxen] active profile: {self._active_profile}')

        try:
            while self._running:
                time.sleep(1)
        except KeyboardInterrupt:
            self.stop()

    def stop(self) -> None:
        self._running = False
        self._cancel_all_repeats()
        self._release_all_toggles()
        if self._device:
            try:
                self._device.ungrab()
            except Exception:
                pass
        if self._uinput:
            self._uinput.close()
        if self._mouse_uinput:
            self._mouse_uinput.close()
        if IPC_SOCKET.exists():
            IPC_SOCKET.unlink()
        print('[kyxen] stopped')

    def _cancel_all_repeats(self) -> None:
        with self._lock:
            stops = dict(self._repeat_stops)
            self._repeat_stops.clear()
        for stop in stops.values():
            stop.set()

    def _release_all_toggles(self) -> None:
        with self._lock:
            held = dict(self._toggle_held)
            self._toggle_held.clear()
        for action in held.values():
            if action.action == 'hold_toggle':
                macro_runner.run_hold(action, press=False)
            elif action.action == 'mouse_button':
                macro_runner.run_mouse_hold(action, press=False)

    # ── device ────────────────────────────────────────────────────────────────

    def _open_device(self) -> None:
        self._device = evdev.InputDevice(self._keyboard.paths.evdev)
        self._device.grab()
        self._uinput = UInput.from_device(self._device, name='Kyxen Passthrough')
        macro_runner.set_uinput(self._uinput)
        _mouse_caps = {ecodes.EV_KEY: [ecodes.BTN_LEFT, ecodes.BTN_RIGHT, ecodes.BTN_MIDDLE,
                                        ecodes.BTN_SIDE, ecodes.BTN_EXTRA]}
        self._mouse_uinput = UInput(_mouse_caps, name='Kyxen Mouse')
        macro_runner.set_mouse_uinput(self._mouse_uinput)
        print(f'[kyxen] grabbed {self._device.name}')

    def _ensure_gkey_remap(self) -> bool:
        if not hasattr(self._keyboard, 'ensure_gkey_remap'):
            return False
        try:
            return self._keyboard.ensure_gkey_remap()
        except Exception as e:
            print(f'[kyxen] WARNING: G-key flash remap failed: {e}')
            print('[kyxen] G-keys may conflict with physical F-keys until remap succeeds')
            return False

    # ── event loop (evdev — suppression + passthrough only) ───────────────────

    def _event_loop(self) -> None:
        suppress = self._keyboard.GKEY_SUPPRESS_CODES
        try:
            for event in self._device.read_loop():
                if not self._running:
                    break
                if event.type == ecodes.EV_KEY and event.code in suppress:
                    # Drop silently — G-key identity comes from HID boot-protocol thread
                    continue
                # Forward as-is; original EV_SYN events drive sync — no extra syn() call
                self._uinput.write_event(event)
        except Exception as e:
            print(f'[kyxen] event loop error: {e}')
            self._running = False

    # ── HID++ G-key listener ──────────────────────────────────────────────────

    def _gkey_hid_loop(self) -> None:
        gkeys_reader.run_gkey_listener(
            hidraw_path=self._keyboard.paths.hidraw_gkeys,
            on_press=self._handle_gkey,
            on_release=self._handle_gkey_release,
            stop_flag=lambda: not self._running,
        )

    def _mkey_hid_loop(self, feat_8010: int, feat_8020: int, feat_profiles: int) -> None:
        gkeys_reader.run_mkey_listener(
            hidraw_path=self._keyboard.paths.hidraw,
            feat_8010_idx=feat_8010,
            feat_8020_idx=feat_8020,
            feat_profiles_idx=feat_profiles,
            on_mkey=self._handle_mkey,
            stop_flag=lambda: not self._running,
            led_queue=self._mkey_led_queue,
        )

    def _handle_mkey(self, mkey_idx: int) -> None:
        gcfg = cfg.load_global_config()
        name = gcfg.get('profile_slots', {}).get(f'm{mkey_idx + 1}')
        if name:
            self.switch_profile(name)
        else:
            print(f'[kyxen] M{mkey_idx + 1} pressed — no profile_slots.m{mkey_idx + 1} in config')

    def _handle_gkey_release(self, gkey: str) -> None:
        with self._lock:
            stop = self._repeat_stops.pop(gkey, None)
        if stop:
            stop.set()

    def _repeat_loop(self, action: cfg.MacroAction, stop: threading.Event) -> None:
        interval = max(action.repeat_rate, 10.0) / 1000.0
        while not stop.is_set():
            macro_runner.run(action)
            stop.wait(interval)

    def _handle_gkey(self, gkey: str) -> None:
        with self._lock:
            profile = self._profiles.get(self._active_profile)
        if not profile:
            return
        action = profile.macros.get(gkey)
        if not action:
            return
        if action.repeat and action.action not in ('hold_toggle', 'none'):
            stop = threading.Event()
            with self._lock:
                self._repeat_stops[gkey] = stop
            threading.Thread(target=self._repeat_loop, args=(action, stop), daemon=True).start()
            return
        is_hold = (action.action == 'hold_toggle' or
                   (action.action == 'mouse_button' and action.mouse_mode == 'hold'))
        if is_hold:
            with self._lock:
                if gkey in self._toggle_held:
                    held_action = self._toggle_held.pop(gkey)
                else:
                    self._toggle_held[gkey] = action
                    held_action = None
            release = held_action is not None
            target  = held_action if release else action
            if target.action == 'hold_toggle':
                macro_runner.run_hold(target, press=not release)
            else:
                macro_runner.run_mouse_hold(target, press=not release)
        else:
            macro_runner.run(action)

    # ── profiles ──────────────────────────────────────────────────────────────

    def _load_profiles(self) -> None:
        with self._lock:
            profiles = cfg.list_profiles()
            if not profiles:
                profiles = [cfg.ensure_default_profile()]
            self._profiles = {p.name: p for p in profiles}
            gcfg   = cfg.load_global_config()
            active = gcfg.get('active_profile', 'default')
            if active not in self._profiles:
                active = next(iter(self._profiles))
            self._active_profile = active

    def switch_profile(self, name: str) -> bool:
        self._cancel_all_repeats()
        self._release_all_toggles()
        with self._lock:
            if name not in self._profiles:
                return False
            self._active_profile = name
            gcfg = cfg.load_global_config()
            gcfg['active_profile'] = name
            cfg.save_global_config(gcfg)
        if self._lighting_engine is not None:
            self._lighting_engine.set_config(self._profiles[name].lighting)
        self._push_mkey_bitmask(self._active_mkey_for(name))
        print(f'[kyxen] profile → {name}')
        return True

    def _push_mkey_bitmask(self, active_mkey: int | None) -> None:
        if self._mkey_led_queue is not None:
            self._mkey_led_queue.put((1 << active_mkey) if active_mkey is not None else 0x00)

    def _active_mkey_for(self, profile_name: str) -> int | None:
        """Return 0-based M-key index if profile_name is assigned to an M-key slot, else None."""
        slots = cfg.load_global_config().get('profile_slots', {})
        for key, val in slots.items():
            if val == profile_name and key.startswith('m') and key[1:].isdigit():
                return int(key[1:]) - 1
        return None

    def reload_config(self) -> None:
        self._load_profiles()
        if self._lighting_engine is not None and self._active_profile in self._profiles:
            self._lighting_engine.set_config(
                self._profiles[self._active_profile].lighting
            )
        print('[kyxen] config reloaded')

    # ── IPC ───────────────────────────────────────────────────────────────────

    def _ipc_loop(self) -> None:
        if IPC_SOCKET.exists():
            IPC_SOCKET.unlink()
        srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        srv.bind(str(IPC_SOCKET))
        IPC_SOCKET.chmod(0o666)
        srv.listen(4)
        srv.settimeout(1.0)
        while self._running:
            try:
                conn, _ = srv.accept()
            except socket.timeout:
                continue
            threading.Thread(target=self._handle_ipc, args=(conn,), daemon=True).start()

    def _handle_ipc(self, conn: socket.socket) -> None:
        try:
            msg  = json.loads(conn.recv(4096).decode())
            cmd  = msg.get('cmd')
            if cmd == 'status':
                with self._lock:
                    resp = {'active_profile': self._active_profile,
                            'profiles': list(self._profiles.keys()),
                            'keyboard': self._keyboard.MODEL_NAME if self._keyboard else None}
            elif cmd == 'switch':
                resp = {'ok': self.switch_profile(msg.get('profile', ''))}
            elif cmd == 'reload':
                self.reload_config()
                resp = {'ok': True}
            else:
                resp = {'error': 'unknown command'}
            conn.sendall(json.dumps(resp).encode())
        except Exception as e:
            try:
                conn.sendall(json.dumps({'error': str(e)}).encode())
            except Exception:
                pass
        finally:
            conn.close()

    # ── config watcher ────────────────────────────────────────────────────────

    def _config_watch(self) -> None:
        try:
            last_mtime = max(
                (p.stat().st_mtime for p in cfg.PROFILES_DIR.glob('*.toml') if p.exists()),
                default=0.0,
            )
        except Exception:
            last_mtime = 0.0
        while self._running:
            try:
                mtime = max(
                    (p.stat().st_mtime for p in cfg.PROFILES_DIR.glob('*.toml') if p.exists()),
                    default=0.0,
                )
                if mtime > last_mtime:
                    last_mtime = mtime
                    time.sleep(0.2)
                    self.reload_config()
            except Exception:
                pass
            time.sleep(1.5)


# ── IPC client (used by GUI) ──────────────────────────────────────────────────

def _ipc_send(cmd: dict) -> dict | None:
    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(2.0)
        s.connect(str(IPC_SOCKET))
        s.sendall(json.dumps(cmd).encode())
        data = s.recv(4096)
        s.close()
        return json.loads(data)
    except Exception:
        return None

def daemon_status()           -> dict | None: return _ipc_send({'cmd': 'status'})
def daemon_running()          -> bool:        return daemon_status() is not None
def daemon_reload()           -> bool:        r = _ipc_send({'cmd': 'reload'});              return bool(r and r.get('ok'))
def daemon_switch_profile(n)  -> bool:        r = _ipc_send({'cmd': 'switch', 'profile': n}); return bool(r and r.get('ok'))
