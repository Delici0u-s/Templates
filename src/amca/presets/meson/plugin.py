"""meson build pipeline plugin for amca.

Applies to any directory (or amca root) containing a ``meson.build`` that
carries the ``amca_var__meson__*`` declaration block.

    amca ---meson              full pipeline
    amca ---meson compile      one step
    amca ---meson -s           clean, then full pipeline
    amca ---meson -n t -n e    pipeline without test and run
"""

from __future__ import annotations

from pathlib import Path

from amca.api import Plugin, PluginContext, PluginError

from ._impl.args import PluginExit, parse_args
from ._impl.project import MesonProject, ProjectError
from ._impl.steps import STEPS, clean

TEMPLATE_FILE = "meson.build.template"


class meson(Plugin):
    name = "meson"
    description = "meson setup/compile/install/test/run pipeline"

    # ── Selection ───────────────────────────────────────────────────────────

    def should_load(self, ctx: PluginContext) -> bool:
        # Prefer the amca root when there is one, so `amca` works from a
        # subdirectory of the project. Falls back to the working directory.
        if ctx.project_dir_info().has_file("meson.build"):
            return True
        # Naming the plugin explicitly loads it even with no meson.build:
        # `---meson --print-template` exists precisely to create one, and a
        # plugin the user addressed by name should say why it cannot help
        # rather than silently not running.
        return bool(ctx.args)

    # ── Execution ───────────────────────────────────────────────────────────

    def load(self, ctx: PluginContext) -> int:
        try:
            opts = parse_args(ctx.args)
        except PluginExit as exit_request:
            code = exit_request.code
            if isinstance(code, str):
                ctx.log.error(code)
                return 2
            return int(code or 0)

        if opts.print_template:
            print(_template_text(), end="")
            return 0

        if opts.quiet:
            ctx.log.set_level("WARN")
        elif opts.verbose:
            ctx.log.set_level("INFO")
            ctx.log.set_prefix("simple")

        meson_file = ctx.project_dir / "meson.build"
        if not meson_file.is_file():
            raise PluginError(
                f"no meson.build in {ctx.project_dir}\n"
                f"  create one with:  amca ---meson --print-template > meson.build"
            )
        try:
            project = MesonProject.load(meson_file)
        except ProjectError as exc:
            raise PluginError(str(exc)) from exc

        if opts.clean and not clean(project, opts, ctx):
            return 1

        # `--clean` on its own stops here; `-s` continues into the pipeline.
        steps = opts.steps()
        if opts.clean and not opts.clean_then_run and opts.mode is None:
            return 0

        for name in steps:
            step = STEPS.get(name)
            if step is None:
                raise PluginError(f"unknown step {name!r}")
            if not step(project, opts, ctx):
                return 1
        return 0


def _template_text() -> str:
    path = Path(__file__).parent / TEMPLATE_FILE
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return "# template file missing from this plugin installation\n"
