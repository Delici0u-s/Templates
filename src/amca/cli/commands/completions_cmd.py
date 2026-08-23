"""``amca completions`` — print, install or remove shell completion scripts."""

from __future__ import annotations

import argparse
import sys

from ...core.context import AmcaContext
from .. import completions as comp

__all__ = ["handle", "register"]


def register(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = sub.add_parser(
        "completions",
        help="print, install or remove shell tab-completion",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "A wheel cannot register completions at install time, so amca does it\n"
            "on first run instead: the script is written to your shell's per-user\n"
            "completion directory. Nothing is added to a shell rc file unless you\n"
            "pass --rc.\n\n"
            f"Set {comp.ENV_DISABLE}=1 to opt out entirely.\n"
        ),
    )
    parser.add_argument("shell", nargs="?", choices=list(comp.SHELLS), default=None,
                        help="defaults to the shell named in $SHELL")
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--install", action="store_true",
                        help="write the script to the standard per-user location")
    action.add_argument("--uninstall", action="store_true",
                        help="remove the script and any rc block amca added")
    action.add_argument("--status", action="store_true",
                        help="report where completions are, or would be, installed")
    action.add_argument("--where", action="store_true",
                        help="print manual installation instructions")
    parser.add_argument("--rc", action="store_true",
                        help="with --install, also add the fpath line to ~/.zshrc (zsh only)")
    parser.add_argument("--command", action="append", default=[], metavar="NAME",
                        help="also complete this name as `amca` — for an alias or "
                             "wrapper (repeatable)")
    parser.add_argument("--pl-command", dest="pl_command", action="append", default=[],
                        metavar="NAME", help="also complete this name as `amcapl`")
    parser.set_defaults(handler=handle)


def _resolve(shell: str | None) -> str | None:
    return shell or comp.detect_shell()


def handle(ctx: AmcaContext, args: argparse.Namespace, _: dict[str, list[str]]) -> int:
    if args.status:
        return _status()

    shell = _resolve(args.shell)
    if shell is None:
        print(
            f"amca: name a shell ({', '.join(comp.SHELLS)}); "
            f"$SHELL={_shell_env()!r} was not recognised",
            file=sys.stderr,
        )
        return 2

    if args.uninstall:
        removed, edited = comp.uninstall(shell)
        if not removed and not edited:
            print(f"nothing installed for {shell}")
            return 0
        for path in removed:
            print(f"deleted {path}")
        for path in edited:
            print(f"removed the amca block from {path}")
        print("  restart your shell for it to take effect")
        return 0

    if args.install:
        result = comp.install(shell, patch_rc=args.rc, names=args.command,
                              pl_names=args.pl_command)
        if result.note and not result.written and "could not write" in result.note:
            print(f"amca: {result.note}", file=sys.stderr)
            return 1
        print(f"{'installed' if result.written else 'already up to date'}: {result.path}")
        if result.rc_patched and result.rc_file:
            print(f"added an fpath block to {result.rc_file}")
        elif result.note:
            print(f"\n  {result.note}")
        if shell == "zsh":
            for name in args.command:
                print(f"  for the alias {name!r}, also add to your rc:  compdef _amca {name}")
            for name in args.pl_command:
                print(f"  for the alias {name!r}, also add to your rc:  compdef _amcapl {name}")
        print("\n  restart your shell (or `exec $SHELL`) to pick it up")
        return 0

    if args.where:
        print(f"# {shell}\n  {comp.install_hint(shell)}")
        return 0

    if sys.stdout.isatty():
        # Nobody wants 200 lines of shell in their scrollback; they meant to
        # redirect it, or they wanted --install.
        print(f"# amca {shell} completion. To install it for real:", file=sys.stderr)
        print("#   amca completions --install\n", file=sys.stderr)

    print(comp.script_for(shell, names=args.command, pl_names=args.pl_command), end="")
    return 0


def _shell_env() -> str:
    import os

    return os.environ.get("SHELL", "")


def _status() -> int:
    current = comp.detect_shell()
    incomplete = False
    for shell in comp.SHELLS:
        path = comp.target_path(shell)
        state = "installed" if comp.is_installed(shell) else "not installed"
        mark = " <- your shell" if shell == current else ""
        print(f"  {shell:<5} {state:<14} {path}{mark}")
        if shell == "zsh" and comp.is_installed("zsh") and comp.needs_fpath_line("zsh"):
            incomplete = True
            # "may not be on $fpath" understated it: without the fpath entry
            # zsh never reads the file, so completion does not work at all.
            print(f"        NOT ACTIVE: zsh does not read {path.parent}.")
            print("        Fix with:   amca completions --install --rc")

    print(f"\n  helper used by the scripts: {comp._executable('amca')}")
    if incomplete:
        print("  (a file being 'installed' is not enough for zsh — see above)")
    print("  aliases need their own registration: "
          "amca completions --install --command <alias>")
    return 0
