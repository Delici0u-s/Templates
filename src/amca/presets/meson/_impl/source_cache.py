"""Detect whether the *set* of source files changed since the last run.

meson only needs ``--reconfigure`` when files appear or disappear, not when
their contents change (ninja handles that). Storing a sorted list of relative
POSIX paths keeps the cache readable and identical across platforms.
"""

from __future__ import annotations

from pathlib import Path

__all__ = ["CACHE_FILENAME", "sources_changed"]

SOURCE_GLOBS: tuple[str, ...] = ("*.c", "*.cpp", "*.cxx", "*.cc", "*.m", "*.mm")
CACHE_FILENAME = "sources.cache"

#: Directories that never contain project sources. Skipping them keeps the
#: walk cheap on large trees; the old version rglob'd everything including
#: .git and subprojects.
PRUNE = frozenset({".git", ".hg", ".svn", "subprojects", "__pycache__", ".cache", "node_modules"})


def _cache_path(project_root: Path, plugin_dir: Path | None) -> Path:
    base = plugin_dir if plugin_dir is not None else project_root
    return base / CACHE_FILENAME


def _walk_sources(root: Path, exclude: frozenset[Path]) -> set[str]:
    """Relative POSIX paths of every source file under *root*.

    Complexity: O(files visited). Pruned subtrees are not descended into, so
    a build directory inside the project costs one stat, not a full walk.
    """
    suffixes = {glob.lstrip("*") for glob in SOURCE_GLOBS}
    found: set[str] = set()
    stack = [root]
    while stack:
        current = stack.pop()
        try:
            entries = list(current.iterdir())
        except OSError:
            continue
        for entry in entries:
            if entry.is_dir():
                if entry.name in PRUNE or entry.name.startswith("."):
                    continue
                if entry.resolve() in exclude:
                    continue
                stack.append(entry)
            elif entry.suffix in suffixes:
                try:
                    found.add(entry.relative_to(root).as_posix())
                except ValueError:
                    continue
    return found


def sources_changed(
    project_root: Path,
    plugin_dir: Path | None,
    exclude: frozenset[Path] = frozenset(),
) -> bool:
    """True when the source set differs from the stored snapshot.

    On the first call the snapshot is written and False is returned, so the
    run immediately after ``meson setup`` does not trigger a pointless
    reconfigure.
    """
    cache_file = _cache_path(project_root, plugin_dir)
    current = _walk_sources(project_root, exclude)

    if not cache_file.exists():
        _write(cache_file, current)
        return False

    try:
        cached = set(filter(None, cache_file.read_text(encoding="utf-8").splitlines()))
    except OSError:
        _write(cache_file, current)
        return True

    if current != cached:
        _write(cache_file, current)
        return True
    return False


def _write(cache_file: Path, sources: set[str]) -> None:
    try:
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        cache_file.write_text("\n".join(sorted(sources)) + "\n", encoding="utf-8")
    except OSError:
        pass  # A read-only project tree must not break the build.
