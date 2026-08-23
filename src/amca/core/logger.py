"""Small levelled logger with optional file output.

Kept deliberately close to the previous behaviour so plugin output looks the
same, with four defects fixed:

* ``set_mode`` had a mutable list as its default argument.
* ``__del__`` closed the file handle, which runs at unpredictable times during
  interpreter shutdown and can raise inside the GC.
* Warnings went to stdout by default, so ``amca ... 2>/dev/null`` still showed
  them and piping stdout captured them.
* ``fatal`` was spelled ``ERROR`` next to an ``error`` that did something else.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from typing import Final, TextIO

__all__ = ["LEVELS", "PREFIXES", "Logger"]

LEVELS: Final[dict[str, int]] = {
    "INFO": 1,
    "SUCCESS": 2,
    "WARN": 3,
    "ERROR": 4,
    "FATAL": 5,
}

PREFIXES: Final[tuple[str, ...]] = ("none", "minimal", "simple", "normal", "verbose")

_TAGS: Final[dict[str, str]] = {
    "INFO": "[INFO]",
    "SUCCESS": "[OK]",
    "WARN": "[WARN]",
    "ERROR": "[ERROR]",
    "FATAL": "[FATAL]",
}

_COLORS: Final[dict[str, str]] = {
    "INFO": "\033[2m",
    "SUCCESS": "\033[32m",
    "WARN": "\033[33m",
    "ERROR": "\033[31m",
    "FATAL": "\033[1;31m",
}

_RESET = "\033[0m"


def _enable_windows_vt() -> bool:
    """Turn on ANSI escape handling in the Windows console.

    Windows Terminal does this itself; the legacy conhost does not, and CPython
    does not do it for you. Returns False when the call is unavailable or
    fails, in which case colour stays off rather than printing escape codes as
    literal text.
    """
    try:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        handle = kernel32.GetStdHandle(-12)  # STD_ERROR_HANDLE
        mode = wintypes.DWORD()
        if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            return False
        enable_vt = 0x0004  # ENABLE_VIRTUAL_TERMINAL_PROCESSING
        return bool(kernel32.SetConsoleMode(handle, mode.value | enable_vt))
    except Exception:
        return False


def supports_color(stream: TextIO) -> bool:
    """Whether ANSI colour is safe on *stream*.

    NO_COLOR wins over everything (the informal standard). Otherwise the stream
    must be a TTY, and on Windows the console must accept VT sequences. The
    TERM check is POSIX-only: on Windows TERM is normally unset, and treating
    that as "no colour" meant colour never appeared there at all.
    """
    if os.environ.get("NO_COLOR"):
        return False
    if not getattr(stream, "isatty", lambda: False)():
        return False
    if os.name == "nt":
        # Windows Terminal, ConEmu and ANSICON advertise themselves; otherwise
        # try to switch VT processing on.
        if os.environ.get("WT_SESSION") or os.environ.get("ANSICON"):
            return True
        return _enable_windows_vt()
    return os.environ.get("TERM", "") not in ("", "dumb")


class Logger:
    """Levelled logger. Construct one per process (or per plugin run)."""

    __slots__ = (
        "_color",
        "_console",
        "_file_enabled",
        "_handle",
        "_min",
        "_name",
        "_path",
        "_prefix",
    )

    def __init__(
        self,
        log_path: str | Path | None = None,
        *,
        mode: str = "console",
        level: str = "INFO",
        prefix: str = "none",
        name: str = "amca",
    ) -> None:
        self._path = Path(log_path) if log_path else None
        self._handle: TextIO | None = None
        self._name = name
        self._min = LEVELS.get(level.upper(), 1)
        self._prefix = PREFIXES.index(prefix) if prefix in PREFIXES else 0
        self._console = True
        self._file_enabled = False
        self._color = supports_color(sys.stderr)
        self.set_mode(mode)

    # ── Configuration ───────────────────────────────────────────────────────

    def set_mode(self, mode: str) -> None:
        self._console, self._file_enabled = {
            "console": (True, False),
            "file": (False, True),
            "both": (True, True),
            "silent": (False, False),
        }.get(mode.lower(), (True, False))

    def set_level(self, level: str) -> None:
        self._min = LEVELS.get(level.upper(), self._min)

    def set_prefix(self, prefix: str) -> None:
        if prefix in PREFIXES:
            self._prefix = PREFIXES.index(prefix)

    # ── Emission ────────────────────────────────────────────────────────────

    def _decorate(self, level: str) -> tuple[str, str]:
        if self._prefix == 0:
            return "", ""
        tag = _TAGS[level]
        if self._prefix == 1:
            plain = tag
        elif self._prefix == 2:
            plain = f"{time.strftime('%H:%M:%S')} {tag}"
        elif self._prefix == 3:
            plain = f"{time.strftime('%Y-%m-%dT%H:%M:%S')} {tag}"
        else:
            plain = (
                f"{time.strftime('%Y-%m-%dT%H:%M:%S')} {tag} "
                f"({self._name} pid={os.getpid()})"
            )
        colored = plain.replace(tag, f"{_COLORS[level]}{tag}{_RESET}") if self._color else plain
        return colored + " ", plain + " "

    def _emit(self, level: str, message: str) -> None:
        if LEVELS[level] < self._min:
            return
        if not self._console and not self._file_enabled:
            return
        colored_prefix, plain_prefix = self._decorate(level)
        if self._console:
            # Everything at WARN and above goes to stderr so that stdout stays
            # usable for the output of whatever the plugin actually ran.
            stream = sys.stderr if LEVELS[level] >= LEVELS["WARN"] else sys.stdout
            stream.write(f"{colored_prefix}{message}\n")
        if self._file_enabled:
            handle = self._open()
            if handle is not None:
                try:
                    handle.write(f"{plain_prefix}{message}\n")
                except OSError:
                    self._file_enabled = False

    def _open(self) -> TextIO | None:
        if self._handle is not None:
            return self._handle
        if self._path is None:
            return None
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._handle = self._path.open("a", encoding="utf-8", buffering=1)
        except OSError:
            self._file_enabled = False
            return None
        return self._handle

    # ── Public API ──────────────────────────────────────────────────────────

    def log(self, message: str = "") -> None:
        self._emit("INFO", message)

    info = log

    def success(self, message: str = "") -> None:
        self._emit("SUCCESS", message)

    def warning(self, message: str = "") -> None:
        self._emit("WARN", message)

    #: Alias. Plugins written against the 2.x Logger call .warn(); linters that
    #: assume any .warn() is logging.warn will try to rewrite it, so both names
    #: are real methods and neither can break at runtime.
    warn = warning

    def error(self, message: str = "") -> None:
        self._emit("ERROR", message)

    def fatal(self, message: str = "", code: int = 1) -> None:
        """Log at FATAL and raise SystemExit."""
        self._emit("FATAL", message)
        self.close()
        raise SystemExit(code)

    def close(self) -> None:
        handle, self._handle = self._handle, None
        if handle is not None:
            try:
                handle.flush()
                handle.close()
            except OSError:
                pass
