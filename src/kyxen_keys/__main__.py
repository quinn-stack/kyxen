"""Entry point: `kyxen-daemon` or `python3 -m kyxen_keys`.

Subcommands:
  (none)               run the daemon
  install-service      register as a systemd user service
  uninstall-service    remove the systemd user service
  print-service        print the rendered unit file to stdout
  install-desktop      register the GUI as an XDG desktop entry
  uninstall-desktop    remove the desktop entry
  print-desktop        print the rendered desktop entry to stdout
"""
from __future__ import annotations
import argparse
import sys

from .daemon import KyxenDaemon


def _run_daemon(_args: argparse.Namespace) -> int:
    KyxenDaemon().start()
    return 0


def _install(args: argparse.Namespace) -> int:
    from . import service
    return service.install(enable=not args.no_enable, start=not args.no_start)


def _uninstall(_args: argparse.Namespace) -> int:
    from . import service
    return service.uninstall()


def _print_unit(_args: argparse.Namespace) -> int:
    from . import service
    return service.print_unit()


def _install_desktop(_args: argparse.Namespace) -> int:
    from . import desktop
    return desktop.install()


def _uninstall_desktop(_args: argparse.Namespace) -> int:
    from . import desktop
    return desktop.uninstall()


def _print_desktop(_args: argparse.Namespace) -> int:
    from . import desktop
    return desktop.print_entry()


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog='kyxen-daemon', description='Kyxen G-key macro daemon')
    sub = p.add_subparsers(dest='cmd')

    inst = sub.add_parser('install-service', help='register as a systemd user service')
    inst.add_argument('--no-enable', action='store_true', help="don't enable the service")
    inst.add_argument('--no-start',  action='store_true', help="don't start the service now")
    inst.set_defaults(func=_install)

    uninst = sub.add_parser('uninstall-service', help='remove the systemd user service')
    uninst.set_defaults(func=_uninstall)

    show = sub.add_parser('print-service', help='print the rendered unit file')
    show.set_defaults(func=_print_unit)

    idesk = sub.add_parser('install-desktop', help='register the GUI as an XDG desktop entry')
    idesk.set_defaults(func=_install_desktop)

    udesk = sub.add_parser('uninstall-desktop', help='remove the desktop entry')
    udesk.set_defaults(func=_uninstall_desktop)

    pdesk = sub.add_parser('print-desktop', help='print the rendered desktop entry')
    pdesk.set_defaults(func=_print_desktop)

    p.set_defaults(func=_run_daemon)
    return p


def main() -> None:
    args = _build_parser().parse_args()
    sys.exit(args.func(args) or 0)


if __name__ == '__main__':
    main()
