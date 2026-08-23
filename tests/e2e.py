#!/usr/bin/env python3
"""End-to-end harness for amca.

Runs the real console scripts as subprocesses against throwaway config and
project directories. Every case declares what it expects; the harness reports
each as PASS or FAIL and exits non-zero if anything fails.

Cases are grouped into "expected" interactions (the documented happy paths)
and "unexpected" ones (typos, hostile argv, broken plugins, corrupt config).
The second group matters more: 2.x failed most of them silently.

    python tests/e2e.py            # run everything
    python tests/e2e.py --verbose  # show captured output for every case
    python tests/e2e.py -k marker  # only cases whose id contains 'marker'
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

HERE = Path(__file__).resolve().parent

#: chmod-based cases only mean anything where POSIX permissions are enforced.
#: Windows ignores most mode bits, and root bypasses them entirely.
POSIX_PERMISSIONS = os.name != "nt" and getattr(os, "geteuid", lambda: 1)() != 0
FIXTURES = HERE / "fixtures"

PROBE_SOURCE = (FIXTURES / "probe" / "plugin.py").read_text(encoding="utf-8")

LEGACY_SOURCE = '''
class legacy:
    def should_load(self, amca_root_dir, amca_root_plugin_dir, working_dir, dir_parser, args):
        return True

    def load(self, amca_root_dir, amca_root_plugin_dir, working_dir, dir_parser, args):
        print("LEGACY ran with args=%r root=%r" % (args, amca_root_dir is not None))
        return 0
'''

BROKEN_SYNTAX = "def oops(:\n"
NO_PLUGIN_CLASS = "x = 1\n"
IMPORT_ERROR = "import a_module_that_does_not_exist_anywhere\n"
CONSTRUCTOR_FAILS = '''
from amca.api import Plugin

class boom(Plugin):
    def __init__(self):
        raise RuntimeError("constructor exploded")
    def should_load(self, ctx): return True
    def load(self, ctx): return 0
'''

C_MAIN = '#include <stdio.h>\nint main(void){ puts("built ok"); return 0; }\n'


# ── Result plumbing ──────────────────────────────────────────────────────────

@dataclass
class Run:
    argv: list[str]
    code: int
    out: str
    err: str

    @property
    def all(self) -> str:
        return self.out + self.err

    def probes(self) -> list[dict]:
        return [
            json.loads(line[len("PROBE "):])
            for line in self.out.splitlines()
            if line.startswith("PROBE ")
        ]

    def probe(self, name: str = "probe") -> dict | None:
        for record in self.probes():
            if record["plugin"] == name:
                return record
        return None


@dataclass
class Case:
    ident: str
    group: str
    description: str
    check: Callable[[Sandbox], list[str]]
    #: True when this exercises a mistake, hostile input, or broken component.
    unexpected: bool = False


@dataclass
class Report:
    passed: int = 0
    failed: int = 0
    failures: list[tuple[str, list[str]]] = field(default_factory=list)


# ── Sandbox ──────────────────────────────────────────────────────────────────

class Sandbox:
    """One throwaway config dir + project dir, with helpers to run amca."""

    def __init__(self, base: Path, verbose: bool = False) -> None:
        self.base = base
        self.config_dir = base / "config"
        self.state_dir = base / "state"
        self.project = base / "project"
        self.home = base / "home"
        self.project.mkdir(parents=True, exist_ok=True)
        self.verbose = verbose
        self.env_extra: dict[str, str] = {}

    # -- environment ---------------------------------------------------------

    def env(self) -> dict[str, str]:
        env = dict(os.environ)
        # Strip any AMCA_* leaking in from the outer shell so a stray export
        # cannot silently change what the matrix is testing.
        for key in [k for k in env if k.startswith(("AMCA_", "PROBE_"))]:
            env.pop(key)
        env["AMCA_CONFIG_DIR"] = str(self.config_dir)
        env["AMCA_STATE_DIR"] = str(self.state_dir)
        env["NO_COLOR"] = "1"
        # Own HOME as well: the completion commands derive XDG paths from it,
        # and no test may write into the developer's real home directory.
        self.home.mkdir(parents=True, exist_ok=True)
        env["HOME"] = str(self.home)
        env.pop("XDG_DATA_HOME", None)
        env.pop("XDG_CONFIG_HOME", None)
        env.pop("ZDOTDIR", None)
        env["SHELL"] = "/bin/bash"
        # Subprocesses are not TTYs here, so the first-run hook stays dormant
        # anyway; being explicit keeps that true if that ever changes.
        env["AMCA_NO_AUTO_COMPLETION"] = "1"
        env.update(self.env_extra)
        return env

    # -- invocation ----------------------------------------------------------

    def run(self, *argv: str, cwd: Path | None = None, stdin: str | None = None,
            timeout: int = 60) -> Run:
        command = [sys.executable, "-m", "amca.cli.amca_cli", *argv]
        return self._exec(command, argv, cwd, stdin, timeout)

    def pl(self, *argv: str, cwd: Path | None = None, stdin: str | None = None,
           timeout: int = 60) -> Run:
        command = [sys.executable, "-m", "amca.cli.amcapl_cli", *argv]
        return self._exec(command, argv, cwd, stdin, timeout)

    def _exec(self, command: list[str], argv, cwd, stdin, timeout) -> Run:
        try:
            proc = subprocess.run(
                command, cwd=str(cwd or self.project), env=self.env(),
                input=stdin if stdin is not None else "",
                capture_output=True, text=True, timeout=timeout, check=False,
            )
            result = Run(list(argv), proc.returncode, proc.stdout, proc.stderr)
        except subprocess.TimeoutExpired:
            result = Run(list(argv), -1, "", f"TIMEOUT after {timeout}s")
        if self.verbose:
            print(f"    $ amca {' '.join(argv)}  -> {result.code}")
            for line in result.all.splitlines():
                print(f"      | {line}")
        return result

    # -- fixtures ------------------------------------------------------------

    def plugins_dir(self) -> Path:
        return self.config_dir / "plugins"

    def add_plugin(self, name: str, source: str = PROBE_SOURCE,
                   entry: str = "plugin.py") -> Path:
        directory = self.plugins_dir() / name
        directory.mkdir(parents=True, exist_ok=True)
        (directory / entry).write_text(source, encoding="utf-8")
        return directory

    def add_probe(self, name: str) -> Path:
        """A probe that reports itself under *name* (marker == folder name)."""
        return self.add_plugin(name, PROBE_SOURCE.replace(
            'NAME = os.environ.get("PROBE_NAME", "probe")',
            f'NAME = os.environ.get("PROBE_NAME_OVERRIDE", "{name}")',
        ))

    def enable(self, *names: str) -> None:
        self.run("config", "set", "plugins.enabled", ",".join(names))

    def set_config(self, key: str, value: str) -> Run:
        return self.run("config", "set", key, value)

    def write_config_raw(self, text: str) -> None:
        self.config_dir.mkdir(parents=True, exist_ok=True)
        (self.config_dir / "config.json").write_text(text, encoding="utf-8")

    def make_root(self) -> None:
        self.run("new")

    def make_meson_project(self) -> None:
        (self.project / "src").mkdir(parents=True, exist_ok=True)
        (self.project / "src" / "main.c").write_text(C_MAIN, encoding="utf-8")
        template = self.run("---meson", "--print-template").out
        template = template.replace("CHANGEME", "e2e").replace("= 'a'", "= 'e2e'")
        (self.project / "meson.build").write_text(template, encoding="utf-8")


# ── Assertion helpers ────────────────────────────────────────────────────────

def expect(condition: bool, message: str) -> list[str]:
    return [] if condition else [message]


def expect_code(run: Run, want: int) -> list[str]:
    return expect(run.code == want,
                  f"exit code {run.code}, expected {want}  (argv: {run.argv})\n"
                  f"      output: {run.all.strip()[:300]}")


def expect_in(run: Run, needle: str) -> list[str]:
    return expect(needle.lower() in run.all.lower(),
                  f"missing {needle!r} in output\n      output: {run.all.strip()[:300]}")


def expect_not_in(run: Run, needle: str) -> list[str]:
    return expect(needle.lower() not in run.all.lower(),
                  f"unexpected {needle!r} in output\n      output: {run.all.strip()[:300]}")


def no_traceback(run: Run) -> list[str]:
    return expect("Traceback (most recent call last)" not in run.all,
                  f"raw traceback leaked to the user\n      {run.all.strip()[:400]}")


# ══ CASES ════════════════════════════════════════════════════════════════════

CASES: list[Case] = []


def case(ident: str, group: str, description: str, *, unexpected: bool = False):
    def decorate(fn: Callable[[Sandbox], list[str]]) -> Callable:
        CASES.append(Case(ident, group, description, fn, unexpected))
        return fn
    return decorate


# ── A. Nothing installed ─────────────────────────────────────────────────────

@case("A1", "no-plugins", "bare `amca` with an empty plugin dir warns and succeeds")
def a1(box: Sandbox) -> list[str]:
    run = box.run()
    return expect_code(run, 0) + expect_in(run, "no plugins installed") + no_traceback(run)


@case("A2", "no-plugins", "`amca plugins` lists nothing and suggests an install")
def a2(box: Sandbox) -> list[str]:
    run = box.run("plugins")
    return expect_code(run, 0) + expect_in(run, "amcapl install")


@case("A3", "no-plugins", "a marker with no plugins installed is a clean error", unexpected=True)
def a3(box: Sandbox) -> list[str]:
    run = box.run("---anything")
    return expect_code(run, 2) + expect_in(run, "unknown plugin marker") + no_traceback(run)


@case("A4", "no-plugins", "`amca --help` never blocks or prompts without a TTY")
def a4(box: Sandbox) -> list[str]:
    run = box.run("--help", timeout=10)
    return (expect_code(run, 0) + expect_in(run, "plugin passthrough")
            + expect_not_in(run, "would you like to create"))


@case("A5", "no-plugins", "`amca --version` prints a version")
def a5(box: Sandbox) -> list[str]:
    run = box.run("--version")
    return expect_code(run, 0) + expect_in(run, "amca 3.")


@case("A6", "no-plugins", "`amca doctor` runs and reports the empty plugin dir")
def a6(box: Sandbox) -> list[str]:
    run = box.run("doctor")
    return expect_in(run, "plugin dir") + no_traceback(run)


# ── B. Installed but disabled ────────────────────────────────────────────────

@case("B1", "disabled", "installed-but-disabled plugin does not run")
def b1(box: Sandbox) -> list[str]:
    box.add_probe("probe")
    run = box.run()
    return (expect_code(run, 0) + expect_in(run, "no plugins are enabled")
            + expect(run.probe("probe") is None, "disabled plugin executed anyway"))


@case("B2", "disabled", "marker for a disabled plugin is recognised, not rejected")
def b2(box: Sandbox) -> list[str]:
    box.add_probe("probe")
    run = box.run("---probe", "-x")
    return (expect_code(run, 0) + expect_not_in(run, "unknown plugin marker")
            + expect(run.probe("probe") is None, "disabled plugin executed anyway"))


@case("B3", "disabled", "`amcapl enable` then run executes it")
def b3(box: Sandbox) -> list[str]:
    box.add_probe("probe")
    enable = box.pl("enable", "probe")
    run = box.run()
    return (expect_code(enable, 0) + expect_code(run, 0)
            + expect(run.probe("probe") is not None, "plugin did not run after enable"))


# ── C. Single plugin ─────────────────────────────────────────────────────────

@case("C1", "single", "context fields are populated correctly")
def c1(box: Sandbox) -> list[str]:
    box.add_probe("probe")
    box.enable("probe")
    box.make_root()
    record = box.run().probe("probe")
    if record is None:
        return ["plugin did not run"]
    return (expect(record["root"] == str(box.project), f"root={record['root']}")
            + expect(record["working_dir"] == str(box.project), "working_dir wrong")
            + expect(record["plugin_dir_exists"], "plugin_dir was not created")
            + expect(record["args"] == [], f"args should be empty, got {record['args']}")
            + expect(record["dry_run"] is False, "dry_run should be False"))


@case("C2", "single", "arguments after the marker reach the plugin verbatim")
def c2(box: Sandbox) -> list[str]:
    box.add_probe("probe")
    box.enable("probe")
    payload = ["-x", "--long=1", "positional", "with space", "üñí", "", "-"]
    record = box.run("---probe", *payload).probe("probe")
    if record is None:
        return ["plugin did not run"]
    return expect(record["args"] == payload, f"args mangled: {record['args']!r}")


@case("C3", "single", "--dry-run reaches the plugin")
def c3(box: Sandbox) -> list[str]:
    box.add_probe("probe")
    box.enable("probe")
    record = box.run("--dry-run", "---probe").probe("probe")
    return expect(record is not None and record["dry_run"] is True, "dry_run not propagated")


@case("C4", "single", "runs from a subdirectory with root resolved upward")
def c4(box: Sandbox) -> list[str]:
    box.add_probe("probe")
    box.enable("probe")
    box.make_root()
    deep = box.project / "a" / "b" / "c"
    deep.mkdir(parents=True)
    record = box.run(cwd=deep).probe("probe")
    if record is None:
        return ["plugin did not run from subdirectory"]
    return (expect(record["root"] == str(box.project), "root not resolved upward")
            + expect(record["working_dir"] == str(deep), "working_dir should be the subdir")
            + expect(record["project_dir"] == str(box.project), "project_dir should be the root"))


@case("C5", "single", "with no root, root is None and plugin_dir is None")
def c5(box: Sandbox) -> list[str]:
    box.add_probe("probe")
    box.enable("probe")
    record = box.run().probe("probe")
    if record is None:
        return ["plugin did not run"]
    return (expect(record["root"] is None, "root should be None")
            + expect(record["plugin_dir"] is None, "plugin_dir should be None")
            + expect(record["project_dir"] == str(box.project), "project_dir should be cwd"))


@case("C6", "single", "`amca run` and bare `amca` behave identically")
def c6(box: Sandbox) -> list[str]:
    box.add_probe("probe")
    box.enable("probe")
    bare = box.run().probe("probe")
    named = box.run("run").probe("probe")
    aliased = box.run("r").probe("probe")
    return expect(bare is not None and named is not None and aliased is not None,
                  "run / r / bare are not equivalent")


@case("C7", "single", ".amca/args/<plugin>.args defaults are prepended")
def c7(box: Sandbox) -> list[str]:
    box.add_probe("probe")
    box.enable("probe")
    box.make_root()
    args_file = box.project / ".amca" / "args" / "probe.args"
    args_file.parent.mkdir(parents=True, exist_ok=True)
    args_file.write_text("# comment\n--from-file\n\n  --spaced  \n", encoding="utf-8")
    record = box.run("---probe", "--from-cli").probe("probe")
    if record is None:
        return ["plugin did not run"]
    return expect(record["args"] == ["--from-file", "--spaced", "--from-cli"],
                  f"arg-file defaults not applied correctly: {record['args']!r}")


@case("C8", "single", "should_load returning False keeps the plugin out")
def c8(box: Sandbox) -> list[str]:
    box.add_probe("probe")
    box.enable("probe")
    box.env_extra["PROBE_SHOULD_LOAD"] = "0"
    run = box.run("---probe", "-x")
    return (expect_code(run, 0)
            + expect(run.probe("probe") is None, "plugin ran despite should_load False")
            + expect_in(run, "should_load"))


# ── D. Multiple plugins ──────────────────────────────────────────────────────

@case("D1", "multi", "two enabled plugins both run")
def d1(box: Sandbox) -> list[str]:
    box.add_probe("alpha")
    box.add_probe("beta")
    box.enable("alpha", "beta")
    run = box.run()
    return (expect_code(run, 0)
            + expect(run.probe("alpha") is not None, "alpha did not run")
            + expect(run.probe("beta") is not None, "beta did not run"))


@case("D2", "multi", "arguments route to the right plugin and do not leak")
def d2(box: Sandbox) -> list[str]:
    box.add_probe("alpha")
    box.add_probe("beta")
    box.enable("alpha", "beta")
    run = box.run("---alpha", "A1", "A2", "---beta", "B1")
    alpha, beta = run.probe("alpha"), run.probe("beta")
    if alpha is None or beta is None:
        return ["one of the plugins did not run"]
    return (expect(alpha["args"] == ["A1", "A2"], f"alpha got {alpha['args']!r}")
            + expect(beta["args"] == ["B1"], f"beta got {beta['args']!r}"))


@case("D3", "multi", "with no markers at all, every applicable plugin runs")
def d3(box: Sandbox) -> list[str]:
    """Superseded in part by D7: markers now narrow the run.

    Kept because the no-marker case is the common one — `amca` on its own must
    still run everything that applies, with empty args.
    """
    box.add_probe("alpha")
    box.add_probe("beta")
    box.enable("alpha", "beta")
    run = box.run()
    alpha, beta = run.probe("alpha"), run.probe("beta")
    return (expect(alpha is not None and alpha["args"] == [], "alpha did not run")
            + expect(beta is not None and beta["args"] == [], "beta did not run"))


@case("D4", "multi", "a repeated marker accumulates rather than overwriting")
def d4(box: Sandbox) -> list[str]:
    box.add_probe("alpha")
    box.enable("alpha")
    record = box.run("---alpha", "one", "---alpha", "two").probe("alpha")
    return expect(record is not None and record["args"] == ["one", "two"],
                  f"repeated marker not accumulated: {record and record['args']!r}")


@case("D5", "multi", "underscored folder is addressed with a dash")
def d5(box: Sandbox) -> list[str]:
    box.add_probe("my_tool")
    box.enable("my_tool")
    run = box.run("---my-tool", "-x")
    record = run.probe("my_tool")
    return (expect_code(run, 0)
            + expect(record is not None and record["args"] == ["-x"],
                     "dash form of an underscored plugin name did not route"))


@case("D6", "multi", "each plugin gets its own private plugin_dir")
def d6(box: Sandbox) -> list[str]:
    box.add_probe("alpha")
    box.add_probe("beta")
    box.enable("alpha", "beta")
    box.make_root()
    run = box.run()
    alpha, beta = run.probe("alpha"), run.probe("beta")
    if alpha is None or beta is None:
        return ["one of the plugins did not run"]
    return (expect(alpha["plugin_dir"] != beta["plugin_dir"], "plugin dirs collided")
            + expect(alpha["plugin_dir_exists"] and beta["plugin_dir_exists"],
                     "plugin dirs not created"))


@case("D7", "multi", "naming a plugin runs only that plugin")
def d7(box: Sandbox) -> list[str]:
    """`amca ---meson --help` used to also execute autoscript.

    Technically correct — autoscript applied to the directory — and completely
    surprising. A marker now narrows the run.
    """
    box.add_probe("alpha")
    box.add_probe("beta")
    box.enable("alpha", "beta")
    run = box.run("---beta", "B1")
    return (expect_code(run, 0)
            + expect(run.probe("beta") is not None, "the named plugin did not run")
            + expect(run.probe("alpha") is None, "an unnamed plugin ran anyway"))


@case("D8", "multi", "plugins.marker_scope=all restores run-everything")
def d8(box: Sandbox) -> list[str]:
    box.add_probe("alpha")
    box.add_probe("beta")
    box.enable("alpha", "beta")
    box.set_config("plugins.marker_scope", "all")
    run = box.run("---beta", "B1")
    alpha = run.probe("alpha")
    return (expect(alpha is not None and alpha["args"] == [], "alpha skipped under scope=all")
            + expect(run.probe("beta") is not None, "beta skipped"))


@case("D9", "multi", "several markers select exactly those plugins")
def d9(box: Sandbox) -> list[str]:
    for name in ("alpha", "beta", "gamma"):
        box.add_probe(name)
    box.enable("alpha", "beta", "gamma")
    run = box.run("---alpha", "a", "---gamma", "g")
    return (expect(run.probe("alpha") is not None, "alpha skipped")
            + expect(run.probe("gamma") is not None, "gamma skipped")
            + expect(run.probe("beta") is None, "beta ran without being named"))


# ── E. Broken plugins (unexpected) ───────────────────────────────────────────

@case("E1", "broken", "PluginError gives a clean message and status 1", unexpected=True)
def e1(box: Sandbox) -> list[str]:
    box.add_probe("probe")
    box.enable("probe")
    box.env_extra["PROBE_RAISE"] = "plugin"
    run = box.run()
    return (expect_code(run, 1) + expect_in(run, "deliberate PluginError") + no_traceback(run))


@case("E2", "broken", "an uncaught exception is contained, not a traceback", unexpected=True)
def e2(box: Sandbox) -> list[str]:
    box.add_probe("probe")
    box.enable("probe")
    box.env_extra["PROBE_RAISE"] = "generic"
    run = box.run()
    return (expect_code(run, 1) + expect_in(run, "ValueError") + no_traceback(run))


@case("E3", "broken", "one failing plugin does not stop the others", unexpected=True)
def e3(box: Sandbox) -> list[str]:
    box.add_probe("alpha")
    box.add_probe("beta")
    box.enable("alpha", "beta")
    box.env_extra["PROBE_RAISE_ALPHA"] = "generic"
    run = box.run()
    return (expect_code(run, 1)
            + expect(run.probe("beta") is not None, "beta was skipped after alpha failed"))


@case("E4", "broken", "plugins.on_error=abort stops after the first failure", unexpected=True)
def e4(box: Sandbox) -> list[str]:
    box.add_probe("alpha")
    box.add_probe("beta")
    box.enable("alpha", "beta")
    box.set_config("plugins.on_error", "abort")
    box.env_extra["PROBE_RAISE_ALPHA"] = "generic"
    run = box.run()
    return (expect_code(run, 1)
            + expect(run.probe("beta") is None, "beta ran despite on_error=abort"))


@case("E5", "broken", "a nonzero return becomes the process exit status", unexpected=True)
def e5(box: Sandbox) -> list[str]:
    box.add_probe("probe")
    box.enable("probe")
    box.env_extra["PROBE_RETURN"] = "7"
    return expect_code(box.run(), 7)


@case("E6", "broken", "a plugin with a syntax error is reported by name", unexpected=True)
def e6(box: Sandbox) -> list[str]:
    box.add_plugin("busted", BROKEN_SYNTAX)
    box.add_probe("probe")
    box.enable("busted", "probe")
    run = box.run()
    return (expect_in(run, "busted") + no_traceback(run)
            + expect(run.probe("probe") is not None,
                     "a broken plugin prevented a healthy one from running"))


@case("E7", "broken", "a plugin importing a missing module is reported", unexpected=True)
def e7(box: Sandbox) -> list[str]:
    box.add_plugin("noimport", IMPORT_ERROR)
    box.enable("noimport")
    run = box.run()
    return expect_in(run, "noimport") + no_traceback(run)


@case("E8", "broken", "a file with no Plugin subclass is reported", unexpected=True)
def e8(box: Sandbox) -> list[str]:
    box.add_plugin("empty", NO_PLUGIN_CLASS)
    box.enable("empty")
    run = box.run()
    return expect_in(run, "no subclass") + no_traceback(run)


@case("E9", "broken", "a plugin whose constructor raises is reported", unexpected=True)
def e9(box: Sandbox) -> list[str]:
    box.add_plugin("ctor", CONSTRUCTOR_FAILS)
    box.enable("ctor")
    run = box.run()
    return expect_in(run, "ctor") + no_traceback(run)


@case("E10", "broken", "should_load raising does not abort the run", unexpected=True)
def e10(box: Sandbox) -> list[str]:
    box.add_probe("alpha")
    box.add_probe("beta")
    box.enable("alpha", "beta")
    box.env_extra["PROBE_SHOULD_RAISE_ALPHA"] = "1"
    run = box.run()
    return (expect_in(run, "should_load")
            + expect(run.probe("beta") is not None, "beta skipped after alpha's should_load raised")
            + no_traceback(run))


@case("E11", "broken", "enabled-but-missing plugin warns by default", unexpected=True)
def e11(box: Sandbox) -> list[str]:
    box.add_probe("probe")
    box.enable("probe", "ghost")
    run = box.run()
    return (expect_code(run, 0) + expect_in(run, "ghost")
            + expect(run.probe("probe") is not None, "healthy plugin skipped"))


@case("E12", "broken", "plugins.on_missing=abort refuses to run", unexpected=True)
def e12(box: Sandbox) -> list[str]:
    box.add_probe("probe")
    box.enable("probe", "ghost")
    box.set_config("plugins.on_missing", "abort")
    run = box.run()
    return expect_code(run, 1) + expect(run.probe("probe") is None, "ran despite abort")


@case("E13", "broken", "plugins.on_missing=ignore stays silent", unexpected=True)
def e13(box: Sandbox) -> list[str]:
    box.add_probe("probe")
    box.enable("probe", "ghost")
    box.set_config("plugins.on_missing", "ignore")
    run = box.run()
    return expect_code(run, 0) + expect_not_in(run, "ghost")


@case("E14", "broken", "a plugin calling sys.exit does not fake success", unexpected=True)
def e14(box: Sandbox) -> list[str]:
    box.add_probe("probe")
    box.enable("probe")
    box.env_extra["PROBE_RAISE"] = "systemexit"
    run = box.run()
    return expect(run.code != 0, f"sys.exit(43) inside a plugin produced exit {run.code}")


@case("E15", "broken", "KeyboardInterrupt inside a plugin yields 130", unexpected=True)
def e15(box: Sandbox) -> list[str]:
    box.add_probe("probe")
    box.enable("probe")
    box.env_extra["PROBE_RAISE"] = "keyboard"
    run = box.run()
    return expect_code(run, 130) + no_traceback(run)


@case("E16", "broken", "two plugins with a same-named submodule stay isolated", unexpected=True)
def e16(box: Sandbox) -> list[str]:
    body = (
        "from amca.api import Plugin\n"
        "from ._impl import MARKER\n"
        "class p(Plugin):\n"
        "    def should_load(self, ctx): return True\n"
        "    def load(self, ctx):\n"
        "        print('ISOLATION ' + MARKER); return 0\n"
    )
    for name, marker in (("alpha", "A"), ("beta", "B")):
        directory = box.add_plugin(name, body)
        (directory / "_impl").mkdir(exist_ok=True)
        (directory / "_impl" / "__init__.py").write_text(f'MARKER = "{marker}"\n')
    box.enable("alpha", "beta")
    run = box.run()
    return (expect_in(run, "ISOLATION A") + expect_in(run, "ISOLATION B"))


# ── F. Marker / argv edge cases (mostly unexpected) ──────────────────────────

@case("F1", "markers", "a mistyped marker errors and names the alternatives", unexpected=True)
def f1(box: Sandbox) -> list[str]:
    box.add_probe("probe")
    box.enable("probe")
    run = box.run("---prbe", "-x")
    return (expect_code(run, 2) + expect_in(run, "unknown plugin marker")
            + expect_in(run, "---probe") + no_traceback(run))


@case("F2", "markers", "a marker with no arguments is valid")
def f2(box: Sandbox) -> list[str]:
    box.add_probe("probe")
    box.enable("probe")
    record = box.run("---probe").probe("probe")
    return expect(record is not None and record["args"] == [], "bare marker mishandled")


@case("F3", "markers", "a session prefix override works and does not persist")
def f3(box: Sandbox) -> list[str]:
    box.add_probe("probe")
    box.enable("probe")
    before = (box.config_dir / "config.json").read_text()
    record = box.run("--marker-prefix", "@@", "@@probe", "-x").probe("probe")
    after = (box.config_dir / "config.json").read_text()
    return (expect(record is not None and record["args"] == ["-x"], "custom prefix did not route")
            + expect(before == after, "a session flag rewrote the config file"))


@case("F4", "markers", "the prefix's own value is not treated as a marker", unexpected=True)
def f4(box: Sandbox) -> list[str]:
    box.add_probe("probe")
    box.enable("probe")
    run = box.run("--marker-prefix", "@@", "run", "@@probe", "-x")
    return expect_code(run, 0) + expect_not_in(run, "unknown plugin marker")


@case("F5", "markers", "--marker-prefix=VALUE form works")
def f5(box: Sandbox) -> list[str]:
    box.add_probe("probe")
    box.enable("probe")
    record = box.run("--marker-prefix=++", "++probe", "-x").probe("probe")
    return expect(record is not None and record["args"] == ["-x"], "=form prefix failed")


@case("F6", "markers", "a prefix of '-' or '--' is rejected with a reason", unexpected=True)
def f6(box: Sandbox) -> list[str]:
    problems: list[str] = []
    for bad in ("-", "--"):
        run = box.run("--marker-prefix", bad, "run")
        problems += expect(run.code != 0, f"prefix {bad!r} was accepted")
        problems += expect_in(run, "collide")
    persist = box.set_config("plugins.marker_prefix", "--")
    problems += expect(persist.code != 0, "config set accepted a colliding prefix")
    return problems


@case("F7", "markers", "a persisted prefix change takes effect on the next run")
def f7(box: Sandbox) -> list[str]:
    box.add_probe("probe")
    box.enable("probe")
    box.set_config("plugins.marker_prefix", "+++")
    record = box.run("+++probe", "-x").probe("probe")
    stale = box.run("---probe", "-x")
    return (expect(record is not None and record["args"] == ["-x"], "new prefix not in effect")
            + expect(stale.code == 2, "the old prefix still routed after the change"))


@case("F8", "markers", "an amca flag after a marker goes to the plugin, not amca", unexpected=True)
def f8(box: Sandbox) -> list[str]:
    box.add_probe("probe")
    box.enable("probe")
    record = box.run("---probe", "--dry-run").probe("probe")
    if record is None:
        return ["plugin did not run"]
    return (expect(record["args"] == ["--dry-run"], f"args={record['args']!r}")
            + expect(record["dry_run"] is False, "amca consumed a flag meant for the plugin"))


@case("F9", "markers", "AMCA_PLUGINS_MARKER_PREFIX env var is honoured")
def f9(box: Sandbox) -> list[str]:
    box.add_probe("probe")
    box.enable("probe")
    box.env_extra["AMCA_PLUGINS_MARKER_PREFIX"] = "%%"
    record = box.run("%%probe", "-x").probe("probe")
    return expect(record is not None and record["args"] == ["-x"], "env prefix ignored")


@case("F10", "markers", "an argument that merely contains the prefix is not a marker")
def f10(box: Sandbox) -> list[str]:
    box.add_probe("probe")
    box.enable("probe")
    record = box.run("---probe", "a---b", "x---probe").probe("probe")
    return expect(record is not None and record["args"] == ["a---b", "x---probe"],
                  f"mid-token prefix mishandled: {record and record['args']!r}")


@case("F11", "markers", "a bare -- stops marker parsing for the rest of argv")
def f11(box: Sandbox) -> list[str]:
    box.add_probe("probe")
    box.enable("probe")
    # A value that both starts with the marker prefix and looks like a flag.
    run = box.run("config", "set", "plugins.marker_prefix", "--", "----")
    got = box.run("config", "get", "plugins.marker_prefix")
    return (expect_code(run, 0) + no_traceback(run)
            + expect(got.out.strip() == "----", f"value not stored: {got.out.strip()!r}"))


@case("F12", "markers", "a prefix-shaped value reaches argparse, not the marker layer",
      unexpected=True)
def f12(box: Sandbox) -> list[str]:
    box.add_probe("probe")
    box.enable("probe")
    # argparse refuses a '-'-leading positional in any CLI; the point is that
    # the *marker* layer let it through rather than claiming a bad marker.
    bare = box.run("config", "set", "core.editor", "---")
    escaped = box.run("config", "set", "core.editor", "--", "---")
    got = box.run("config", "get", "core.editor")
    return (expect_not_in(bare, "unknown plugin marker")
            + expect_code(escaped, 0)
            + expect(got.out.strip() == "---", f"value not stored: {got.out.strip()!r}"))


@case("F13", "markers", "a case-slip marker suggests the right one", unexpected=True)
def f13(box: Sandbox) -> list[str]:
    box.add_probe("autoscript")
    box.enable("autoscript")
    run = box.run("---autoScr")
    return (expect_code(run, 2) + expect_in(run, "did you mean")
            + expect_in(run, "---autoscript"))


# ── G. Config ────────────────────────────────────────────────────────────────

@case("G1", "config", "set / get / unset round-trip")
def g1(box: Sandbox) -> list[str]:
    box.set_config("plugins.marker_prefix", "+++")
    got = box.run("config", "get", "plugins.marker_prefix")
    box.run("config", "unset", "plugins.marker_prefix")
    back = box.run("config", "get", "plugins.marker_prefix")
    return (expect(got.out.strip() == "+++", f"get returned {got.out.strip()!r}")
            + expect(back.out.strip() == "---", f"unset did not restore the default: {back.out!r}"))


@case("G2", "config", "list --origin labels each layer correctly")
def g2(box: Sandbox) -> list[str]:
    box.set_config("core.debug", "true")
    box.env_extra["AMCA_LOG_LEVEL"] = "WARN"
    run = box.run("--log-mode", "silent", "config", "list", "--origin")
    problems: list[str] = []
    for key, origin in (("core.debug", "file"), ("log.level", "env"), ("log.mode", "session")):
        line = next((row for row in run.all.splitlines() if row.strip().startswith(key)), "")
        problems += expect(f"[{origin}]" in line, f"{key} labelled {line.strip()!r}, want [{origin}]")
    return problems


@case("G3", "config", "an unknown key is rejected with a suggestion", unexpected=True)
def g3(box: Sandbox) -> list[str]:
    run = box.run("config", "set", "plugin_prefix", "xyz")
    return (expect_code(run, 2) + expect_in(run, "unknown config key")
            + expect_in(run, "marker_prefix"))


@case("G4", "config", "an out-of-range or wrong-typed value is refused", unexpected=True)
def g4(box: Sandbox) -> list[str]:
    problems: list[str] = []
    for key, value in (("log.mode", "loud"), ("root.search_depth", "0"),
                       ("root.folder_name", "a/b"), ("core.debug", "maybe")):
        run = box.run("config", "set", key, value)
        problems += expect(run.code != 0, f"{key}={value!r} was accepted")
        problems += no_traceback(run)
    return problems


@case("G5", "config", "an unknown key in the JSON file is reported, not ignored", unexpected=True)
def g5(box: Sandbox) -> list[str]:
    box.write_config_raw('{"plugins": {"plugin_prefix": "@@"}}')
    run = box.run("plugins")
    return expect_in(run, "plugins.plugin_prefix") + expect_code(run, 0)


@case("G6", "config", "malformed JSON warns and falls back to defaults", unexpected=True)
def g6(box: Sandbox) -> list[str]:
    box.write_config_raw("{ this is not json ")
    run = box.run("plugins")
    return expect_code(run, 0) + expect_in(run, "config") + no_traceback(run)


@case("G7", "config", "a JSON array at the top level is refused cleanly", unexpected=True)
def g7(box: Sandbox) -> list[str]:
    box.write_config_raw("[1,2,3]")
    run = box.run("plugins")
    return expect_code(run, 0) + expect_in(run, "object") + no_traceback(run)


@case("G8", "config", "session flags never write to disk")
def g8(box: Sandbox) -> list[str]:
    box.run("config", "set", "core.greet", "false")
    before = (box.config_dir / "config.json").read_text()
    box.run("--debug", "--log-level", "ERROR", "--depth", "9", "plugins")
    box.run("--marker-prefix", "@@", "doctor")
    after = (box.config_dir / "config.json").read_text()
    return expect(before == after, "a session flag mutated config.json")


@case("G9", "config", "a failed command still writes nothing", unexpected=True)
def g9(box: Sandbox) -> list[str]:
    box.run("config", "set", "core.greet", "false")
    before = (box.config_dir / "config.json").read_text()
    box.run("--marker-prefix", "@@", "--nonsense-flag")
    box.run("---nope")
    after = (box.config_dir / "config.json").read_text()
    return expect(before == after, "a failed run mutated config.json")


@case("G10", "config", "`config describe` documents every key")
def g10(box: Sandbox) -> list[str]:
    run = box.run("config", "describe")
    return (expect_code(run, 0) + expect_in(run, "AMCA_PLUGINS_MARKER_PREFIX")
            + expect_in(run, "default :"))


@case("G11", "config", "session beats env beats file")
def g11(box: Sandbox) -> list[str]:
    box.set_config("log.level", "INFO")
    box.env_extra["AMCA_LOG_LEVEL"] = "WARN"
    env_wins = box.run("config", "get", "log.level")
    session_wins = box.run("--log-level", "FATAL", "config", "get", "log.level")
    return (expect(env_wins.out.strip() == "WARN", f"env layer lost: {env_wins.out.strip()!r}")
            + expect(session_wins.out.strip() == "FATAL",
                     f"session layer lost: {session_wins.out.strip()!r}"))


@case("G12", "config", "a read-only config directory does not crash", unexpected=True)
def g12(box: Sandbox) -> list[str]:
    if not POSIX_PERMISSIONS:
        return []
    box.run("config", "set", "core.greet", "false")
    box.config_dir.mkdir(parents=True, exist_ok=True)
    (box.config_dir / "config.json").write_text("{}")
    os.chmod(box.config_dir, 0o500)
    try:
        run = box.run("config", "set", "core.greet", "true")
        return no_traceback(run) + expect(run.code != 0 or "greet" in run.all,
                                          "silent failure on a read-only config dir")
    finally:
        os.chmod(box.config_dir, 0o700)


@case("G13", "config", "hand-editing the config file works")
def g13(box: Sandbox) -> list[str]:
    """The file is a first-class way to configure amca, not a cache."""
    box.write_config_raw(
        '{"plugins": {"marker_prefix": "+++", "enabled": ["probe"]}, '
        '"log": {"level": "WARN"}}'
    )
    box.add_probe("probe")
    record = box.run("+++probe", "-x").probe("probe")
    level = box.run("config", "get", "log.level")
    return (expect(record is not None and record["args"] == ["-x"],
                   "hand-written marker_prefix had no effect")
            + expect(level.out.strip() == "WARN", "hand-written log.level had no effect"))


@case("G14", "config", "list --origin names the env var redirecting the config dir")
def g14(box: Sandbox) -> list[str]:
    run = box.run("config", "list", "--origin")
    return expect_in(run, "AMCA_CONFIG_DIR") + expect_in(run, "config file")


@case("G15", "config", "a shell-glob marker prefix is warned about", unexpected=True)
def g15(box: Sandbox) -> list[str]:
    run = box.run("config", "set", "plugins.marker_prefix", "?")
    return expect_code(run, 0) + expect_in(run, "glob")


@case("G16", "config", "--help reflects the configured prefix, not the default")
def g16(box: Sandbox) -> list[str]:
    box.add_probe("probe")
    box.enable("probe")
    box.set_config("plugins.marker_prefix", "+++")
    run = box.run("--help")
    return (expect_in(run, "+++probe") + expect_not_in(run, "---meson")
            + expect_in(run, "Current marker prefix"))


# ── N. Shell completion ──────────────────────────────────────────────────────

@case("N1", "completion", "machine-readable plugin names and markers")
def n1(box: Sandbox) -> list[str]:
    box.add_probe("alpha")
    box.add_probe("beta")
    box.enable("alpha")
    names = box.run("plugins", "--names")
    markers = box.run("plugins", "--markers")
    enabled = box.run("plugins", "--names", "--enabled-only")
    return (expect(names.out.split() == ["alpha", "beta"], f"names: {names.out!r}")
            + expect(markers.out.split() == ["---alpha", "---beta"], f"markers: {markers.out!r}")
            + expect(enabled.out.split() == ["alpha"], f"enabled-only: {enabled.out!r}"))


@case("N2", "completion", "markers track the configured prefix")
def n2(box: Sandbox) -> list[str]:
    box.add_probe("probe")
    box.set_config("plugins.marker_prefix", "@@")
    run = box.run("plugins", "--markers")
    return expect(run.out.strip() == "@@probe", f"got {run.out!r}")


@case("N3", "completion", "config keys are listed one per line")
def n3(box: Sandbox) -> list[str]:
    run = box.run("config", "list", "--keys")
    keys = run.out.split()
    return (expect_code(run, 0)
            + expect("plugins.marker_prefix" in keys, "key list incomplete")
            + expect(all("[" not in k for k in keys), "decoration leaked into --keys"))


@case("N4", "completion", "every shell script is emitted and non-empty")
def n4(box: Sandbox) -> list[str]:
    problems: list[str] = []
    for shell in ("bash", "zsh", "fish"):
        run = box.run("completions", shell)
        problems += expect_code(run, 0)
        problems += expect(len(run.out) > 500, f"{shell} script suspiciously short")
    return problems


@case("N5", "completion", "an unknown shell is refused", unexpected=True)
def n5(box: Sandbox) -> list[str]:
    run = box.run("completions", "csh")
    return expect_code(run, 2) + no_traceback(run)


@case("N6", "completion", "helper commands work with no plugins and no config")
def n6(box: Sandbox) -> list[str]:
    """Completion runs on every Tab. It must never fail or print noise."""
    problems: list[str] = []
    for argv in (("plugins", "--names"), ("plugins", "--markers"),
                 ("config", "list", "--keys")):
        run = box.run(*argv)
        problems += expect_code(run, 0)
        problems += expect(run.err.strip() == "", f"{argv} wrote to stderr: {run.err!r}")
    return problems


@case("N13", "completion", "scripts call amca by absolute path, not by name")
def n13(box: Sandbox) -> list[str]:
    """A venv or alias install is not on PATH.

    A completion script calling a bare `amca` then returns nothing for every
    dynamic candidate, and the whole feature looks broken.
    """
    problems: list[str] = []
    for shell in ("bash", "zsh", "fish"):
        run = box.run("completions", shell)
        problems += expect(" /" in run.out or run.out.count("/amca") > 0,
                           f"{shell} script does not use an absolute helper path")
    return problems


@case("N14", "completion", "--command registers an alias exactly once")
def n14(box: Sandbox) -> list[str]:
    run = box.run("completions", "zsh", "--command", "a3")
    first = next((ln for ln in run.out.splitlines() if ln.startswith("#compdef")), "")
    return (expect("a3" in first, f"alias not registered: {first!r}")
            + expect(first.split().count("a3") == 1,
                     f"alias registered twice: {first!r}"))


@case("N7", "completion", "--status reports all three shells")
def n7(box: Sandbox) -> list[str]:
    run = box.run("completions", "--status")
    return (expect_code(run, 0) + expect_in(run, "bash")
            + expect_in(run, "zsh") + expect_in(run, "fish")
            + expect_in(run, "not installed"))


@case("N8", "completion", "--install writes to the per-user directory")
def n8(box: Sandbox) -> list[str]:
    run = box.run("completions", "bash", "--install")
    target = box.home / ".local" / "share" / "bash-completion" / "completions" / "amca"
    sibling = target.with_name("amcapl")
    return (expect_code(run, 0)
            + expect(target.is_file(), f"not written to {target}")
            + expect(sibling.is_file(), "amcapl completion missing")
            + expect(len(target.read_text()) > 500, "written script is too short"))


@case("N9", "completion", "--install is idempotent and --uninstall reverses it")
def n9(box: Sandbox) -> list[str]:
    box.run("completions", "bash", "--install")
    again = box.run("completions", "bash", "--install")
    removed = box.run("completions", "bash", "--uninstall")
    target = box.home / ".local" / "share" / "bash-completion" / "completions" / "amca"
    return (expect_in(again, "already up to date")
            + expect_code(removed, 0)
            + expect(not target.exists(), "file survived --uninstall"))


@case("N10", "completion", "--install --rc adds a removable block to .zshrc")
def n10(box: Sandbox) -> list[str]:
    box.run("completions", "zsh", "--install", "--rc")
    zshrc = box.home / ".zshrc"
    if not zshrc.exists():
        return ["--rc did not create .zshrc"]
    with_block = zshrc.read_text()
    box.run("completions", "zsh", "--uninstall")
    after = zshrc.read_text()
    return (expect("fpath=" in with_block, "no fpath line added")
            + expect(">>> amca completion >>>" in with_block, "block not delimited")
            + expect("amca completion" not in after, "block survived --uninstall")
            + expect(zshrc.exists(), "--uninstall deleted .zshrc entirely"))


@case("N11", "completion", "--rc preserves the rest of the rc file", unexpected=True)
def n11(box: Sandbox) -> list[str]:
    box.home.mkdir(parents=True, exist_ok=True)
    zshrc = box.home / ".zshrc"
    zshrc.write_text("export MY_THING=1\nalias ll='ls -l'\n")
    box.run("completions", "zsh", "--install", "--rc")
    box.run("completions", "zsh", "--uninstall")
    after = zshrc.read_text()
    return (expect("MY_THING" in after, "amca clobbered an unrelated rc line")
            + expect("alias ll=" in after, "amca clobbered an unrelated rc line"))


@case("N12", "completion", "the first-run hook never fires in a non-TTY")
def n12(box: Sandbox) -> list[str]:
    env = dict(box.env_extra)
    box.env_extra.pop("AMCA_NO_AUTO_COMPLETION", None)
    run = box.run("plugins")
    box.env_extra = env
    installed = (box.home / ".local" / "share").exists()
    return (expect_not_in(run, "tab-completion")
            + expect(not installed, "wrote completion files without a terminal"))


# ── H. Legacy plugin API ─────────────────────────────────────────────────────

@case("H1", "legacy", "a 2.x five-argument plugin still loads and runs")
def h1(box: Sandbox) -> list[str]:
    box.add_plugin("oldstyle", LEGACY_SOURCE, entry="init.py")
    box.enable("oldstyle")
    box.make_root()
    run = box.run("---oldstyle", "keep", "these")
    return (expect_code(run, 0) + expect_in(run, "LEGACY ran")
            + expect_in(run, "['keep', 'these']"))


@case("H2", "legacy", "legacy and modern plugins coexist")
def h2(box: Sandbox) -> list[str]:
    box.add_plugin("oldstyle", LEGACY_SOURCE, entry="init.py")
    box.add_probe("probe")
    box.enable("oldstyle", "probe")
    run = box.run()
    return (expect_in(run, "LEGACY ran")
            + expect(run.probe("probe") is not None, "modern plugin skipped"))


# ── I. amcapl ────────────────────────────────────────────────────────────────

@case("I1", "amcapl", "install from builtin works offline and enables")
def i1(box: Sandbox) -> list[str]:
    run = box.pl("install", "meson", "--source", "builtin")
    listing = box.pl("list")
    return (expect_code(run, 0) + expect_in(run, "installed from builtin")
            + expect_in(listing, "enabled"))


@case("I2", "amcapl", "installing an unknown plugin fails cleanly", unexpected=True)
def i2(box: Sandbox) -> list[str]:
    run = box.pl("install", "does-not-exist", "--source", "builtin")
    return expect(run.code != 0, "unknown plugin install reported success") + no_traceback(run)


@case("I3", "amcapl", "reinstalling without --force is refused", unexpected=True)
def i3(box: Sandbox) -> list[str]:
    box.pl("install", "meson", "--source", "builtin")
    run = box.pl("install", "meson", "--source", "builtin")
    return expect_in(run, "already installed") + no_traceback(run)


@case("I4", "amcapl", "enable / disable / toggle round-trip")
def i4(box: Sandbox) -> list[str]:
    box.add_probe("probe")
    box.pl("enable", "probe")
    on = box.run().probe("probe")
    box.pl("disable", "probe")
    off = box.run().probe("probe")
    box.pl("toggle", "probe")
    back = box.run().probe("probe")
    return (expect(on is not None, "enable failed")
            + expect(off is None, "disable failed")
            + expect(back is not None, "toggle failed"))


@case("I5", "amcapl", "uninstall removes the folder and the enabled entry")
def i5(box: Sandbox) -> list[str]:
    box.add_probe("probe")
    box.pl("enable", "probe")
    run = box.pl("uninstall", "probe", "-y")
    enabled = box.run("config", "get", "plugins.enabled")
    return (expect_code(run, 0)
            + expect(not (box.plugins_dir() / "probe").exists(), "folder still present")
            + expect("probe" not in enabled.out, "still listed as enabled"))


@case("I6", "amcapl", "`amcapl call` runs a plugin ignoring should_load")
def i6(box: Sandbox) -> list[str]:
    box.add_probe("probe")
    box.env_extra["PROBE_SHOULD_LOAD"] = "0"
    run = box.pl("call", "probe", "--", "forced")
    record = run.probe("probe")
    return (expect_code(run, 0)
            + expect(record is not None and record["args"] == ["forced"],
                     f"call did not forward args: {record and record['args']!r}"))


@case("I7", "amcapl", "calling an unknown plugin fails cleanly", unexpected=True)
def i7(box: Sandbox) -> list[str]:
    run = box.pl("call", "ghost")
    return expect_code(run, 2) + expect_in(run, "ghost") + no_traceback(run)


@case("I8", "amcapl", "enabling an unknown plugin is refused", unexpected=True)
def i8(box: Sandbox) -> list[str]:
    run = box.pl("enable", "ghost")
    return expect(run.code != 0, "enabled a plugin that is not installed") + no_traceback(run)


@case("I9", "amcapl", "`amcapl list --available` degrades when a source is unreachable",
      unexpected=True)
def i9(box: Sandbox) -> list[str]:
    box.set_config("plugins.sources", "builtin,github:nope/nope@main:x")
    run = box.pl("list", "--available", timeout=60)
    return expect_code(run, 0) + expect_in(run, "meson") + no_traceback(run)


@case("I10", "amcapl", "a garbage source string is skipped with a warning", unexpected=True)
def i10(box: Sandbox) -> list[str]:
    box.set_config("plugins.sources", "builtin,::not a source::")
    run = box.pl("list", "--available")
    return expect_code(run, 0) + expect_in(run, "meson") + no_traceback(run)


@case("I11", "amcapl", "no interactive command exits silently", unexpected=True)
def i11(box: Sandbox) -> list[str]:
    """Every picker-driven command must say something on every path.

    `amcapl install` with an empty selection used to exit 1 printing nothing,
    which is indistinguishable from a crash.
    """
    problems: list[str] = []
    for argv in (("install",), ("enable",), ("disable",), ("toggle",), ("uninstall",)):
        run = box.pl(*argv)
        problems += expect(run.all.strip() != "",
                           f"`amcapl {' '.join(argv)}` produced no output at all")
        problems += no_traceback(run)
    return problems


@case("I12", "amcapl", "picker commands explain themselves with a plugin installed")
def i12(box: Sandbox) -> list[str]:
    box.add_probe("probe")
    enable_all = box.pl("enable", "probe")
    again = box.pl("enable")
    return (expect_code(enable_all, 0)
            + expect_in(again, "already enabled")
            + expect_code(again, 0))


# ── J. Roots ─────────────────────────────────────────────────────────────────

@case("J1", "root", "new / show / remove lifecycle")
def j1(box: Sandbox) -> list[str]:
    created = box.run("new")
    shown = box.run("root", "show")
    removed = box.run("remove", "-y")
    gone = box.run("root", "show")
    return (expect_code(created, 0) + expect_code(shown, 0)
            + expect_code(removed, 0) + expect_code(gone, 1))


@case("J2", "root", "`amca new` twice is idempotent, not an error")
def j2(box: Sandbox) -> list[str]:
    box.run("new")
    run = box.run("new")
    return expect_code(run, 0) + expect_in(run, "already")


@case("J3", "root", "root.search_depth is honoured")
def j3(box: Sandbox) -> list[str]:
    box.make_root()
    deep = box.project / "a" / "b" / "c" / "d" / "e"
    deep.mkdir(parents=True)
    far = box.run("root", "show", cwd=deep)
    near = box.run("--depth", "2", "root", "show", cwd=deep)
    return (expect_code(far, 1) + expect_code(near, 1)
            + expect_code(box.run("--depth", "9", "root", "show", cwd=deep), 0))


@case("J4", "root", "non-interactive run never blocks on the create-root prompt")
def j4(box: Sandbox) -> list[str]:
    box.add_probe("probe")
    box.enable("probe")
    run = box.run(timeout=10)
    return (expect_code(run, 0) + expect_not_in(run, "would you like")
            + expect(not (box.project / ".amca").exists(), "a root was created unprompted"))


@case("J5", "root", "root ignore / unignore / clear-ignored")
def j5(box: Sandbox) -> list[str]:
    ignore = box.run("root", "ignore")
    listed = box.run("config", "get", "root.ignored_paths")
    box.run("root", "unignore")
    cleared = box.run("root", "clear-ignored")
    after = box.run("config", "get", "root.ignored_paths")
    return (expect_code(ignore, 0) + expect(str(box.project) in listed.out, "not recorded")
            + expect_code(cleared, 0) + expect("[]" in after.out, "not cleared"))


# ── K. Real meson project ────────────────────────────────────────────────────

@case("K1", "meson", "full pipeline builds, installs and runs a real C project")
def k1(box: Sandbox) -> list[str]:
    if shutil.which("meson") is None or shutil.which("ninja") is None:
        return []
    box.pl("install", "meson", "--source", "builtin")
    box.make_meson_project()
    run = box.run(timeout=180)
    return expect_code(run, 0) + expect_in(run, "built ok")


@case("K2", "meson", "a single mode runs only that step")
def k2(box: Sandbox) -> list[str]:
    if shutil.which("meson") is None:
        return []
    box.pl("install", "meson", "--source", "builtin")
    box.make_meson_project()
    run = box.run("---meson", "setup", timeout=120)
    return (expect_code(run, 0) + expect_not_in(run, "built ok")
            + expect((box.project / "build").is_dir(), "build dir not created"))


@case("K3", "meson", "-n skips the named steps")
def k3(box: Sandbox) -> list[str]:
    if shutil.which("meson") is None:
        return []
    box.pl("install", "meson", "--source", "builtin")
    box.make_meson_project()
    run = box.run("---meson", "-n", "e", "-n", "t", timeout=180)
    return expect_code(run, 0) + expect_not_in(run, "built ok")


@case("K4", "meson", "--dry-run changes nothing on disk")
def k4(box: Sandbox) -> list[str]:
    if shutil.which("meson") is None:
        return []
    box.pl("install", "meson", "--source", "builtin")
    box.make_meson_project()
    run = box.run("--dry-run", "---meson", timeout=120)
    return (expect_code(run, 0) + expect_in(run, "would run")
            + expect(not (box.project / "build").exists(), "dry run created the build dir"))


@case("K5", "meson", "a meson.build without amca variables is a clean error", unexpected=True)
def k5(box: Sandbox) -> list[str]:
    box.pl("install", "meson", "--source", "builtin")
    (box.project / "meson.build").write_text("project('x', ['c'])\n", encoding="utf-8")
    run = box.run(timeout=60)
    return (expect_code(run, 1) + expect_in(run, "version_behaviour") + no_traceback(run))


@case("K6", "meson", "an unsupported template version is named", unexpected=True)
def k6(box: Sandbox) -> list[str]:
    box.pl("install", "meson", "--source", "builtin")
    box.make_meson_project()
    text = (box.project / "meson.build").read_text().replace("'2.0.1'", "'9.9.9'")
    (box.project / "meson.build").write_text(text, encoding="utf-8")
    run = box.run(timeout=60)
    return expect_code(run, 1) + expect_in(run, "9.9.9") + no_traceback(run)


@case("K7", "meson", "meson missing from PATH gives an actionable message", unexpected=True)
def k7(box: Sandbox) -> list[str]:
    box.pl("install", "meson", "--source", "builtin")
    box.make_meson_project()
    box.env_extra["AMCA_TOOL_MESON"] = "/definitely/not/here/meson"
    run = box.run(timeout=60)
    return (expect(run.code != 0, "missing meson reported success")
            + expect_in(run, "meson") + no_traceback(run))


@case("K8", "meson", "meson does not load in a directory with no meson.build")
def k8(box: Sandbox) -> list[str]:
    box.pl("install", "meson", "--source", "builtin")
    run = box.run()
    return expect_code(run, 0) + expect_not_in(run, "[setup]")


@case("K9", "meson", "--print-template emits a usable template")
def k9(box: Sandbox) -> list[str]:
    box.pl("install", "meson", "--source", "builtin")
    run = box.run("---meson", "--print-template")
    return (expect_code(run, 0) + expect_in(run, "amca_var__meson__version_behaviour")
            + expect_in(run, "executable("))


@case("K10", "meson", "the meson plugin's --help does not exit amca uncleanly")
def k10(box: Sandbox) -> list[str]:
    box.pl("install", "meson", "--source", "builtin")
    run = box.run("---meson", "--help")
    return expect_code(run, 0) + expect_in(run, "pipeline") + no_traceback(run)


@case("K11", "meson", "an invalid meson flag is reported, not a traceback", unexpected=True)
def k11(box: Sandbox) -> list[str]:
    box.pl("install", "meson", "--source", "builtin")
    box.make_meson_project()
    run = box.run("---meson", "--no-such-flag")
    return expect(run.code != 0, "bad flag accepted") + no_traceback(run)


# ── L. autoscript ────────────────────────────────────────────────────────────

@case("L1", "autoscript", "runs the project script and forwards arguments")
def l1(box: Sandbox) -> list[str]:
    if os.name == "nt":
        return []
    box.pl("install", "autoscript", "--source", "builtin")
    script = box.project / "amca_auto_script.sh"
    script.write_text('#!/usr/bin/env sh\necho "SCRIPT got: $*"\n', encoding="utf-8")
    script.chmod(0o755)
    run = box.run("---autoscript", "alpha", "--beta")
    return expect_code(run, 0) + expect_in(run, "SCRIPT got: alpha --beta")


@case("L2", "autoscript", "a failing script propagates its exit status", unexpected=True)
def l2(box: Sandbox) -> list[str]:
    if os.name == "nt":
        return []
    box.pl("install", "autoscript", "--source", "builtin")
    script = box.project / "amca_auto_script.sh"
    script.write_text("#!/usr/bin/env sh\nexit 9\n", encoding="utf-8")
    script.chmod(0o755)
    return expect_code(box.run(), 9)


@case("L3", "autoscript", "two competing scripts are reported as ambiguous", unexpected=True)
def l3(box: Sandbox) -> list[str]:
    if os.name == "nt":
        return []
    box.pl("install", "autoscript", "--source", "builtin")
    for suffix in (".sh", ".bash"):
        path = box.project / f"amca_auto_script{suffix}"
        path.write_text("#!/usr/bin/env sh\ntrue\n", encoding="utf-8")
        path.chmod(0o755)
    run = box.run()
    return expect_code(run, 1) + expect_in(run, "multiple") + no_traceback(run)


@case("L4", "autoscript", "does not load where there is no script")
def l4(box: Sandbox) -> list[str]:
    box.pl("install", "autoscript", "--source", "builtin")
    run = box.run()
    return expect_code(run, 0) + expect_not_in(run, "[autoscript]")


@case("L5", "autoscript", "--help describes the plugin instead of running the script")
def l5(box: Sandbox) -> list[str]:
    if os.name == "nt":
        return []
    box.pl("install", "autoscript", "--source", "builtin")
    script = box.project / "amca_auto_script.sh"
    script.write_text('#!/usr/bin/env sh\necho "SCRIPT RAN"\n', encoding="utf-8")
    script.chmod(0o755)
    run = box.run("---autoscript", "--help")
    return (expect_code(run, 0) + expect_in(run, "usage:")
            + expect_not_in(run, "SCRIPT RAN"))


@case("L6", "autoscript", "a bare -- forwards everything to the script")
def l6(box: Sandbox) -> list[str]:
    if os.name == "nt":
        return []
    box.pl("install", "autoscript", "--source", "builtin")
    script = box.project / "amca_auto_script.sh"
    script.write_text('#!/usr/bin/env sh\necho "SCRIPT GOT: $*"\n', encoding="utf-8")
    script.chmod(0o755)
    run = box.run("---autoscript", "--", "--help", "--new")
    return expect_code(run, 0) + expect_in(run, "SCRIPT GOT: --help --new")


@case("L7", "autoscript", "--help works before any script exists")
def l7(box: Sandbox) -> list[str]:
    box.pl("install", "autoscript", "--source", "builtin")
    run = box.run("---autoscript", "--help")
    return (expect_code(run, 0) + expect_in(run, "usage:")
            + expect_not_in(run, "no auto script found"))


# ── P. The bundled example plugin ────────────────────────────────────────────

@case("P1", "example", "the example preset installs and runs")
def p1(box: Sandbox) -> list[str]:
    install = box.pl("install", "example", "--source", "builtin")
    run = box.run("---example", "hello")
    return (expect_code(install, 0) + expect_code(run, 0)
            + expect_in(run, "example plugin ran with"))


@case("P2", "example", "the example documents every context field")
def p2(box: Sandbox) -> list[str]:
    box.pl("install", "example", "--source", "builtin")
    box.make_root()
    run = box.run("---example", "--show")
    problems = expect_code(run, 0)
    for name in ("args", "working_dir", "root", "project_dir", "plugin_dir", "dry_run"):
        problems += expect_in(run, name)
    return problems


@case("P3", "example", "the example's PluginError path is clean", unexpected=True)
def p3(box: Sandbox) -> list[str]:
    box.pl("install", "example", "--source", "builtin")
    run = box.run("---example", "--fail")
    return expect_code(run, 1) + expect_in(run, "clean failure") + no_traceback(run)


@case("P4", "example", "the example stays out of the way when not addressed")
def p4(box: Sandbox) -> list[str]:
    box.pl("install", "example", "--source", "builtin")
    run = box.run()
    return expect_code(run, 0) + expect_not_in(run, "example plugin ran")


# ── M. Interpreter / environment hygiene ─────────────────────────────────────

@case("M1", "env", "subprocesses see a clean library path")
def m1(box: Sandbox) -> list[str]:
    body = (
        "import os, subprocess, sys\n"
        "from amca.api import Plugin\n"
        "from amca.core import proc\n"
        "class envprobe(Plugin):\n"
        "    def should_load(self, ctx): return True\n"
        "    def load(self, ctx):\n"
        "        code, out, err = proc.capture([sys.executable, '-c',\n"
        "            'import binascii, sys; print(sys.version.split()[0])'])\n"
        "        print('CHILD %d %s' % (code, out.strip()))\n"
        "        return code\n"
    )
    box.add_plugin("envprobe", body)
    box.enable("envprobe")
    run = box.run()
    return expect_code(run, 0) + expect_in(run, "CHILD 0")


@case("M2", "env", "doctor reports no problems on a healthy install")
def m2(box: Sandbox) -> list[str]:
    box.add_probe("probe")
    box.enable("probe")
    box.make_root()
    run = box.run("doctor")
    return expect_code(run, 0) + expect_in(run, "No problems found")


@case("M3", "env", "doctor exits non-zero when a plugin is broken", unexpected=True)
def m3(box: Sandbox) -> list[str]:
    box.add_plugin("busted", BROKEN_SYNTAX)
    box.enable("busted")
    run = box.run("doctor")
    return expect_code(run, 1) + expect_in(run, "problem")


@case("M4", "env", "log.mode=silent suppresses plugin logging but not plugin stdout")
def m4(box: Sandbox) -> list[str]:
    box.add_probe("probe")
    box.enable("probe")
    run = box.run("--log-mode", "silent", "---probe", "-x")
    return (expect(run.probe("probe") is not None, "plugin stdout was suppressed")
            + expect_not_in(run, "[WARN]"))


@case("M5", "env", "an unreadable working directory does not crash", unexpected=True)
def m5(box: Sandbox) -> list[str]:
    if not POSIX_PERMISSIONS:
        return []
    box.add_probe("probe")
    box.enable("probe")
    locked = box.project / "locked"
    locked.mkdir()
    os.chmod(locked, 0o000)
    try:
        run = box.run(cwd=box.project, timeout=20)
        return expect_code(run, 0) + no_traceback(run)
    finally:
        os.chmod(locked, 0o700)


# ── Runner ───────────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(description="amca end-to-end matrix")
    parser.add_argument("-k", dest="filter", default="",
                        help="only run cases whose id, group or description matches")
    parser.add_argument("--verbose", "-v", action="store_true")
    parser.add_argument("--list", action="store_true", help="print the matrix and exit")
    args = parser.parse_args()

    selected = [
        case for case in CASES
        if not args.filter
        or args.filter.lower() in f"{case.ident} {case.group} {case.description}".lower()
    ]

    if args.list:
        for case in selected:
            kind = "unexpected" if case.unexpected else "expected  "
            print(f"{case.ident:<5} {kind}  {case.group:<11} {case.description}")
        return 0

    report = Report()
    current_group = ""
    for case in selected:
        if case.group != current_group:
            current_group = case.group
            print(f"\n── {current_group} " + "─" * (58 - len(current_group)))
        with tempfile.TemporaryDirectory(prefix=f"amca-e2e-{case.ident}-") as tmp:
            box = Sandbox(Path(tmp), verbose=args.verbose)
            try:
                problems = case.check(box)
            except Exception as exc:  # harness bug, not an amca bug
                problems = [f"harness error: {type(exc).__name__}: {exc}"]
        marker = "!" if case.unexpected else " "
        if problems:
            report.failed += 1
            report.failures.append((case.ident, problems))
            print(f"  FAIL{marker} {case.ident:<5} {case.description}")
            for problem in problems:
                print(f"        - {problem}")
        else:
            report.passed += 1
            print(f"  pass{marker} {case.ident:<5} {case.description}")

    total = report.passed + report.failed
    print("\n" + "═" * 66)
    print(f"  {report.passed}/{total} passed"
          + (f", {report.failed} FAILED" if report.failed else ""))
    print("  ('!' marks a case that exercises a mistake or a broken component)")
    return 1 if report.failed else 0


if __name__ == "__main__":
    sys.exit(main())
