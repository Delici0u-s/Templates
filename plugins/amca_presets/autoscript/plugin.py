"""Run a per-project shell script through amca.

Looks for ``amca_auto_script[.sh|.bash|.zsh]`` (``.ps1``/``.bat``/``.cmd`` on
Windows) in the working directory, falling back to the amca root. Everything
after the marker is forwarded to the script.

    amca ---autoscript                  run it
    amca ---autoscript build --release  run it with arguments
    amca ---autoscript --new            create one here
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from amca.api import Plugin, PluginContext, PluginError
from amca.core import proc

from ._impl.scripts import CANDIDATES, INTERPRETERS, build_command, find_script, template_for


class autoscript(Plugin):
    name = "autoscript"
    description = "runs this project's amca_auto_script"

    def should_load(self, ctx: PluginContext) -> bool:
        for directory in self._search_dirs(ctx):
            info = ctx.dirs.parse_dir(directory)
            if info.has_file(*CANDIDATES):
                return True
        # With explicit arguments the user is asking for us by name, so load
        # even with no script present — `--new` needs to reach load().
        return bool(ctx.args)

    def load(self, ctx: PluginContext) -> int:
        opts, forwarded, wants_help = _parse(ctx.args)

        if wants_help:
            print(HELP_TEXT.format(candidates=", ".join(CANDIDATES)))
            return 0

        if opts.new:
            return self._create(ctx)

        for directory in self._search_dirs(ctx):
            script, matches = find_script(directory)
            if len(matches) > 1:
                raise PluginError(
                    f"multiple auto scripts in {directory}: "
                    f"{', '.join(p.name for p in matches)} — keep exactly one"
                )
            if script is None:
                continue

            command, error = build_command(script, forwarded)
            if command is None:
                raise PluginError(error)
            if ctx.dry_run:
                ctx.log.log(f"[autoscript] would run: {' '.join(command)}")
                return 0
            # ctx.log.log(f"[autoscript] {' '.join(command)}")
            code = proc.call(command, cwd=str(ctx.working_dir.path))
            if code == 130:
                raise KeyboardInterrupt
            return code

        ctx.log.warning("no auto script found. Create one with:  amca ---autoscript --new")
        return 1

    # ── Helpers ─────────────────────────────────────────────────────────────

    @staticmethod
    def _search_dirs(ctx: PluginContext) -> list[Path]:
        """Working directory first, then the project root — closest wins."""
        directories = [ctx.working_dir.path]
        if ctx.root is not None and ctx.root.path != ctx.working_dir.path:
            directories.append(ctx.root.path)
        return directories

    def _create(self, ctx: PluginContext) -> int:
        directory = ctx.working_dir.path
        _, matches = find_script(directory)
        if matches:
            raise PluginError(f"{matches[0].name} already exists in {directory}")

        extensions = list(INTERPRETERS)
        default = ".ps1" if os.name == "nt" else ".sh"
        extension = default

        if sys.stdin.isatty():
            from amca.cli.prompt import select

            picked = select("Script type?", extensions)
            if picked is None:
                return 1
            extension = picked

        target = directory / f"amca_auto_script{extension}"
        if ctx.dry_run:
            ctx.log.log(f"[autoscript] would create {target}")
            return 0
        target.write_text(template_for(extension), encoding="utf-8")
        if os.name != "nt":
            target.chmod(target.stat().st_mode | 0o111)
        ctx.dirs.invalidate(directory)
        ctx.log.success(f"created {target}")
        return 0


HELP_TEXT = """\
usage: amca <marker>autoscript [--new] [--] [SCRIPT ARGS ...]

Runs this project's auto script, forwarding any arguments to it.

  <none>        run the script
  --new         create an auto script here (asks which shell)
  --help, -h    this message
  --            stop interpreting flags; everything after goes to the script,
                including --help and --new

Looked for in the working directory first, then the amca root:
  {candidates}
"""


def _parse(args: list[str]) -> tuple[argparse.Namespace, list[str], bool]:
    """Split our own flags from what gets forwarded to the script.

    Returns (options, forwarded, wants_help).

    Everything unrecognised belongs to the script. ``--help`` used to be part
    of "everything", so `---autoscript --help` ran the script rather than
    explaining the plugin — and with no script yet, answered a help request
    with an unrelated hint. It is now handled here; `--` still forwards it
    verbatim for scripts that take their own --help.
    """
    if "--" in args:
        index = args.index("--")
        head, tail = args[:index], args[index + 1 :]
    else:
        head, tail = args, None

    parser = argparse.ArgumentParser(add_help=False, allow_abbrev=False)
    parser.add_argument("--new", "--create", action="store_true")
    parser.add_argument("-h", "--help", dest="want_help", action="store_true")
    known, forwarded = parser.parse_known_args(head)
    if tail is not None:
        forwarded = [*forwarded, *tail]
    return known, forwarded, bool(known.want_help)
