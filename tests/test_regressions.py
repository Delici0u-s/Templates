"""Regression tests.

Every test here corresponds to a defect that shipped in amca 2.x. They are
written as "this specific thing must never come back" rather than as coverage.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from amca.config.schema import SCHEMA, ConfigError
from amca.config.store import ConfigStore
from amca.core.context import AmcaContext
from amca.plugins.markers import UnknownMarker, split_argv


@pytest.fixture()
def store(tmp_path: Path) -> ConfigStore:
    return ConfigStore(tmp_path / "config.json", read_env=False)


# ── Marker splitting ─────────────────────────────────────────────────────────

class TestMarkers:
    """2.x split argv on `startswith(prefix)` but matched markers exactly, so
    anything in between was split off and then silently discarded."""

    def test_basic_split(self) -> None:
        result = split_argv(
            ["run", "---meson", "-s", "---autoscript", "--fast"],
            ["meson", "autoscript"], "---",
        )
        assert result.main == ["run"]
        assert result.per_plugin == {"meson": ["-s"], "autoscript": ["--fast"]}

    def test_unknown_marker_raises_instead_of_swallowing(self) -> None:
        with pytest.raises(UnknownMarker) as caught:
            split_argv(["---mesn", "-s"], ["meson"], "---")
        assert "---meson" in str(caught.value)

    def test_option_value_is_not_a_marker(self) -> None:
        # The exact 2.x failure: `--plugin-prefix @@` split on its own value.
        result = split_argv(
            ["--marker-prefix", "@@", "run", "@@meson", "-s"], ["meson"], "@@",
        )
        assert result.main == ["--marker-prefix", "@@", "run"]
        assert result.per_plugin == {"meson": ["-s"]}

    def test_underscores_become_dashes(self) -> None:
        result = split_argv(["---auto-script", "x"], ["auto_script"], "---")
        assert result.per_plugin == {"auto_script": ["x"]}

    def test_repeated_marker_appends(self) -> None:
        result = split_argv(["---meson", "a", "---meson", "b"], ["meson"], "---")
        assert result.per_plugin == {"meson": ["a", "b"]}

    def test_prefix_shaped_value_is_not_a_marker(self) -> None:
        # `amca config set plugins.marker_prefix ----` must not be read as a
        # marker: '----' is not a plausible plugin name.
        result = split_argv(["config", "set", "k", "----"], ["meson"], "---")
        assert result.main == ["config", "set", "k", "----"]
        assert result.per_plugin == {}

    def test_double_dash_stops_parsing_but_is_kept(self) -> None:
        result = split_argv(["set", "--", "---meson"], ["meson"], "---")
        assert result.main == ["set", "--", "---meson"]
        assert result.per_plugin == {}

    def test_double_dash_inside_plugin_args_is_forwarded(self) -> None:
        result = split_argv(["---meson", "--", "-x"], ["meson"], "---")
        assert result.per_plugin == {"meson": ["--", "-x"]}

    def test_unknown_marker_suggests_a_case_slip(self) -> None:
        with pytest.raises(UnknownMarker) as caught:
            split_argv(["---autoScr"], ["autoscript"], "---")
        assert "did you mean: ---autoscript" in str(caught.value)

    def test_unknown_marker_suggests_a_near_miss(self) -> None:
        with pytest.raises(UnknownMarker) as caught:
            split_argv(["---mesn"], ["meson"], "---")
        assert "did you mean: ---meson" in str(caught.value)

    def test_empty_prefix_rejected(self) -> None:
        with pytest.raises(ValueError):
            split_argv([], ["meson"], "")


# ── Config layering ──────────────────────────────────────────────────────────

class TestConfigStore:
    """2.x used Settings(auto_save=True), so every 'session-only' CLI override
    was written straight to the user's config file — including when the command
    subsequently failed."""

    def test_session_override_never_touches_disk(self, store: ConfigStore) -> None:
        store.set_session("core.debug", True)
        store.save()
        assert store.get("core.debug") is True
        assert not store.path.exists()

    def test_persistent_write_round_trips(self, store: ConfigStore) -> None:
        store.set_persistent("plugins.marker_prefix", "+++")
        store.save()
        reloaded = ConfigStore(store.path, read_env=False)
        assert reloaded.get("plugins.marker_prefix") == "+++"

    def test_precedence(self, store: ConfigStore) -> None:
        assert store.resolve("core.debug").origin == "default"
        store.set_persistent("core.debug", True)
        assert store.resolve("core.debug").origin == "file"
        store.set_session("core.debug", False)
        assert store.resolve("core.debug").origin == "session"
        assert store.get("core.debug") is False

    def test_unknown_key_is_reported_not_ignored(self, tmp_path: Path) -> None:
        path = tmp_path / "config.json"
        path.write_text(json.dumps({"plugins": {"plugin_prefix": "---"}}))
        loaded = ConfigStore(path, read_env=False)
        assert loaded.load_error is not None
        assert "plugins.plugin_prefix" in loaded.load_error

    def test_env_layer(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("AMCA_PLUGINS_MARKER_PREFIX", "@@")
        loaded = ConfigStore(tmp_path / "config.json")
        assert loaded.get("plugins.marker_prefix") == "@@"
        assert loaded.resolve("plugins.marker_prefix").origin == "env"

    def test_bad_value_rejected_at_set_time(self, store: ConfigStore) -> None:
        with pytest.raises(ConfigError):
            store.set_persistent("plugins.marker_prefix", "--")
        with pytest.raises(ConfigError):
            store.set_persistent("root.folder_name", "a/b")
        with pytest.raises(ConfigError):
            store.set_persistent("log.mode", "loud")

    def test_atomic_save_leaves_no_temp_files(self, store: ConfigStore) -> None:
        store.set_persistent("core.greet", True)
        store.save()
        assert sorted(p.name for p in store.path.parent.iterdir()) == ["config.json"]


# ── Context ──────────────────────────────────────────────────────────────────

class TestContext:
    """2.x ran root discovery at import time of impl.util.globals, so
    `amca --help` could block on an interactive prompt."""

    def test_construction_does_not_prompt_or_scan(self, tmp_path: Path) -> None:
        ctx = AmcaContext(config_dir_override=tmp_path / "cfg", cwd=tmp_path)
        assert ctx._root_done is False

    def test_root_found_from_subdirectory(self, tmp_path: Path) -> None:
        (tmp_path / ".Amca").mkdir()
        deep = tmp_path / "a" / "b" / "c"
        deep.mkdir(parents=True)
        ctx = AmcaContext(config_dir_override=tmp_path / "cfg", cwd=deep)
        root = ctx.find_root()
        assert root is not None and root.path == tmp_path.resolve()

    def test_search_depth_is_honoured(self, tmp_path: Path) -> None:
        (tmp_path / ".Amca").mkdir()
        deep = tmp_path / "a" / "b" / "c" / "d" / "e"
        deep.mkdir(parents=True)
        ctx = AmcaContext(config_dir_override=tmp_path / "cfg", cwd=deep)
        ctx.config.set_session("root.search_depth", 2)
        assert ctx.find_root() is None

    def test_non_interactive_never_blocks(self, tmp_path: Path) -> None:
        ctx = AmcaContext(config_dir_override=tmp_path / "cfg", cwd=tmp_path)
        # stdin is not a TTY under pytest, so this must return rather than read.
        assert ctx.find_root(interactive=True) is None


# ── Schema integrity ─────────────────────────────────────────────────────────

class TestSchema:
    def test_every_default_survives_its_own_validation(self) -> None:
        for key, field in SCHEMA.items():
            coerced = field.coerce(field.default)
            field.check(coerced)
            assert coerced == field.default, key

    def test_cli_flag_map_matches_schema(self) -> None:
        from amca.cli.common import FLAG_TO_KEY

        assert set(FLAG_TO_KEY.values()) <= set(SCHEMA)


# ── Interactive prompt semantics ─────────────────────────────────────────────

class TestPromptSemantics:
    """An empty confirmed selection and a cancellation are different events.

    Collapsing them made `amcapl install` + Enter exit 1 with no output.
    """

    def test_multiselect_returns_none_without_a_tty(self) -> None:
        from amca.cli.prompt import multiselect

        # pytest captures stdio, so this is the non-interactive path.
        assert multiselect("pick", ["a", "b"]) is None

    def test_multiselect_returns_none_for_empty_choices(self) -> None:
        from amca.cli.prompt import multiselect

        assert multiselect("pick", []) is None

    def test_checkbox_empty_selection_is_a_list_not_none(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from amca.cli import prompt

        class _Checkbox:
            def execute(self) -> list[str]:
                return []          # user pressed Enter having toggled nothing

        class _Inquirer:
            @staticmethod
            def checkbox(**_kwargs: object) -> _Checkbox:
                return _Checkbox()

        monkeypatch.setattr(prompt, "interactive", lambda: True)
        monkeypatch.setattr(prompt, "_inquirer", lambda: _Inquirer())
        assert prompt.multiselect("pick", ["a", "b"]) == []

    def test_checkbox_cancel_is_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from amca.cli import prompt

        class _Checkbox:
            def execute(self) -> list[str]:
                raise KeyboardInterrupt

        class _Inquirer:
            @staticmethod
            def checkbox(**_kwargs: object) -> _Checkbox:
                return _Checkbox()

        monkeypatch.setattr(prompt, "interactive", lambda: True)
        monkeypatch.setattr(prompt, "_inquirer", lambda: _Inquirer())
        assert prompt.multiselect("pick", ["a", "b"]) is None
