"""``amca new`` / ``amca remove`` / ``amca root`` — amca root directories."""

from __future__ import annotations

import argparse

from ...core.context import amcaContext
from ...core.paths import remove_tree
from ..prompt import confirm

__all__ = ["register"]


def register(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    new = sub.add_parser("new", aliases=["n"], help="create an amca root here")
    new.set_defaults(handler=_new)

    remove = sub.add_parser("remove", aliases=["rm"], help="delete the amca root")
    remove.add_argument("-y", "--yes", action="store_true", help="skip confirmation")
    remove.set_defaults(handler=_remove)

    root = sub.add_parser("root", help="show or manage root detection")
    root_sub = root.add_subparsers(dest="root_command", metavar="<action>")

    show = root_sub.add_parser("show", help="print the resolved root")
    show.set_defaults(handler=_show)

    ignore = root_sub.add_parser("ignore", help="stop asking to create a root here")
    ignore.set_defaults(handler=_ignore)

    unignore = root_sub.add_parser("unignore", help="ask again in this directory")
    unignore.set_defaults(handler=_unignore)

    clear = root_sub.add_parser("clear-ignored", help="forget every ignored directory")
    clear.set_defaults(handler=_clear_ignored)

    root.set_defaults(handler=_show)


def _new(ctx: amcaContext, args: argparse.Namespace, _: dict[str, list[str]]) -> int:
    existing = ctx.find_root()
    if existing is not None and existing.path == ctx.cwd:
        print(f"already an amca root: {existing.marker}")
        return 0
    if existing is not None:
        print(f"note: a parent root already exists at {existing.marker}")
    root = ctx.create_root(ctx.cwd)
    print(f"created {root.marker}")
    return 0


def _remove(ctx: amcaContext, args: argparse.Namespace, _: dict[str, list[str]]) -> int:
    root = ctx.find_root()
    if root is None:
        print("no amca root found")
        return 1
    if not args.yes and not confirm(f"Delete {root.marker}?", default=False):
        print("cancelled")
        return 1
    remove_tree(root.marker)
    print(f"removed {root.marker}")
    return 0


def _show(ctx: amcaContext, args: argparse.Namespace, _: dict[str, list[str]]) -> int:
    root = ctx.find_root()
    if root is None:
        print(f"no amca root within {ctx.config.get_int('root.search_depth')} "
              f"levels above {ctx.cwd}")
        return 1
    print(f"root   : {root.path}")
    print(f"marker : {root.marker}")
    return 0


def _ignore(ctx: amcaContext, args: argparse.Namespace, _: dict[str, list[str]]) -> int:
    ignored = {str(p) for p in ctx.config.get_list("root.ignored_paths")}
    ignored.add(str(ctx.cwd))
    ctx.config.set_persistent("root.ignored_paths", sorted(ignored))
    ctx.config.save()
    print(f"ignoring {ctx.cwd}")
    return 0


def _unignore(ctx: amcaContext, args: argparse.Namespace, _: dict[str, list[str]]) -> int:
    ignored = {str(p) for p in ctx.config.get_list("root.ignored_paths")}
    if str(ctx.cwd) not in ignored:
        print(f"{ctx.cwd} was not ignored")
        return 0
    ignored.discard(str(ctx.cwd))
    ctx.config.set_persistent("root.ignored_paths", sorted(ignored))
    ctx.config.save()
    print(f"no longer ignoring {ctx.cwd}")
    return 0


def _clear_ignored(ctx: amcaContext, args: argparse.Namespace, _: dict[str, list[str]]) -> int:
    count = len(ctx.config.get_list("root.ignored_paths"))
    ctx.config.set_persistent("root.ignored_paths", [])
    ctx.config.save()
    print(f"cleared {count} ignored director{'y' if count == 1 else 'ies'}")
    return 0
