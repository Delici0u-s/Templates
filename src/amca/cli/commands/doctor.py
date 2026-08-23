"""``amca doctor`` — answer "why is it behaving like that?" in one command.

This exists because the two hardest bugs in the previous version were both
invisible from the outside: a subprocess inheriting a poisoned
``LD_LIBRARY_PATH`` from the frozen launcher, and a config value that was being
read from a layer the user did not know existed. Both are one line of output
here.
"""

from __future__ import annotations

import argparse
import os
import platform
import shutil
import sys
from pathlib import Path

from ... import __version__
from ...core import proc
from ...core.context import amcaContext
from ...plugins.registry import Registry

__all__ = ["handle", "register"]

_OK = "ok  "
_WARN = "warn"
_BAD = "FAIL"


def register(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = sub.add_parser("doctor", help="check the installation and report problems")
    parser.add_argument("--tools", nargs="*", default=None,
                        help="extra external programs to probe for")
    parser.set_defaults(handler=handle)


def _stale_presets() -> Path | None:
    """Detect a leftover src/amca/presets/ from an older layout."""
    try:
        import amca

        candidate = Path(amca.__file__ or "").parent / "presets"
    except Exception:
        return None
    return candidate if candidate.is_dir() else None


def _line(status: str, label: str, detail: str = "") -> None:
    print(f"  [{status}] {label}" + (f"  —  {detail}" if detail else ""))


def handle(ctx: amcaContext, args: argparse.Namespace, _: dict[str, list[str]]) -> int:
    problems = 0

    print(f"amca {__version__}")
    print(f"  python  {sys.version.split()[0]}  ({sys.executable})")
    print(f"  system  {platform.system()} {platform.release()}")
    print()

    print("paths")
    _line(_OK, "config dir", str(ctx.config_dir))
    _line(
        _OK if ctx.config.path.exists() else _WARN,
        "config file",
        str(ctx.config.path) + ("" if ctx.config.path.exists() else "  (not created yet)"),
    )
    _line(_OK, "state dir", str(ctx.state_dir))
    plugins_dir = ctx.plugins_dir
    _line(
        _OK if plugins_dir.is_dir() else _WARN,
        "plugin dir",
        str(plugins_dir) + ("" if plugins_dir.is_dir() else "  (missing)"),
    )
    print()

    print("config")
    if ctx.config.load_error:
        _line(_BAD, "config file loaded", ctx.config.load_error)
        problems += 1
    else:
        _line(_OK, "config file loaded")
    non_default = [row for row in ctx.config.all() if row.origin != "default"]
    if non_default:
        for row in non_default:
            _line(_OK, f"{row.key} = {row.value!r}", f"from {row.origin}")
    else:
        _line(_OK, "all settings at defaults")
    print()

    print("root")
    root = ctx.find_root()
    if root is None:
        _line(_WARN, "amca root", f"none within {ctx.config.get_int('root.search_depth')} "
                                  f"levels of {ctx.cwd}")
    else:
        _line(_OK, "amca root", str(root.marker))
    print()

    stale = _stale_presets()
    if stale is not None:
        _line(_BAD, "stale directory", str(stale))
        print(f"         This is left over from amca <= 3.0.0, where the bundled\n"
              f"         presets lived under src/. They now live in plugins/.\n"
              f"         Extracting a new release over an old checkout does not\n"
              f"         remove it. Delete it:  rm -rf {stale}")
        problems += 1
        print()

    print("plugins")
    registry = Registry(ctx)
    if not registry.entries:
        _line(_WARN, "installed", "none")
    for entry in registry.entries:
        instance = registry.instantiate(entry)
        if instance is None:
            _line(_BAD, entry.name, entry.error or "failed to load")
            problems += 1
        else:
            state = "enabled" if entry.enabled else "disabled"
            _line(_OK, entry.name, f"{state}; {instance.description or 'loads cleanly'}")
    for name in registry.missing_enabled():
        _line(_BAD, name, "enabled but not installed")
        problems += 1
    print()

    print("external tools")
    wanted = list(args.tools or []) or ["meson", "ninja", "git", ctx.editor.split()[0]]
    for tool in dict.fromkeys(wanted):
        found = shutil.which(tool)
        override = os.environ.get(f"AMCA_TOOL_{tool.upper().replace('-', '_')}")
        if override:
            _line(_OK, tool, f"{override}  (via AMCA_TOOL_{tool.upper()})")
        elif found:
            _line(_OK, tool, found)
        else:
            _line(_WARN, tool, "not on PATH")
    print()

    print("subprocess environment")
    if proc.is_frozen():
        _line(_WARN, "frozen bundle", "running from a PyInstaller bundle; "
                                      "loader paths are being sanitised for children")
    else:
        _line(_OK, "not a frozen bundle",
              "children inherit the shell's library paths unchanged")
    code, out, err = proc.capture(
        [sys.executable, "-c", "import binascii, sys; print(sys.version.split()[0])"]
    )
    if code == 0:
        _line(_OK, "child python imports cleanly", out.strip())
    else:
        _line(_BAD, "child python failed", (err or out).strip().splitlines()[-1:][0] if (err or out) else "")
        problems += 1
    print()

    if problems:
        print(f"{problems} problem(s) found.")
    else:
        print("No problems found.")
    return 1 if problems else 0
