"""Cheap, cached directory listings.

A single amca run asks "what is in this directory?" repeatedly — once during
root discovery, once per plugin ``should_load``, once more during ``load``. The
cache turns that into one ``scandir`` per directory per process.

Complexity: ``parse_dir`` is O(entries) on a miss, O(1) on a hit.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

__all__ = ["DirInfo", "DirParser"]


@dataclass(frozen=True, slots=True)
class DirInfo:
    """Snapshot of one directory's immediate contents."""

    path: Path
    files: frozenset[str] = field(default_factory=frozenset)
    folders: frozenset[str] = field(default_factory=frozenset)
    #: False when the directory does not exist or could not be read. The old
    #: version let iterdir() raise straight out of plugin discovery.
    readable: bool = True

    def has_file(self, *names: str) -> bool:
        return any(name in self.files for name in names)

    def has_folder(self, *names: str) -> bool:
        return any(name in self.folders for name in names)


class DirParser:
    """Memoising directory reader. Not thread-safe; amca is single-threaded."""

    __slots__ = ("_cache",)

    def __init__(self) -> None:
        self._cache: dict[Path, DirInfo] = {}

    def parse_dir(self, path: Path) -> DirInfo:
        key = Path(path).resolve(strict=False)
        cached = self._cache.get(key)
        if cached is not None:
            return cached

        files: set[str] = set()
        folders: set[str] = set()
        readable = True
        try:
            with os.scandir(key) as entries:
                for entry in entries:
                    try:
                        if entry.is_dir():
                            folders.add(entry.name)
                        else:
                            files.add(entry.name)
                    except OSError:
                        files.add(entry.name)
        except (OSError, ValueError):
            readable = False

        info = DirInfo(key, frozenset(files), frozenset(folders), readable)
        self._cache[key] = info
        return info

    def invalidate(self, path: Path | None = None) -> None:
        """Drop cached entries. Call after creating or deleting directories."""
        if path is None:
            self._cache.clear()
        else:
            self._cache.pop(Path(path).resolve(strict=False), None)
