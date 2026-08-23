"""``amca`` — run the plugins that apply to the current directory."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from ..config.schema import SCHEMA
from ..config.store import ConfigError
from ..core.context import AmcaContext
from ..plugins.markers import UnknownMarker, split_argv
from ..plugins.registry import Registry
from . import common
from .commands import args_edit, config_cmd, doctor, root_cmd, run_cmd

__all__ = ["build_parser", "main"]

_EPILOG = """\
plugin passthrough:
  Arguments after a plugin marker go to that plugin, up to the next marker.

      amca ---meson -s ---autoscript --fast

  Markers are formed from the prefix (default '---') plus the plugin's folder
  name, with underscores written as dashes. `amca plugins` lists them.
  An unknown marker is an error, not a silently discarded argument.
  A bare -- stops marker parsing, for values that start with the prefix:

      amca config set plugins.marker_prefix -- +++

troubleshooting:
  amca config list --origin   show every setting and which layer it came from
  amca doctor                 check tools, paths, and plugin health
"""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="amca",
        description="Run the build/script pipeline that fits the current directory.",
        epilog=_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    common.add_global_flags(parser)
    parser.add_argument("--dry-run", action="store_true",
                        help="show what would run without running it")

    sub = parser.add_subparsers(dest="command", metavar="<command>")

    run_parser = sub.add_parser("run", aliases=["r"],
                                help="run applicable plugins (default)")
    run_parser.set_defaults(handler=run_cmd.handle)

    root_cmd.register(sub)
    args_edit.register(sub)
    config_cmd.register(sub)
    doctor.register(sub)

    plugins_parser = sub.add_parser("plugins", help="list plugins and their markers")
    plugins_parser.set_defaults(handler=_handle_plugins)

    return parser


def _handle_plugins(ctx: AmcaContext, args: argparse.Namespace, _: dict[str, list[str]]) -> int:
    registry = Registry(ctx)
    prefix = ctx.config.get_str("plugins.marker_prefix")
    entries = registry.entries
    if not entries:
        print(f"No plugins installed in {ctx.plugins_dir}")
        print("Install one with:  amcapl install meson")
        return 0
    width = max(len(entry.name) for entry in entries)
    for entry in entries:
        state = "enabled " if entry.enabled else "disabled"
        print(f"  {state}  {entry.name:<{width}}  {prefix}{entry.name.replace('_', '-')}")
    missing = registry.missing_enabled()
    if missing:
        print(f"\n  enabled but not installed: {', '.join(missing)}")
    return 0


def _main(argv: Sequence[str] | None = None) -> int:
    raw = list(sys.argv[1:] if argv is None else argv)

    # The marker prefix must be known before argv can be split, but it lives in
    # config, which lives behind --config-dir. A hand-rolled scan rather than a
    # throwaway argparse: argparse assigns `--` a special meaning and would
    # print its own bare usage block on a malformed flag, before amca has even
    # decided what the command is.
    pre = common.pre_scan(raw)

    try:
        ctx = AmcaContext(config_dir_override=pre.get("config-dir"))
    except ConfigError as exc:
        print(f"amca: {exc}", file=sys.stderr)
        return 2

    prefix = pre.get("marker-prefix") or ctx.config.get_str("plugins.marker_prefix")
    try:
        SCHEMA["plugins.marker_prefix"].check(prefix)
    except ConfigError as exc:
        print(f"amca: {exc}", file=sys.stderr)
        return 2
    registry_names = [entry.name for entry in Registry(ctx).entries]

    try:
        split = split_argv(raw, registry_names, prefix)
    except UnknownMarker as exc:
        print(f"amca: {exc}", file=sys.stderr)
        return 2
    except ValueError as exc:
        print(f"amca: {exc}", file=sys.stderr)
        return 2

    parser = build_parser()
    args = parser.parse_args(split.main)

    try:
        common.apply_global_flags(ctx, args)
    except ConfigError as exc:
        print(f"amca: {exc}", file=sys.stderr)
        return 2

    if ctx.config.get_bool("core.greet"):
        print("Hello Master")

    handler = getattr(args, "handler", None)
    if handler is None:
        handler = run_cmd.handle
    return int(handler(ctx, args, split.per_plugin) or 0)


def main(argv: Sequence[str] | None = None) -> int:
    """Console-script entry point. Never lets a bare traceback reach the user."""
    return common.run_entry(_main, argv)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
