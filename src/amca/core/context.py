"""The object every command and plugin receives.

Constructing an ``AmcaContext`` reads config and nothing else. Root discovery is
lazy and *never* prompts on its own — a caller that wants the interactive
"create a root here?" behaviour asks for it explicitly with
``find_root(interactive=True)``.

That split is the point. Previously root discovery ran as a side effect of
importing ``impl.util.globals``, which meant ``amca --help`` blocked on a y/n
prompt before printing help, and ``--depth`` could not affect the search it was
supposed to configure because the search had already happened at import time
(the old ``--help`` epilog said so out loud).
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

from ..config.store import ConfigStore
from . import paths
from .dirparse import DirInfo, DirParser
from .logger import Logger

__all__ = ["AmcaContext", "AmcaRoot"]


@dataclass(frozen=True, slots=True)
class AmcaRoot:
    """A resolved amca root."""

    #: Directory containing the marker folder (the project root).
    path: Path
    #: The marker folder itself, e.g. ``<path>/.Amca``.
    marker: Path

    @property
    def plugins_dir(self) -> Path:
        return self.marker / "plugins"

    @property
    def args_dir(self) -> Path:
        return self.marker / "args"


class AmcaContext:
    """Shared state for one amca invocation."""

    __slots__ = ("_root", "_root_done", "config", "config_dir", "cwd", "dirs", "log", "state_dir")

    def __init__(
        self,
        *,
        config_dir_override: str | os.PathLike[str] | None = None,
        cwd: Path | None = None,
    ) -> None:
        self.config_dir = paths.config_dir(config_dir_override)
        self.state_dir = paths.state_dir()
        self.config = ConfigStore.open(self.config_dir)
        self.dirs = DirParser()
        self.cwd = (cwd or Path.cwd()).resolve()
        self._root: AmcaRoot | None = None
        self._root_done = False

        self.log = Logger(
            self.state_dir / "amca.log",
            mode=self.config.get_str("log.mode"),
            level=self.config.get_str("log.level"),
            prefix=self.config.get_str("log.prefix"),
        )
        if self.config.load_error:
            # Surfaced rather than swallowed: a config file that failed to load
            # is the single most likely reason for "I changed it and nothing
            # happened".
            self.log.warning(f"config: {self.config.load_error}")

    # ── Derived paths ───────────────────────────────────────────────────────

    @property
    def plugins_dir(self) -> Path:
        configured = self.config.get_str("plugins.dir")
        if configured:
            return Path(configured).expanduser().resolve()
        return self.config_dir / "plugins"

    @property
    def editor(self) -> str:
        from ..config.schema import default_editor

        return self.config.get_str("core.editor") or default_editor()

    # ── Root discovery ──────────────────────────────────────────────────────

    def find_root(self, *, interactive: bool = False) -> AmcaRoot | None:
        """Walk up from cwd looking for the marker folder.

        Complexity: O(depth) directory reads, all cached in the DirParser.

        With ``interactive=True`` and no root found, offers to create one — but
        only when stdin is a TTY, so piping into amca or running it from an
        editor hook can never hang waiting for input.
        """
        if self._root_done:
            return self._root

        marker_name = self.config.get_str("root.folder_name")
        depth = self.config.get_int("root.search_depth")

        current = self.cwd
        for _ in range(max(1, depth)):
            info = self.dirs.parse_dir(current)
            if info.readable and marker_name in info.folders:
                self._root = AmcaRoot(current, current / marker_name)
                break
            if current.parent == current:
                break
            current = current.parent

        if self._root is None and interactive:
            self._root = self._maybe_create_root(marker_name)

        self._root_done = True
        return self._root

    def _maybe_create_root(self, marker_name: str) -> AmcaRoot | None:
        if not self.config.get_bool("root.ask_to_create"):
            return None
        if not (sys.stdin.isatty() and sys.stdout.isatty()):
            return None
        ignored = {str(p) for p in self.config.get_list("root.ignored_paths")}
        if str(self.cwd) in ignored:
            return None

        from ..cli.prompt import confirm

        if not confirm(f"No amca root found. Create one in {self.cwd}?", default=True):
            # Remember the "no" so the question is asked once per directory
            # rather than on every invocation.
            ignored.add(str(self.cwd))
            self.config.set_persistent("root.ignored_paths", sorted(ignored))
            self.config.save()
            return None

        return self.create_root(self.cwd)

    def create_root(self, path: Path) -> AmcaRoot:
        marker = (path / self.config.get_str("root.folder_name")).resolve()
        marker.mkdir(parents=True, exist_ok=True)
        (marker / "plugins").mkdir(exist_ok=True)
        (marker / "args").mkdir(exist_ok=True)
        self.dirs.invalidate(path)
        root = AmcaRoot(path.resolve(), marker)
        self._root = root
        self._root_done = True
        return root

    # ── Convenience ─────────────────────────────────────────────────────────

    def working_dir_info(self) -> DirInfo:
        return self.dirs.parse_dir(self.cwd)
