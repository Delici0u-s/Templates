"""Where amca keeps its files.

The old build wrote an absolute path into ``src/config_path.py`` at install
time. That made the checkout machine-specific (it showed up as a permanently
dirty file in git), made the binary non-relocatable, and meant reinstalling was
the only way to move the config. Resolution is now purely runtime.

Precedence, highest first:
  1. ``--config-dir`` on the command line
  2. ``$AMCA_CONFIG_DIR``
  3. ``$XDG_CONFIG_HOME/amca``  (Linux/BSD)
  4. platform default: ``~/.config/amca``, ``~/Library/Application Support/amca``,
     or ``%APPDATA%\\amca``
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

__all__ = [
    "ENV_CONFIG_DIR",
    "ENV_STATE_DIR",
    "config_dir",
    "default_config_dir",
    "state_dir",
]

ENV_CONFIG_DIR = "AMCA_CONFIG_DIR"
ENV_STATE_DIR = "AMCA_STATE_DIR"

_APP = "amca"


def _home() -> Path:
    return Path.home()


def default_config_dir() -> Path:
    """Platform-appropriate config directory, ignoring any override."""
    if sys.platform == "win32":
        base = os.environ.get("APPDATA")
        return Path(base) / _APP if base else _home() / "AppData" / "Roaming" / _APP
    if sys.platform == "darwin":
        return _home() / "Library" / "Application Support" / _APP
    xdg = os.environ.get("XDG_CONFIG_HOME")
    return Path(xdg) / _APP if xdg else _home() / ".config" / _APP


def default_state_dir() -> Path:
    """Where logs and caches live — separate from config so it can be wiped."""
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA")
        return Path(base) / _APP if base else _home() / "AppData" / "Local" / _APP
    if sys.platform == "darwin":
        return _home() / "Library" / "Caches" / _APP
    xdg = os.environ.get("XDG_STATE_HOME")
    return Path(xdg) / _APP if xdg else _home() / ".local" / "state" / _APP


def config_dir(override: str | os.PathLike[str] | None = None) -> Path:
    """Resolve the effective config directory. Does not create it."""
    if override:
        return Path(override).expanduser().resolve()
    env = os.environ.get(ENV_CONFIG_DIR)
    if env:
        return Path(env).expanduser().resolve()
    return default_config_dir()


def state_dir(override: str | os.PathLike[str] | None = None) -> Path:
    """Resolve the effective state directory. Does not create it."""
    if override:
        return Path(override).expanduser().resolve()
    env = os.environ.get(ENV_STATE_DIR)
    if env:
        return Path(env).expanduser().resolve()
    return default_state_dir()


def remove_tree(path: Path) -> None:
    """Delete a directory tree, tolerating read-only files.

    Windows refuses to unlink a file with the read-only attribute set, and git
    object files are exactly that. ``shutil.rmtree`` then fails partway
    through, leaving a half-deleted tree. Clearing the bit and retrying is the
    documented remedy.
    """
    import shutil
    import stat

    def _force(func, target, _exc):  # type: ignore[no-untyped-def]
        try:
            os.chmod(target, stat.S_IWRITE)
            func(target)
        except OSError:
            pass

    if sys.version_info >= (3, 12):
        shutil.rmtree(path, onexc=_force)
    else:
        shutil.rmtree(path, onerror=_force)
