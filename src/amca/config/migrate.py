"""Importing an amca 2.x configuration.

The old layout was two JSON files under ``<root>/amca_config/``:
``general_conf.json`` and ``plugins/plugin_conf.json``. Keys were renamed in
3.0 (several booleans became enums), so this is an explicit table rather than
a copy.

Run by ``amca config migrate``. Never automatic: silently rewriting someone's
configuration on first launch is how you lose their settings without them
noticing.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .schema import SCHEMA
from .store import ConfigStore

__all__ = ["MigrationPlan", "find_legacy_config", "plan_migration"]


def _bool_to(true_value: str, false_value: str) -> Callable[[Any], Any]:
    return lambda raw: true_value if bool(raw) else false_value


def _prefix_level(raw: Any) -> Any:
    # 2.x spelled the "no prefix" level "None" (the string).
    text = str(raw)
    return "none" if text in ("None", "none", "") else text.lower()


#: (old file, old dotted key) -> (new key, converter)
_MAP: dict[tuple[str, str], tuple[str, Callable[[Any], Any] | None]] = {
    ("general", "debug"): ("core.debug", None),
    ("general", "extreamly_important.greet_user"): ("core.greet", None),
    ("general", "default_file_editor"): ("core.editor", None),
    ("general", "amca_root.folder_name"): ("root.folder_name", None),
    ("general", "amca_root.recursive_search_depth"): ("root.search_depth", None),
    ("general", "amca_root.ask_for_new"): ("root.ask_to_create", None),
    ("general", "amca_root.ignored_paths"): ("root.ignored_paths", None),
    ("general", "logging.log_mode"): ("log.mode", None),
    ("general", "logging.min_level"): ("log.level", None),
    ("general", "logging.log_prefix_level"): ("log.prefix", _prefix_level),
    ("plugins", "args.plugin_prefix"): ("plugins.marker_prefix", None),
    ("plugins", "generic.plugin_path"): ("plugins.dir", None),
    ("plugins", "enabled_plugins"): ("plugins.enabled", None),
    ("plugins", "generic.exit_on_plugin_error"): (
        "plugins.on_error", _bool_to("abort", "continue")),
    ("plugins", "generic.exit_on_plugin_not_found"): (
        "plugins.on_missing", _bool_to("abort", "warn")),
    ("plugins", "logging.print_loaded"): ("plugins.announce_loaded", None),
    ("plugins", "plugin_sources"): ("plugins.sources", None),
}

#: Keys that existed in 2.x and deliberately have no 3.x equivalent.
_DROPPED = {
    ("plugins", "logging.warn_if_plugin_not_found"):
        "folded into plugins.on_missing (ignore|warn|abort)",
    ("plugins", "logging.warn_if_plugin_arg_not_enabled"):
        "always warns now — a disabled plugin receiving arguments is a mistake worth naming",
}


@dataclass(slots=True)
class MigrationPlan:
    source: Path
    changes: dict[str, Any] = field(default_factory=dict)
    dropped: list[str] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)

    def apply(self, store: ConfigStore) -> None:
        for key, value in self.changes.items():
            store.set_persistent(key, value)
        store.save()


def find_legacy_config(search: list[Path]) -> Path | None:
    """Locate an ``amca_config`` directory from a 2.x install."""
    for base in search:
        candidate = base / "amca_config"
        if (candidate / "general_conf.json").is_file():
            return candidate
        if base.name == "amca_config" and (base / "general_conf.json").is_file():
            return base
    return None


def _flatten(data: dict[str, Any], prefix: str = "") -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in data.items():
        dotted = f"{prefix}{key}"
        if isinstance(value, dict):
            out.update(_flatten(value, f"{dotted}."))
        else:
            out[dotted] = value
    return out


def _load(path: Path) -> dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8") or "{}")
    except (OSError, ValueError):
        return {}
    return _flatten(raw) if isinstance(raw, dict) else {}


def plan_migration(legacy_dir: Path) -> MigrationPlan:
    """Work out what a migration would change, without changing anything."""
    plan = MigrationPlan(source=legacy_dir)
    old = {
        "general": _load(legacy_dir / "general_conf.json"),
        "plugins": _load(legacy_dir / "plugins" / "plugin_conf.json"),
    }

    for (bucket, old_key), (new_key, convert) in _MAP.items():
        if old_key not in old[bucket]:
            continue
        value = old[bucket][old_key]
        if convert is not None:
            value = convert(value)
        field_def = SCHEMA[new_key]
        try:
            coerced = field_def.coerce(value)
            field_def.check(coerced)
        except Exception as exc:
            plan.problems.append(f"{old_key} -> {new_key}: {exc}")
            continue
        if coerced != field_def.default:
            plan.changes[new_key] = coerced

    for (bucket, old_key), reason in _DROPPED.items():
        if old_key in old[bucket]:
            plan.dropped.append(f"{old_key}: {reason}")

    # 2.x had no offline source, so a migrated plugins.sources would lose the
    # ability to install a preset without a network. Put 'builtin' back in
    # front of whatever was there.
    sources = plan.changes.get("plugins.sources")
    if sources is not None and "builtin" not in sources:
        plan.changes["plugins.sources"] = ["builtin", *sources]

    # 2.x stored plugins under <config>/amca_config/plugins/installed_plugins.
    installed = legacy_dir / "plugins" / "installed_plugins"
    if installed.is_dir() and "plugins.dir" not in plan.changes:
        plan.changes["plugins.dir"] = str(installed.resolve())

    return plan
