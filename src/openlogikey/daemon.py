"""
OpenLogiKey daemon — detects keyboard, grabs G-key interface,
executes macros, forwards all other input via uinput passthrough.
"""
from __future__ import annotations
import json
import os
import socket
import threading
import time
from pathlib import Path

import evdev
from evdev import UInput, ecodes

from . import config as cfg
from . import macro as macro_runner
from .keyboards import detect_keyboard, LogitechKeyboard

IPC_SOCKET = Path('/tmp/openlogikey.sock')


class OpenLogiKeyDaemon:
    def __init__(self) -> None:
        self._lock           = threading.Lock()
        self._keyboard: LogitechKeyboard | None = None
        self._device:   evdev.InputDevice | None = None
        self._uinput:   UInput | None = None
        self._active_profile = ''
        self._profiles:  dict[str, cfg.Profile] = {}
        self._running    = False

    # ── startup / shutdown ────────────────────────────────────────────────────

    def start(self) -> None:
        self._keyboard = detect_keyboard()
        if self._keyboard is None:
            print('[openlogikey] no supported keyboard found — exiting')
            return

        self._open_device()
        self._load_profiles()
        self._running = True

        threading.Thread(target=self._event_loop,   daemon=True).start()
        threading.Thread(target=self._ipc_loop,     daemon=True).start()
        threading.Thread(target=self._config_watch, daemon=True).start()

        print(f'[openlogikey] active profile: {self._active_profile}')

        try:
            while self._running:
                time.sleep(1)
        except KeyboardInterrupt:
            self.stop()

    def stop(self) -> None:
        self._running = False
        if self._device:
            try:
                self._device.ungrab()
            except Exception:
                pass
        if self._uinput:
            self._uinput.close()
        if IPC_SOCKET.exists():
            IPC_SOCKET.unlink()
        print('[openlogikey] stopped')

    # ── device ────────────────────────────────────────────────────────────────

    def _open_device(self) -> None:
        self._device = evdev.InputDevice(self._keyboard.paths.evdev)
        self._device.grab()
        self._uinput = UInput.from_device(self._device, name='OpenLogiKey Passthrough')
        macro_runner.set_uinput(self._uinput)
        print(f'[openlogikey] grabbed {self._device.name}')

    # ── event loop ────────────────────────────────────────────────────────────

    def _event_loop(self) -> None:
        gkey_map = self._keyboard.gkey_map()
        try:
            for event in self._device.read_loop():
                if not self._running:
                    break
                if event.type == ecodes.EV_KEY and event.code in gkey_map:
                    if event.value == 1:
                        self._handle_gkey(gkey_map[event.code])
                else:
                    self._uinput.write_event(event)
                    self._uinput.syn()
        except Exception as e:
            print(f'[openlogikey] event loop error: {e}')
            self._running = False

    def _handle_gkey(self, gkey: str) -> None:
        with self._lock:
            profile = self._profiles.get(self._active_profile)
        if not profile:
            return
        action = profile.macros.get(gkey)
        if action:
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
        with self._lock:
            if name not in self._profiles:
                return False
            self._active_profile = name
            gcfg = cfg.load_global_config()
            gcfg['active_profile'] = name
            cfg.save_global_config(gcfg)
        if self._keyboard:
            profile = self._profiles[name]
            self._keyboard.apply_lighting(profile.lighting_mode, profile.lighting_colour)
        print(f'[openlogikey] profile → {name}')
        return True

    def reload_config(self) -> None:
        self._load_profiles()
        print('[openlogikey] config reloaded')

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
def daemon_reload()           -> bool:        r = _ipc_send({'cmd': 'reload'});          return bool(r and r.get('ok'))
def daemon_switch_profile(n)  -> bool:        r = _ipc_send({'cmd': 'switch', 'profile': n}); return bool(r and r.get('ok'))
