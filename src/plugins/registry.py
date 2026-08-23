"""Selecting and running plugins for one invocation."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..api import Plugin, PluginContext, PluginError
from ..core.context import AmcaContext
from ..core.proc import ToolMissing
from .argfiles import read_arg_file
from .loader import DiscoveredPlugin, PluginLoadError, discover, load_plugin

__all__ = ["PluginEntry", "Registry"]


@dataclass(slots=True)
class PluginEntry:
    found: DiscoveredPlugin
    enabled: bool
    instance: Plugin | None = None
    error: str | None = None

    @property
    def name(self) -> str:
        return self.found.folder


class Registry:
    """Discovery, enablement, and the run loop.

    Kept separate from the CLI so ``amca run``, ``amcapl call`` and ``amcapl
    list`` all share one notion of what a plugin is and when it applies.
    """

    __slots__ = ("_entries", "ctx")

    def __init__(self, ctx: AmcaContext) -> None:
        self.ctx = ctx
        enabled = {str(name) for name in ctx.config.get_list("plugins.enabled")}
        self._entries = [
            PluginEntry(found, found.folder in enabled)
            for found in discover(ctx.plugins_dir, ctx.dirs)
        ]

    # ── Queries ─────────────────────────────────────────────────────────────

    @property
    def entries(self) -> list[PluginEntry]:
        return list(self._entries)

    def names(self) -> list[str]:
        return [entry.name for entry in self._entries]

    def enabled_names(self) -> list[str]:
        return [entry.name for entry in self._entries if entry.enabled]

    def get(self, name: str) -> PluginEntry | None:
        for entry in self._entries:
            if entry.name == name:
                return entry
        return None

    def missing_enabled(self) -> list[str]:
        """Names in ``plugins.enabled`` with nothing on disk to back them."""
        present = set(self.names())
        return sorted(
            name
            for name in (str(n) for n in self.ctx.config.get_list("plugins.enabled"))
            if name not in present
        )

    # ── Execution ───────────────────────────────────────────────────────────

    def make_context(self, name: str, args: list[str], *, dry_run: bool) -> PluginContext:
        root = self.ctx.find_root()
        plugin_dir: Path | None = None
        defaults: list[str] = []
        if root is not None:
            plugin_dir = root.plugins_dir / name
            plugin_dir.mkdir(parents=True, exist_ok=True)
            # Per-project defaults from .Amca/args/<name>.args come first, so
            # anything typed on the command line can still override them.
            defaults = read_arg_file(root.args_dir / f"{name}.args")
            if defaults and self.ctx.config.get_bool("core.debug"):
                self.ctx.log.log(f"{name}: default args {defaults}")
        return PluginContext(
            args=[*defaults, *args],
            working_dir=self.ctx.working_dir_info(),
            root=root,
            plugin_dir=plugin_dir,
            dirs=self.ctx.dirs,
            log=self.ctx.log,
            dry_run=dry_run,
        )

    def instantiate(self, entry: PluginEntry) -> Plugin | None:
        if entry.instance is not None or entry.error is not None:
            return entry.instance
        try:
            entry.instance = load_plugin(entry.found)
        except PluginLoadError as exc:
            entry.error = str(exc)
            self.ctx.log.error(str(exc))
        return entry.instance

    def run(self, args_by_plugin: dict[str, list[str]], *, dry_run: bool = False) -> int:
        """Run every enabled plugin whose ``should_load`` returns True.

        Returns the exit status: 0 when everything succeeded, otherwise the
        first non-zero status a plugin returned.
        """
        log = self.ctx.log
        abort_on_error = self.ctx.config.get_str("plugins.on_error") == "abort"
        on_missing = self.ctx.config.get_str("plugins.on_missing")
        announce = self.ctx.config.get_bool("plugins.announce_loaded")

        missing = self.missing_enabled()
        if missing and on_missing != "ignore":
            message = f"enabled plugin(s) not installed: {', '.join(missing)}"
            if on_missing == "abort":
                log.error(message)
                return 1
            log.warning(message)

        # Naming a plugin with a marker narrows the run to that plugin. Without
        # this, `amca ---meson --help` also executed autoscript, because
        # autoscript legitimately applied to the directory — technically correct
        # and completely surprising. Set plugins.marker_scope=all for the old
        # run-everything behaviour.
        restrict_to: set[str] | None = None
        if args_by_plugin and self.ctx.config.get_str("plugins.marker_scope") == "selected":
            restrict_to = set(args_by_plugin)

        # Selection pass: cheap, no side effects beyond the plugin's own dir.
        selected: list[tuple[PluginEntry, PluginContext]] = []
        for entry in self._entries:
            if not entry.enabled:
                continue
            if restrict_to is not None and entry.name not in restrict_to:
                continue
            instance = self.instantiate(entry)
            if instance is None:
                if abort_on_error:
                    return 1
                continue
            ctx = self.make_context(entry.name, args_by_plugin.get(entry.name, []), dry_run=dry_run)
            try:
                applies = instance.should_load(ctx)
            except Exception as exc:
                log.error(f"{entry.name}: should_load raised: {exc}")
                if abort_on_error:
                    return 1
                continue
            if applies:
                selected.append((entry, ctx))

        if not selected:
            unmatched = [name for name in args_by_plugin if not self._is_selected(name, selected)]
            for name in unmatched:
                candidate = self.get(name)
                if candidate is None:
                    continue
                if not candidate.enabled:
                    log.warning(f"{name}: arguments given but the plugin is disabled "
                             f"(enable it with: amcapl enable {name})")
                else:
                    log.warning(f"{name}: arguments given but should_load() returned False here")

        status = 0
        for entry, ctx in selected:
            if announce:
                log.log(f"running plugin '{entry.name}'")
            try:
                result = entry.instance.load(ctx)  # type: ignore[union-attr]
            except PluginError as exc:
                log.error(f"{entry.name}: {exc}")
                result = 1
            except ToolMissing as exc:
                log.error(f"{entry.name}: {exc}")
                result = 127
            except KeyboardInterrupt:
                log.warning(f"{entry.name}: interrupted")
                return 130
            except Exception as exc:
                log.error(f"{entry.name}: {type(exc).__name__}: {exc}")
                if self.ctx.config.get_bool("core.debug"):
                    import traceback

                    traceback.print_exc()
                result = 1
            code = int(result or 0)
            if code != 0:
                status = status or code
                if abort_on_error:
                    return status
        return status

    @staticmethod
    def _is_selected(name: str, selected: list[tuple[PluginEntry, PluginContext]]) -> bool:
        return any(entry.name == name for entry, _ in selected)
