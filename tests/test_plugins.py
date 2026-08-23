"""Plugin loading and preset behaviour."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from amca.plugins.loader import PluginLoadError, discover, load_plugin
from amca_presets.meson._impl.args import parse_args
from amca_presets.meson._impl.project import MesonProject, ProjectError

PLUGIN_SOURCE = '''
from amca.api import Plugin

class demo(Plugin):
    description = "test plugin"

    def should_load(self, ctx):
        return True

    def load(self, ctx):
        return 0
'''

LEGACY_SOURCE = '''
class old(object):
    def should_load(self, amca_root_dir, amca_root_plugin_dir, working_dir, dir_parser, args):
        return True

    def load(self, amca_root_dir, amca_root_plugin_dir, working_dir, dir_parser, args):
        return 0
'''

COLLIDING_SOURCE = '''
from amca.api import Plugin
from ._impl import MARKER

class demo(Plugin):
    description = MARKER
    def should_load(self, ctx): return True
    def load(self, ctx): return 0
'''


def _write_plugin(root: Path, name: str, body: str, *, entry: str = "plugin.py") -> None:
    directory = root / name
    directory.mkdir(parents=True)
    (directory / entry).write_text(body)


class TestDiscovery:
    def test_missing_directory_is_not_an_error(self, tmp_path: Path) -> None:
        assert discover(tmp_path / "nope") == []

    def test_finds_both_entry_filenames(self, tmp_path: Path) -> None:
        _write_plugin(tmp_path, "modern", PLUGIN_SOURCE)
        _write_plugin(tmp_path, "ancient", LEGACY_SOURCE, entry="init.py")
        assert sorted(p.folder for p in discover(tmp_path)) == ["ancient", "modern"]

    def test_dotted_and_dunder_directories_skipped(self, tmp_path: Path) -> None:
        _write_plugin(tmp_path, "__pycache__", PLUGIN_SOURCE)
        _write_plugin(tmp_path, ".hidden", PLUGIN_SOURCE)
        assert discover(tmp_path) == []


class TestLoading:
    def test_loads_and_names_from_folder(self, tmp_path: Path) -> None:
        _write_plugin(tmp_path, "demo", PLUGIN_SOURCE)
        instance = load_plugin(discover(tmp_path)[0])
        assert instance.name == "demo"
        assert instance.description == "test plugin"

    def test_legacy_five_arg_plugin_is_adapted(self, tmp_path: Path) -> None:
        _write_plugin(tmp_path, "ancient", LEGACY_SOURCE, entry="init.py")
        instance = load_plugin(discover(tmp_path)[0])
        assert "legacy" in instance.description

    def test_no_plugin_class_gives_a_named_error(self, tmp_path: Path) -> None:
        _write_plugin(tmp_path, "empty", "x = 1\n")
        with pytest.raises(PluginLoadError, match="empty"):
            load_plugin(discover(tmp_path)[0])

    def test_sys_path_is_restored(self, tmp_path: Path) -> None:
        _write_plugin(tmp_path, "demo", PLUGIN_SOURCE)
        before = list(sys.path)
        load_plugin(discover(tmp_path)[0])
        assert sys.path == before

    def test_two_plugins_with_same_submodule_name_do_not_collide(self, tmp_path: Path) -> None:
        """2.x injected each plugin's subdirectories as *top-level* modules, so
        the second plugin's `_impl` resolved to the first plugin's code."""
        for name, marker in (("alpha", "A"), ("beta", "B")):
            directory = tmp_path / name
            (directory / "_impl").mkdir(parents=True)
            (directory / "_impl" / "__init__.py").write_text(f'MARKER = "{marker}"\n')
            (directory / "plugin.py").write_text(COLLIDING_SOURCE)

        found = {p.folder: p for p in discover(tmp_path)}
        assert load_plugin(found["alpha"]).description == "A"
        assert load_plugin(found["beta"]).description == "B"


class TestBundledPresets:
    """The presets live outside src/ but must still ship and stay importable.

    Moving them from src/amca/presets/ to plugins/amca_presets/ is exactly the
    kind of change that quietly breaks packaging — a wheel that installs fine
    and then cannot find its own bundled plugins.
    """

    def test_presets_package_is_importable(self) -> None:
        import amca_presets

        assert Path(amca_presets.__file__).parent.is_dir()

    def test_builtin_source_finds_every_preset(self) -> None:
        from amca.plugins.sources import BuiltinSource

        offered = BuiltinSource().list_plugins()
        assert {"meson", "autoscript", "example"} <= set(offered), offered

    def test_presets_are_not_importable_under_amca(self) -> None:
        # A second import path to the same code is a shadowing hazard: the
        # loader imports a *copy* as amca_plugin_<name>, never this one.
        import importlib

        with pytest.raises(ImportError):
            importlib.import_module("amca.presets")

    def test_meson_template_ships_with_the_plugin(self) -> None:
        from amca.plugins.sources import BuiltinSource

        root = BuiltinSource()._root()
        assert (root / "meson" / "meson.build.template").is_file()

    def test_every_preset_has_an_entry_file(self) -> None:
        from amca.plugins.sources import BuiltinSource

        root = BuiltinSource()._root()
        for entry in root.iterdir():
            if entry.is_dir() and not entry.name.startswith(("_", ".")):
                assert (entry / "plugin.py").is_file() or (entry / "init.py").is_file(), entry


class TestMesonProject:
    TEMPLATE = """\
project('x', ['c'])
amca_var__meson__version_behaviour = '2.0.1'
amca_var__meson__build_dir         = 'build'
amca_var__meson__executable_name   = 'app'
amca_var__meson__install_dir       = '../compiled'
"""

    def test_parses(self, tmp_path: Path) -> None:
        meson_file = tmp_path / "meson.build"
        meson_file.write_text(self.TEMPLATE)
        project = MesonProject.load(meson_file)
        assert project.build_dir == (tmp_path / "build").resolve()
        assert project.executable_path.name.startswith("app")

    def test_missing_version_names_the_variable(self, tmp_path: Path) -> None:
        meson_file = tmp_path / "meson.build"
        meson_file.write_text("project('x', ['c'])\n")
        with pytest.raises(ProjectError, match="version_behaviour"):
            MesonProject.load(meson_file)

    def test_unsupported_version_is_explicit(self, tmp_path: Path) -> None:
        meson_file = tmp_path / "meson.build"
        meson_file.write_text(self.TEMPLATE.replace("2.0.1", "9.9.9"))
        with pytest.raises(ProjectError, match="9.9.9"):
            MesonProject.load(meson_file)


class TestMesonArgs:
    def test_default_pipeline_order(self) -> None:
        assert parse_args([]).steps() == [
            "setup", "reconfigure", "compile", "install", "test", "run",
        ]

    def test_skip_aliases(self) -> None:
        assert "test" not in parse_args(["-n", "t"]).steps()
        assert "run" not in parse_args(["-n", "e"]).steps()

    def test_single_mode(self) -> None:
        assert parse_args(["compile"]).steps() == ["compile"]

    def test_clean_alone_runs_nothing_else(self) -> None:
        opts = parse_args(["clean"])
        assert opts.clean is True and opts.steps() == []

    def test_dash_s_cleans_then_runs_everything(self) -> None:
        opts = parse_args(["-s"])
        assert opts.clean is True and opts.clean_then_run is True
        assert len(opts.steps()) == 6

    def test_passthrough_args_are_shell_split(self) -> None:
        opts = parse_args(["-Ab", "--buildtype=debug -Dfoo=bar"])
        assert opts.setup_args == ["--buildtype=debug", "-Dfoo=bar"]
