"""The individual pipeline steps.

Each step has the same signature and returns True to continue the pipeline.
They share one :class:`MesonProject` and one resolved ``meson`` executable
instead of each re-deriving both.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from pathlib import Path

from amca.api import PluginContext, PluginError
from amca.core import proc
from amca.core.paths import remove_tree

from .args import MesonOptions
from .project import MesonProject
from .source_cache import sources_changed

__all__ = ["STEPS", "clean"]

Step = Callable[[MesonProject, MesonOptions, PluginContext], bool]

_MESON_HINT = (
    "Fedora/RHEL   : sudo dnf install meson\n"
    "  Debian/Ubuntu : sudo apt install meson\n"
    "  any platform  : uv tool install meson\n"
    "  override path : export AMCA_TOOL_MESON=/path/to/meson"
)


def _clear_console() -> None:
    """Clear the terminal, portably.

    `cls` is a cmd.exe *builtin*, not an executable, so spawning it directly
    raises FileNotFoundError on Windows. Route it through the shell there; on
    POSIX `clear` is a real binary and may legitimately be absent, so a failure
    is not worth reporting.
    """
    if os.name == "nt":
        proc.call(["cmd", "/c", "cls"])
        return
    try:
        proc.call([proc.resolve_tool("clear", "tput")])
    except proc.ToolMissing:
        print("\033[2J\033[H", end="")


def _meson() -> str:
    return proc.resolve_tool("meson", hint=_MESON_HINT)


def _run(cmd: list[str], cwd: Path, opts: MesonOptions, ctx: PluginContext, label: str) -> bool:
    printable = " ".join(cmd)
    if ctx.dry_run:
        ctx.log.log(f"[{label}] would run: {printable}   (in {cwd})")
        return True
    ctx.log.log(f"[{label}] {printable}")
    code = proc.call(cmd, cwd=str(cwd))
    if code == 0:
        return True
    if code == 130:
        raise KeyboardInterrupt
    ctx.log.error(f"[{label}] failed (exit {code})")
    return False


# ── Steps ────────────────────────────────────────────────────────────────────

def clean(project: MesonProject, opts: MesonOptions, ctx: PluginContext) -> bool:
    """Remove the build directory and the installed binary.

    Install paths are resolved before anything is deleted — the old version
    computed the executable path from the build directory *after* deleting it
    in some orderings.
    """
    executable = project.executable_path
    install_dir = project.install_dir

    if project.build_dir.exists():
        if ctx.dry_run:
            ctx.log.log(f"[clean] would remove {project.build_dir}")
        else:
            ctx.log.log(f"[clean] removing {project.build_dir}")
            remove_tree(project.build_dir)
    else:
        ctx.log.log(f"[clean] no build dir at {project.build_dir}")

    if executable.exists():
        if ctx.dry_run:
            ctx.log.log(f"[clean] would remove {executable}")
        else:
            executable.unlink(missing_ok=True)
            ctx.log.log(f"[clean] removed {executable}")

    if (
        install_dir.exists()
        and install_dir != project.build_dir
        and not any(install_dir.iterdir())
        and not ctx.dry_run
    ):
        install_dir.rmdir()

    ctx.log.success("[clean] done")
    return True


def setup(project: MesonProject, opts: MesonOptions, ctx: PluginContext) -> bool:
    if project.build_dir.exists():
        ctx.log.log("[setup] build dir exists, skipping")
        return True
    cmd = [_meson(), "setup", str(project.build_dir), *opts.setup_args]
    return _run(cmd, project.root, opts, ctx, "setup")


def reconfigure(project: MesonProject, opts: MesonOptions, ctx: PluginContext) -> bool:
    if not project.build_dir.exists():
        ctx.log.log("[reconfigure] no build dir yet — setup will handle it")
        return True

    _sync_ide_config(project, ctx)

    if not sources_changed(project.root, ctx.plugin_dir, frozenset({project.build_dir})):
        ctx.log.log("[reconfigure] source list unchanged, skipping")
        return True

    ctx.log.log("[reconfigure] source list changed")
    cmd = [_meson(), "setup", "--reconfigure", str(project.build_dir)]
    return _run(cmd, project.root, opts, ctx, "reconfigure")


def _require_build_dir(project: MesonProject, ctx: PluginContext, label: str) -> bool:
    """False means 'skip this step'; raises only when it is a real error.

    Under --dry-run the build directory legitimately does not exist, because
    setup was also only simulated. Treating that as a failure made
    `--dry-run` abort partway through the pipeline it was supposed to preview.
    """
    if project.build_dir.exists():
        return True
    if ctx.dry_run:
        ctx.log.log(f"[{label}] would run once the build dir exists")
        return False
    raise PluginError(
        f"build directory does not exist: {project.build_dir}\n"
        f"  run setup first, or drop the -n s skip"
    )


def compile_(project: MesonProject, opts: MesonOptions, ctx: PluginContext) -> bool:
    if not _require_build_dir(project, ctx, "compile"):
        return True
    proc.resolve_tool("ninja", "ninja-build", "samu",
                      hint="meson's default backend needs ninja installed")
    cmd = [_meson(), "compile", "-j", str(opts.jobs), *opts.compile_args]
    return _run(cmd, project.build_dir, opts, ctx, "compile")


def install(project: MesonProject, opts: MesonOptions, ctx: PluginContext) -> bool:
    if not _require_build_dir(project, ctx, "install"):
        return True
    return _run([_meson(), "install"], project.build_dir, opts, ctx, "install")


def test(project: MesonProject, opts: MesonOptions, ctx: PluginContext) -> bool:
    if not _require_build_dir(project, ctx, "test"):
        return True
    cmd = [_meson(), "test", "--num-processes", str(opts.jobs)]
    if opts.verbose:
        cmd.append("--verbose")
    if not _run(cmd, project.build_dir, opts, ctx, "test"):
        return False
    ctx.log.success("[test] all tests passed")
    return True


def run(project: MesonProject, opts: MesonOptions, ctx: PluginContext) -> bool:
    executable = project.executable_path
    if not executable.exists() and ctx.dry_run:
        ctx.log.log(f"[run] would execute {executable} {' '.join(opts.exec_args)}".rstrip())
        return True
    if not executable.exists():
        raise PluginError(
            f"executable not found: {executable}\n"
            f"  has the project been compiled and installed?"
        )
    if ctx.dry_run:
        ctx.log.log(f"[run] would execute {executable} {' '.join(opts.exec_args)}")
        return True
    if opts.clear_console:
        _clear_console()
    ctx.log.log(f"[run] {executable}")
    code = proc.call([str(executable), *opts.exec_args], cwd=str(ctx.working_dir.path))
    if code == 130:
        raise KeyboardInterrupt
    if code != 0:
        ctx.log.warning(f"[run] program exited with status {code}")
    return code == 0


STEPS: dict[str, Step] = {
    "setup": setup,
    "reconfigure": reconfigure,
    "compile": compile_,
    "install": install,
    "test": test,
    "run": run,
}


# ── IDE integration ──────────────────────────────────────────────────────────

def _sync_ide_config(project: MesonProject, ctx: PluginContext) -> None:
    """Keep .vscode/launch.json and .clangd pointing at the current build."""
    if ctx.dry_run:
        return

    launch = project.root / ".vscode" / "launch.json"
    if launch.exists():
        try:
            relative = project.executable_path.relative_to(project.root)
            data = json.loads(launch.read_text(encoding="utf-8"))
            for config in data.get("configurations", []):
                config["program"] = "${workspaceFolder}/" + relative.as_posix()
            launch.write_text(json.dumps(data, indent=4) + "\n", encoding="utf-8")
            ctx.log.log("[reconfigure] updated .vscode/launch.json")
        except Exception as exc:
            ctx.log.warning(f"[reconfigure] could not update launch.json: {exc}")

    clangd = project.root / ".clangd"
    if clangd.exists():
        try:
            relative_build = project.build_dir.relative_to(project.root).as_posix()
            lines = clangd.read_text(encoding="utf-8").splitlines()
            replaced = False
            for index, line in enumerate(lines):
                if line.lstrip().startswith("CompilationDatabase:"):
                    indent = " " * (len(line) - len(line.lstrip()))
                    lines[index] = f"{indent}CompilationDatabase: {relative_build}"
                    replaced = True
            if not replaced:
                lines.append(f"CompilationDatabase: {relative_build}")
            clangd.write_text("\n".join(lines) + "\n", encoding="utf-8")
        except Exception as exc:
            ctx.log.warning(f"[reconfigure] could not update .clangd: {exc}")
