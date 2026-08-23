"""Locating and invoking a project's ``amca_auto_script``."""

from __future__ import annotations

import os
from pathlib import Path

__all__ = ["BASENAME", "CANDIDATES", "INTERPRETERS", "build_command", "find_script", "template_for"]

BASENAME = "amca_auto_script"

if os.name == "nt":
    INTERPRETERS: dict[str, list[str]] = {
        ".ps1": ["powershell", "-ExecutionPolicy", "Bypass", "-File"],
        ".bat": ["cmd", "/C"],
        ".cmd": ["cmd", "/C"],
    }
    #: On Windows an extensionless file is not executable, so it is not a
    #: candidate. On POSIX it is (with a shebang).
    CANDIDATES: tuple[str, ...] = tuple(f"{BASENAME}{ext}" for ext in INTERPRETERS)
else:
    INTERPRETERS = {
        ".sh": ["sh"],
        ".bash": ["bash"],
        ".zsh": ["zsh"],
    }
    CANDIDATES = (BASENAME,) + tuple(f"{BASENAME}{ext}" for ext in INTERPRETERS)

_TEMPLATES = {
    ".bat": "@echo off\r\n\r\n",
    ".cmd": "@echo off\r\n\r\n",
    ".ps1": "# amca auto script\r\n\r\n",
    ".sh": "#!/usr/bin/env sh\nset -eu\n\n",
    ".bash": "#!/usr/bin/env bash\nset -euo pipefail\n\n",
    ".zsh": "#!/usr/bin/env zsh\nset -euo pipefail\n\n",
}


def template_for(extension: str) -> str:
    return _TEMPLATES.get(extension, "#!/usr/bin/env sh\nset -eu\n\n")


def find_script(directory: Path) -> tuple[Path | None, list[Path]]:
    """Return (script, all_matches).

    Two matches is an ambiguity the caller must report rather than silently
    picking one — which is what the previous version did in one code path and
    not in another.
    """
    matches = [directory / name for name in CANDIDATES if (directory / name).is_file()]
    return (matches[0] if len(matches) == 1 else None), matches


def build_command(script: Path, args: list[str]) -> tuple[list[str] | None, str]:
    """Build the argv for *script*. Returns (argv, error_message)."""
    interpreter = INTERPRETERS.get(script.suffix.lower())
    if interpreter is not None:
        return [*interpreter, str(script), *args], ""
    if not os.access(script, os.X_OK):
        return None, f"{script.name} is not executable — run: chmod +x {script}"
    return [str(script), *args], ""
