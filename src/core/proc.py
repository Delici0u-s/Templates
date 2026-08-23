"""One place for every external process amca or a plugin spawns.

Two jobs:

1. **Environment hygiene.** ``host_env()`` strips loader-path injection that a
   frozen bundle would have added. amca is no longer shipped as a PyInstaller
   binary, so this is now belt-and-braces rather than load-bearing — but it is
   cheap, and it is exactly the bug that made ``meson`` explode with
   "internal Python C API version mismatch" after every distro Python bump: the
   frozen launcher put its own stale ``libpython`` on ``LD_LIBRARY_PATH`` and
   every child inherited it. Keeping the guard here means reintroducing a
   frozen build later cannot reintroduce that bug.

2. **Tool resolution.** ``resolve_tool("meson")`` looks up an override
   (``AMCA_TOOL_MESON``) before falling back to ``PATH``, so a user with meson
   in a venv or a pinned toolchain does not have to fight amca. Previously
   seven separate call sites hardcoded the bare string ``"meson"``.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

__all__ = ["ToolMissing", "call", "capture", "host_env", "is_frozen", "resolve_tool", "run"]

_LOADER_VARS = (
    "LD_LIBRARY_PATH",
    "LIBPATH",
    "DYLD_LIBRARY_PATH",
    "DYLD_FRAMEWORK_PATH",
)


class ToolMissing(RuntimeError):
    """A required external program is not installed or not on PATH."""

    def __init__(self, tool: str, hint: str = "") -> None:
        self.tool = tool
        self.hint = hint
        super().__init__(f"'{tool}' not found on PATH" + (f"\n  {hint}" if hint else ""))


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False)) and hasattr(sys, "_MEIPASS")


def host_env(base: Mapping[str, str] | None = None, **overrides: str) -> dict[str, str]:
    """Environment for a child process, with bundle-loader paths undone."""
    env = dict(os.environ if base is None else base)
    if is_frozen():
        for key in _LOADER_VARS:
            original = env.pop(f"{key}_ORIG", None)
            if original is not None:
                env[key] = original
            else:
                env.pop(key, None)
        for key in [k for k in env if k.startswith("_PYI_")]:
            env.pop(key, None)
        env.pop("_MEIPASS2", None)
    env.update(overrides)
    return env


def resolve_tool(name: str, *alternatives: str, hint: str = "") -> str:
    """Find an external program.

    Order: ``$AMCA_TOOL_<NAME>`` override, then *name*, then *alternatives*
    (so ``resolve_tool("ninja", "ninja-build", "samu")`` works across distros).
    """
    override = os.environ.get(f"AMCA_TOOL_{name.upper().replace('-', '_')}")
    if override:
        path = Path(override).expanduser()
        if path.is_file() and os.access(path, os.X_OK):
            return str(path)
        found = shutil.which(override)
        if found:
            return found
        raise ToolMissing(name, f"AMCA_TOOL_{name.upper()} points at {override!r}, which is not executable")

    for candidate in (name, *alternatives):
        found = shutil.which(candidate)
        if found:
            return found
    raise ToolMissing(name, hint)


def run(cmd: Sequence[str], **kwargs: Any) -> subprocess.CompletedProcess[Any]:
    kwargs.setdefault("env", host_env())
    return subprocess.run(list(cmd), **kwargs)


def call(cmd: Sequence[str], **kwargs: Any) -> int:
    """Run *cmd*, return its exit status. Ctrl-C yields 130, as a shell would."""
    kwargs.setdefault("env", host_env())
    try:
        return subprocess.call(list(cmd), **kwargs)
    except KeyboardInterrupt:
        return 130
    except FileNotFoundError as exc:
        raise ToolMissing(str(cmd[0])) from exc


def capture(cmd: Sequence[str], **kwargs: Any) -> tuple[int, str, str]:
    kwargs.setdefault("env", host_env())
    kwargs.setdefault("text", True)
    kwargs.setdefault("check", False)
    completed = subprocess.run(list(cmd), capture_output=True, **kwargs)
    return completed.returncode, completed.stdout or "", completed.stderr or ""
