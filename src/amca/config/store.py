"""Layered configuration with explicit persistence and origin tracking.

Four layers, lowest to highest:

    default  ->  file  ->  env  ->  session

Only the ``file`` layer is ever written to disk, and only through
:meth:`ConfigStore.set_persistent`. Everything a CLI flag does lands in
``session``, which exists purely in memory.

This is the fix for a real bug in the previous version: ``Settings`` was
constructed with ``auto_save=True``, and the code that applied "session-only,
not persisted" CLI overrides called ``Settings.set()``. So

    amca --plugin-prefix @@ --debug

permanently rewrote ``plugin_conf.json``, *including when the command then
failed with an argparse error*. Every run silently mutated the config it had
just read.

:meth:`origin` exists so ``amca config list`` can show which layer a value came
from. "I edited the JSON and nothing happened" should be a five-second question
to answer, not an afternoon.
"""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from .schema import SCHEMA, ConfigError, Field, env_name_for

__all__ = ["ConfigError", "ConfigStore", "Origin", "ResolvedValue"]

Origin = Literal["default", "file", "env", "session"]

CONFIG_FILENAME = "config.json"


@dataclass(frozen=True, slots=True)
class ResolvedValue:
    key: str
    value: Any
    origin: Origin


class ConfigStore:
    """Read-mostly view over the four layers.

    Complexity: ``get`` is O(1) (four dict probes). Construction is O(n) in the
    number of schema fields, done once per process.
    """

    __slots__ = ("_dirty", "_env", "_file", "_load_error", "_path", "_session")

    def __init__(self, path: Path, *, read_env: bool = True) -> None:
        self._path = path
        self._file: dict[str, Any] = {}
        self._env: dict[str, Any] = {}
        self._session: dict[str, Any] = {}
        self._dirty = False
        self._load_error: str | None = None

        self._load_file()
        if read_env:
            self._load_env()

    # ── Construction helpers ────────────────────────────────────────────────

    @classmethod
    def open(cls, config_dir: Path, *, read_env: bool = True) -> ConfigStore:
        return cls(config_dir / CONFIG_FILENAME, read_env=read_env)

    @property
    def path(self) -> Path:
        return self._path

    @property
    def load_error(self) -> str | None:
        """Non-None when the config file exists but could not be used."""
        return self._load_error

    def _load_file(self) -> None:
        if not self._path.exists():
            return
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8") or "{}")
        except Exception as exc:
            self._load_error = f"{self._path}: {exc}"
            return
        if not isinstance(raw, dict):
            self._load_error = f"{self._path}: top level must be an object"
            return

        flat = _flatten(raw)
        unknown = sorted(set(flat) - set(SCHEMA))
        for key in unknown:
            # Loud, not silent. An unknown key is almost always a typo or a
            # key from an older version, and silence is exactly how "I changed
            # it and nothing happened" happens.
            flat.pop(key)
        if unknown:
            self._load_error = (
                f"{self._path}: ignoring unknown key(s): {', '.join(unknown)}"
            )

        for key, value in flat.items():
            field = SCHEMA[key]
            try:
                coerced = field.coerce(value)
                field.check(coerced)
            except ConfigError as exc:
                self._load_error = f"{self._path}: {exc}"
                continue
            self._file[key] = coerced

    def _load_env(self) -> None:
        for key, field in SCHEMA.items():
            raw = os.environ.get(env_name_for(key))
            if raw is None:
                continue
            try:
                coerced = field.coerce(raw)
                field.check(coerced)
            except ConfigError:
                continue
            self._env[key] = coerced

    # ── Reads ───────────────────────────────────────────────────────────────

    def get(self, key: str) -> Any:
        return self.resolve(key).value

    def get_bool(self, key: str) -> bool:
        return bool(self.get(key))

    def get_int(self, key: str) -> int:
        return int(self.get(key))

    def get_str(self, key: str) -> str:
        return str(self.get(key))

    def get_list(self, key: str) -> list[Any]:
        value = self.get(key)
        return list(value) if isinstance(value, list) else []

    def resolve(self, key: str) -> ResolvedValue:
        field = SCHEMA.get(key)
        if field is None:
            raise KeyError(f"unknown config key: {key}")
        for layer, origin in (
            (self._session, "session"),
            (self._env, "env"),
            (self._file, "file"),
        ):
            if key in layer:
                return ResolvedValue(key, layer[key], origin)  # type: ignore[arg-type]
        return ResolvedValue(key, _copy(field.default), "default")

    def all(self) -> Iterator[ResolvedValue]:
        for key in SCHEMA:
            yield self.resolve(key)

    # ── Writes ──────────────────────────────────────────────────────────────

    def set_session(self, key: str, value: Any) -> None:
        """In-memory override for this process only. Never touches disk."""
        field = _field(key)
        coerced = field.coerce(value)
        field.check(coerced)
        self._session[key] = coerced

    def set_persistent(self, key: str, value: Any) -> None:
        """Write to the file layer. Call :meth:`save` to flush."""
        field = _field(key)
        coerced = field.coerce(value)
        field.check(coerced)
        self._file[key] = coerced
        self._dirty = True

    def unset_persistent(self, key: str) -> bool:
        _field(key)
        existed = self._file.pop(key, _MISSING) is not _MISSING
        self._dirty = self._dirty or existed
        return existed

    def save(self) -> None:
        """Atomically write the file layer. No-op when nothing changed."""
        if not self._dirty:
            return
        self._path.parent.mkdir(parents=True, exist_ok=True)
        nested = _unflatten(self._file)
        tmp_name: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                "w", encoding="utf-8", delete=False, dir=str(self._path.parent)
            ) as handle:
                tmp_name = handle.name
                json.dump(nested, handle, indent=2, ensure_ascii=False, sort_keys=True)
                handle.write("\n")
            os.replace(tmp_name, self._path)
            tmp_name = None
        finally:
            if tmp_name is not None:
                Path(tmp_name).unlink(missing_ok=True)
        self._dirty = False


class _Missing:
    __slots__ = ()


_MISSING = _Missing()


def _field(key: str) -> Field:
    field = SCHEMA.get(key)
    if field is None:
        raise KeyError(f"unknown config key: {key}")
    return field


def _copy(value: Any) -> Any:
    if isinstance(value, list):
        return list(value)
    if isinstance(value, dict):
        return dict(value)
    return value


def _flatten(data: dict[str, Any], prefix: str = "") -> dict[str, Any]:
    """Nested JSON -> dotted keys. Stops descending at a known leaf key."""
    out: dict[str, Any] = {}
    for key, value in data.items():
        dotted = f"{prefix}{key}"
        if isinstance(value, dict) and dotted not in SCHEMA:
            out.update(_flatten(value, f"{dotted}."))
        else:
            out[dotted] = value
    return out


def _unflatten(data: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for dotted, value in data.items():
        parts = dotted.split(".")
        node = out
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = value
    return out
