"""Argument parsing for the meson plugin."""

from __future__ import annotations

import argparse
import os
import shlex
from dataclasses import dataclass, field

__all__ = ["STEP_NAMES", "MesonOptions", "PluginExit", "parse_args"]

VERSION = "3.0.0"

#: Pipeline order. ``clean`` is not in here — it is a prelude, controlled by
#: --clean / -s, because putting it in the list made `--skip` semantics
#: ambiguous in the old version (`-s` meant both "shorthand" and a skip token).
STEP_NAMES = ("setup", "reconfigure", "compile", "install", "test", "run")

_SKIP_ALIASES = {
    "r": "reconfigure", "reconf": "reconfigure", "reconfigure": "reconfigure",
    "c": "compile", "compile": "compile",
    "i": "install", "install": "install",
    "e": "run", "exec": "run", "run": "run",
    "t": "test", "test": "test",
    "s": "setup", "setup": "setup",
}


class PluginExit(SystemExit):
    """argparse asked to exit (``--help`` / bad flag) — not a crash."""


@dataclass(slots=True)
class MesonOptions:
    mode: str | None = None
    skip: frozenset[str] = frozenset()
    clean: bool = False
    clean_then_run: bool = False
    clear_console: bool = False
    setup_args: list[str] = field(default_factory=list)
    compile_args: list[str] = field(default_factory=list)
    exec_args: list[str] = field(default_factory=list)
    jobs: int = 0
    verbose: bool = False
    quiet: bool = False
    print_template: bool = False

    def steps(self) -> list[str]:
        if self.mode is not None:
            return [self.mode]
        return [name for name in STEP_NAMES if name not in self.skip]


class _Parser(argparse.ArgumentParser):
    """argparse that raises instead of calling sys.exit directly.

    A plugin runs inside amca's process; letting argparse call ``sys.exit``
    would take down the whole run, including any other plugin that had already
    been selected.
    """

    def exit(self, status: int = 0, message: str | None = None) -> None:  # type: ignore[override]
        if message:
            self._print_message(message, __import__("sys").stderr)
        raise PluginExit(status)

    def error(self, message: str) -> None:  # type: ignore[override]
        self.print_usage(__import__("sys").stderr)
        raise PluginExit(f"amca meson: {message}")


def _build_parser() -> argparse.ArgumentParser:
    default_jobs = os.cpu_count() or 1
    parser = _Parser(
        prog="amca ---meson",
        description="Build, install, test and run a meson project.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "pipeline (in order):  " + " -> ".join(STEP_NAMES) + "\n"
            "  naming a mode runs only that mode.\n"
            "  -n/--skip removes a step from the pipeline; repeatable.\n"
        ),
    )
    parser.add_argument("-V", "--version", action="version", version=f"%(prog)s {VERSION}")
    parser.add_argument("mode", nargs="?", choices=list(STEP_NAMES) + ["clean"],
                        help="run a single step instead of the pipeline")
    parser.add_argument("-n", "--skip", action="append", default=[],
                        choices=sorted(_SKIP_ALIASES),
                        metavar="STEP",
                        help="skip a pipeline step (r|c|i|e|t|s or the full name)")
    parser.add_argument("--clean", "--clear", dest="clean", action="store_true",
                        help="remove the build directory and installed binary")
    parser.add_argument("-s", dest="clean_then_run", action="store_true",
                        help="shorthand for --clean followed by the full pipeline")
    parser.add_argument("-c", "--clear-console", dest="clear_console", action="store_true",
                        help="clear the terminal just before running the binary")
    parser.add_argument("-Ab", "--setup-args", dest="setup_args", default="",
                        metavar='"ARGS"', help="extra arguments for `meson setup`")
    parser.add_argument("-Ac", "--compile-args", dest="compile_args", default="",
                        metavar='"ARGS"', help="extra arguments for `meson compile`")
    parser.add_argument("-Ae", "--exec-args", dest="exec_args", default="",
                        metavar='"ARGS"', help="arguments for the built binary")
    parser.add_argument("-j", "--jobs", type=int, default=default_jobs, metavar="N",
                        help=f"parallel jobs (default: {default_jobs})")
    parser.add_argument("-v", "--verbose", action="store_true")
    parser.add_argument("-q", "--quiet", action="store_true")
    parser.add_argument("--print-template", action="store_true",
                        help="print a meson.build template and exit")
    return parser


def _split(value: str) -> list[str]:
    if not value:
        return []
    try:
        return shlex.split(value, posix=os.name != "nt")
    except ValueError as exc:
        raise PluginExit(f"amca meson: malformed argument string {value!r}: {exc}")


def parse_args(argv: list[str]) -> MesonOptions:
    ns = _build_parser().parse_args(argv)
    mode = ns.mode
    clean = ns.clean or mode == "clean"
    if mode == "clean":
        mode = None
        # `meson clean` alone means clean and stop.
        return MesonOptions(mode=None, clean=True, clean_then_run=False,
                            jobs=max(1, ns.jobs), verbose=ns.verbose, quiet=ns.quiet,
                            skip=frozenset(STEP_NAMES))

    return MesonOptions(
        mode=mode,
        skip=frozenset(_SKIP_ALIASES[token] for token in ns.skip),
        clean=clean or ns.clean_then_run,
        clean_then_run=ns.clean_then_run,
        clear_console=ns.clear_console,
        setup_args=_split(ns.setup_args),
        compile_args=_split(ns.compile_args),
        exec_args=_split(ns.exec_args),
        jobs=max(1, ns.jobs),
        verbose=ns.verbose,
        quiet=ns.quiet,
        print_template=ns.print_template,
    )
