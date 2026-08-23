"""Discovering plugins on disk and importing them.

Each plugin directory is imported as a real package under the synthetic name
``amca_plugin_<folder>``, with its own directory on ``sys.path`` only for the
duration of the import. The previous loader instead pushed the plugin
directory, every immediate subdirectory, and the parent onto ``sys.path``
permanently, then fabricated top-level modules named after whatever
subdirectories it found — so a plugin containing ``impl/`` claimed the global
name ``impl`` and the next plugin's ``import impl.util`` resolved into the
first plugin's code. It also tried four different plugin-shape heuristics and
three constructor signatures, silently. One shape is enough.
"""

from __future__ import annotations

import importlib.util
import inspect
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any

from ..api import Plugin
from ..core.dirparse import DirParser

__all__ = ["ENTRY_FILENAMES", "DiscoveredPlugin", "PluginLoadError", "discover", "load_plugin"]

#: Accepted entry-point filenames, in priority order. ``init.py`` is the legacy
#: name and is kept so existing plugin checkouts keep working.
ENTRY_FILENAMES: tuple[str, ...] = ("plugin.py", "init.py")


class PluginLoadError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class DiscoveredPlugin:
    #: Folder name — this is what the user types after the marker prefix.
    folder: str
    directory: Path
    entry: Path


def discover(plugins_dir: Path, dirs: DirParser | None = None) -> list[DiscoveredPlugin]:
    """List plugin directories that contain a recognised entry file.

    Complexity: O(#plugin directories). Never raises on a missing or
    unreadable plugin directory — an empty list is the correct answer there.
    """
    parser = dirs or DirParser()
    info = parser.parse_dir(plugins_dir)
    if not info.readable:
        return []

    found: list[DiscoveredPlugin] = []
    for folder in sorted(info.folders):
        if folder.startswith((".", "__")):
            continue
        directory = info.path / folder
        for filename in ENTRY_FILENAMES:
            entry = directory / filename
            if entry.is_file():
                found.append(DiscoveredPlugin(folder, directory, entry))
                break
    return found


@contextmanager
def _temporary_sys_path(directory: Path) -> Iterator[None]:
    """Expose *directory* for imports, then put ``sys.path`` back."""
    text = str(directory)
    added = text not in sys.path
    if added:
        sys.path.insert(0, text)
    try:
        yield
    finally:
        if added:
            try:
                sys.path.remove(text)
            except ValueError:
                pass


def _import_entry(found: DiscoveredPlugin) -> ModuleType:
    module_name = f"amca_plugin_{found.folder}"
    spec = importlib.util.spec_from_file_location(
        module_name,
        found.entry,
        submodule_search_locations=[str(found.directory)],
    )
    if spec is None or spec.loader is None:
        raise PluginLoadError(f"cannot build an import spec for {found.entry}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        with _temporary_sys_path(found.directory):
            spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(module_name, None)
        raise
    return module


def _find_plugin_class(module: ModuleType) -> type[Plugin] | None:
    for _, obj in inspect.getmembers(module, inspect.isclass):
        if obj is Plugin or obj.__module__ != module.__name__:
            continue
        if issubclass(obj, Plugin):
            return obj
    return None


def _find_legacy_class(module: ModuleType) -> type | None:
    """Detect a pre-3.0 plugin: a class with five-parameter should_load/load."""
    for _, obj in inspect.getmembers(module, inspect.isclass):
        if obj.__module__ != module.__name__:
            continue
        should = getattr(obj, "should_load", None)
        load = getattr(obj, "load", None)
        if not callable(should) or not callable(load):
            continue
        try:
            params = list(inspect.signature(should).parameters)
        except (TypeError, ValueError):
            continue
        if len(params) >= 5:
            return obj
    return None


class _LegacyAdapter(Plugin):
    """Presents a pre-3.0 five-argument plugin through the new interface."""

    def __init__(self, inner: object, folder: str) -> None:
        self._inner = inner
        self.name = folder
        self.description = "(legacy plugin API)"

    def _unpack(self, ctx: Any) -> tuple[Any, ...]:
        root_info = None
        if ctx.root is not None:
            root_info = ctx.dirs.parse_dir(ctx.root.path)
        return (root_info, ctx.plugin_dir, ctx.working_dir, ctx.dirs, ctx.args)

    def should_load(self, ctx: Any) -> bool:
        return bool(self._inner.should_load(*self._unpack(ctx)))  # type: ignore[attr-defined]

    def load(self, ctx: Any) -> int | None:
        result = self._inner.load(*self._unpack(ctx))  # type: ignore[attr-defined]
        return None if result is None else int(result)


def load_plugin(found: DiscoveredPlugin) -> Plugin:
    """Import *found* and return a ready-to-use plugin instance.

    Raises PluginLoadError with a message that names the plugin. Import errors
    inside plugin code are wrapped rather than propagated, so one broken
    third-party plugin cannot take down an unrelated command.
    """
    try:
        module = _import_entry(found)
    except Exception as exc:
        raise PluginLoadError(f"{found.folder}: import failed: {exc}") from exc

    cls = _find_plugin_class(module)
    if cls is not None:
        try:
            instance = cls()
        except Exception as exc:
            raise PluginLoadError(
                f"{found.folder}: {cls.__name__}() failed — plugin classes must be "
                f"constructible with no arguments: {exc}"
            ) from exc
        if not instance.name:
            instance.name = found.folder
        return instance

    legacy = _find_legacy_class(module)
    if legacy is not None:
        try:
            inner = legacy()
        except TypeError:
            try:
                inner = legacy(None, None)  # old (plugin_root_info, dir_parser) ctor
            except Exception as exc:
                raise PluginLoadError(
                    f"{found.folder}: could not instantiate legacy plugin: {exc}"
                ) from exc
        return _LegacyAdapter(inner, found.folder)

    raise PluginLoadError(
        f"{found.folder}: {found.entry.name} defines no subclass of amca.api.Plugin"
    )
