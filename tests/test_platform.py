"""Platform-specific behaviour.

amca is developed and CI-tested on Linux. These tests exercise the Windows and
macOS branches by patching ``os.name`` / ``sys.platform`` and reloading the
affected modules, so a change that breaks a non-Linux path fails here rather
than on a user's machine.

This is simulation, not a substitute for running on the real platform: it
verifies that the branches exist, are reachable, and produce the intended
commands and paths. It cannot verify that Windows itself behaves as expected.
"""

from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path

import pytest

# ── Config and state directories ─────────────────────────────────────────────

class TestPaths:
    def test_linux_uses_xdg(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from amca.core import paths

        monkeypatch.setattr(sys, "platform", "linux")
        monkeypatch.setenv("XDG_CONFIG_HOME", "/tmp/xdg")
        assert paths.default_config_dir() == Path("/tmp/xdg/amca")

    def test_linux_without_xdg(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from amca.core import paths

        monkeypatch.setattr(sys, "platform", "linux")
        monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
        assert paths.default_config_dir() == Path.home() / ".config" / "amca"

    def test_windows_uses_appdata(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from amca.core import paths

        monkeypatch.setattr(sys, "platform", "win32")
        monkeypatch.setenv("APPDATA", r"C:\Users\x\AppData\Roaming")
        assert paths.default_config_dir() == Path(r"C:\Users\x\AppData\Roaming") / "amca"

    def test_windows_without_appdata(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from amca.core import paths

        monkeypatch.setattr(sys, "platform", "win32")
        monkeypatch.delenv("APPDATA", raising=False)
        assert paths.default_config_dir().parts[-3:] == ("AppData", "Roaming", "amca")

    def test_macos_uses_application_support(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from amca.core import paths

        monkeypatch.setattr(sys, "platform", "darwin")
        expected = Path.home() / "Library" / "Application Support" / "amca"
        assert paths.default_config_dir() == expected

    def test_state_dir_is_separate_from_config_on_every_platform(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from amca.core import paths

        for platform in ("linux", "win32", "darwin"):
            monkeypatch.setattr(sys, "platform", platform)
            assert paths.default_state_dir() != paths.default_config_dir(), platform

    def test_env_override_wins_everywhere(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from amca.core import paths

        monkeypatch.setenv("AMCA_CONFIG_DIR", str(Path.cwd()))
        assert paths.config_dir() == Path.cwd().resolve()


# ── Executable naming ────────────────────────────────────────────────────────

class TestExecutableSuffix:
    TEMPLATE = (
        "amca_var__meson__version_behaviour = '2.0.1'\n"
        "amca_var__meson__build_dir         = 'build'\n"
        "amca_var__meson__executable_name   = 'app'\n"
        "amca_var__meson__install_dir       = '../out'\n"
    )

    def _project(self, tmp_path: Path):  # type: ignore[no-untyped-def]
        from amca_presets.meson._impl.project import MesonProject

        meson_file = tmp_path / "meson.build"
        meson_file.write_text(self.TEMPLATE)
        return MesonProject.load(meson_file)

    def test_posix_has_no_suffix(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(os, "name", "posix")
        assert self._project(tmp_path).executable_path.name == "app"

    def test_windows_appends_exe(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(os, "name", "nt")
        assert self._project(tmp_path).executable_path.name == "app.exe"


# ── autoscript interpreter table ─────────────────────────────────────────────

def _reload_scripts(monkeypatch: pytest.MonkeyPatch, name: str):  # type: ignore[no-untyped-def]
    """Re-import scripts.py under a pretend os.name.

    The candidate list and interpreter table are built at import time, so a
    plain monkeypatch is not enough — the module has to be re-executed.
    """
    monkeypatch.setattr(os, "name", name)
    module = importlib.import_module("amca_presets.autoscript._impl.scripts")
    return importlib.reload(module)


class TestAutoscriptPlatform:
    def test_posix_candidates(self, monkeypatch: pytest.MonkeyPatch) -> None:
        scripts = _reload_scripts(monkeypatch, "posix")
        assert "amca_auto_script" in scripts.CANDIDATES
        assert "amca_auto_script.sh" in scripts.CANDIDATES
        assert not any(c.endswith((".bat", ".ps1")) for c in scripts.CANDIDATES)

    def test_windows_candidates_exclude_extensionless(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        scripts = _reload_scripts(monkeypatch, "nt")
        # An extensionless file is not executable on Windows, so offering it
        # would only produce a confusing failure.
        assert "amca_auto_script" not in scripts.CANDIDATES
        assert "amca_auto_script.ps1" in scripts.CANDIDATES
        assert "amca_auto_script.bat" in scripts.CANDIDATES

    def test_windows_batch_goes_through_cmd(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        scripts = _reload_scripts(monkeypatch, "nt")
        script = tmp_path / "amca_auto_script.bat"
        script.write_text("@echo off\n")
        command, error = scripts.build_command(script, ["x"])
        assert error == ""
        # .bat cannot be handed to CreateProcess directly with any confidence;
        # it must be run by the command interpreter.
        assert command is not None and command[:2] == ["cmd", "/C"]
        assert command[-1] == "x"

    def test_windows_powershell_bypasses_execution_policy(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        scripts = _reload_scripts(monkeypatch, "nt")
        script = tmp_path / "amca_auto_script.ps1"
        script.write_text("")
        command, _ = scripts.build_command(script, [])
        assert command is not None
        assert "-ExecutionPolicy" in command and "Bypass" in command

    def test_posix_shell_script_gets_an_interpreter(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        scripts = _reload_scripts(monkeypatch, "posix")
        script = tmp_path / "amca_auto_script.sh"
        script.write_text("")
        command, error = scripts.build_command(script, ["a"])
        assert error == "" and command == ["sh", str(script), "a"]

    def test_posix_extensionless_needs_the_executable_bit(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        scripts = _reload_scripts(monkeypatch, "posix")
        script = tmp_path / "amca_auto_script"
        script.write_text("#!/bin/sh\n")
        script.chmod(0o644)
        command, error = scripts.build_command(script, [])
        assert command is None and "chmod" in error

    @pytest.fixture(autouse=True)
    def _restore(self) -> None:
        yield
        importlib.reload(importlib.import_module("amca_presets.autoscript._impl.scripts"))


# ── Argument splitting ───────────────────────────────────────────────────────

class TestShellSplitting:
    def test_posix_quoting(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(os, "name", "posix")
        from amca_presets.meson._impl.args import parse_args

        assert parse_args(["-Ab", "'a b' c"]).setup_args == ["a b", "c"]

    def test_windows_keeps_backslashes(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(os, "name", "nt")
        from amca_presets.meson._impl.args import parse_args

        # Non-posix shlex must not eat backslashes in a Windows path.
        result = parse_args(["-Ab", r"--prefix C:\Program"]).setup_args
        assert result == ["--prefix", r"C:\Program"]


# ── Editor default ───────────────────────────────────────────────────────────

class TestEditorDefault:
    def test_windows_defaults_to_notepad(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from amca.config.schema import default_editor

        monkeypatch.setattr(os, "name", "nt")
        monkeypatch.delenv("VISUAL", raising=False)
        monkeypatch.delenv("EDITOR", raising=False)
        assert default_editor() == "notepad"

    def test_posix_defaults_to_nano(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from amca.config.schema import default_editor

        monkeypatch.setattr(os, "name", "posix")
        monkeypatch.delenv("VISUAL", raising=False)
        monkeypatch.delenv("EDITOR", raising=False)
        assert default_editor() == "nano"

    def test_env_wins(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from amca.config.schema import default_editor

        monkeypatch.setenv("VISUAL", "hx")
        assert default_editor() == "hx"


# ── Colour detection ─────────────────────────────────────────────────────────

class _FakeTTY:
    def isatty(self) -> bool:
        return True


class TestColorDetection:
    def test_no_color_env_wins(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from amca.core.logger import supports_color

        monkeypatch.setenv("NO_COLOR", "1")
        assert supports_color(_FakeTTY()) is False  # type: ignore[arg-type]

    def test_non_tty_is_never_coloured(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from amca.core.logger import supports_color

        monkeypatch.delenv("NO_COLOR", raising=False)

        class Pipe:
            def isatty(self) -> bool:
                return False

        assert supports_color(Pipe()) is False  # type: ignore[arg-type]

    def test_windows_terminal_is_detected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from amca.core.logger import supports_color

        monkeypatch.delenv("NO_COLOR", raising=False)
        monkeypatch.setattr(os, "name", "nt")
        monkeypatch.setenv("WT_SESSION", "abc")
        # TERM is unset on Windows; the POSIX TERM check used to make this False.
        monkeypatch.delenv("TERM", raising=False)
        assert supports_color(_FakeTTY()) is True  # type: ignore[arg-type]

    def test_posix_dumb_terminal(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from amca.core.logger import supports_color

        monkeypatch.delenv("NO_COLOR", raising=False)
        monkeypatch.setattr(os, "name", "posix")
        monkeypatch.setenv("TERM", "dumb")
        assert supports_color(_FakeTTY()) is False  # type: ignore[arg-type]


# ── Path handling that must not assume a separator ───────────────────────────

class TestPathPortability:
    def test_source_cache_stores_posix_paths(self, tmp_path: Path) -> None:
        from amca_presets.meson._impl.source_cache import sources_changed

        nested = tmp_path / "a" / "b"
        nested.mkdir(parents=True)
        (nested / "x.c").write_text("")
        cache = tmp_path / "cache"
        cache.mkdir()

        assert sources_changed(tmp_path, cache) is False
        stored = (cache / "sources.cache").read_text().split()
        # Forward slashes regardless of platform, so a cache written on one
        # machine is comparable on another.
        assert stored == ["a/b/x.c"]
        assert "\\" not in (cache / "sources.cache").read_text()

    def test_root_folder_name_rejects_both_separators(self) -> None:
        from amca.config.schema import SCHEMA, ConfigError

        field = SCHEMA["root.folder_name"]
        for bad in ("a/b", r"a\b"):
            with pytest.raises(ConfigError):
                field.check(field.coerce(bad))

    def test_remove_tree_handles_a_read_only_file(self, tmp_path: Path) -> None:
        from amca.core.paths import remove_tree

        target = tmp_path / "tree"
        (target / "sub").mkdir(parents=True)
        victim = target / "sub" / "locked.txt"
        victim.write_text("x")
        victim.chmod(0o444)
        remove_tree(target)
        assert not target.exists()


# ── The meson template must not emit CRLF ────────────────────────────────────

def test_glob_script_writes_bytes_not_print() -> None:
    """print() translates \\n to \\r\\n on Windows.

    meson splits the script's stdout on '\\n', so every source path would keep
    a trailing '\\r' and resolve to nothing. Writing to the binary buffer
    bypasses newline translation.
    """
    from amca_presets.meson import plugin

    template = (Path(plugin.__file__).parent / plugin.TEMPLATE_FILE).read_text()
    assert "sys.stdout.buffer.write" in template
    # Only the comment may mention print(); no line may call it.
    calls = [
        line for line in template.splitlines()
        if "print(" in line and not line.lstrip().startswith("#")
    ]
    assert calls == [], f"template still calls print(): {calls}"
