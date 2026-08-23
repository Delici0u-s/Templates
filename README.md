# Amca

Directory-aware auto-executer. Run `amca` anywhere and it works out what that
directory *is* — a meson project, a directory with a build script — and runs the
right pipeline. Behaviour comes from plugins; amca itself just decides which
ones apply.

```
$ cd ~/code/thing        # contains meson.build
$ amca                   # setup -> reconfigure -> compile -> install -> test -> run
$ amca ---meson -s       # clean first, then the whole pipeline
$ amca ---meson compile  # just one step
```

---

## Install

Amca is a normal Python package with two console scripts. Install it as a
**tool**, not into a project environment:

```bash
uv tool install --python 3.13 git+https://github.com/Delici0u-s/Amca
```

`--python` pins a `uv`-managed interpreter, so a distro Python upgrade cannot
break amca. Alternatively:

```bash
pipx install git+https://github.com/Delici0u-s/Amca
pip install --user git+https://github.com/Delici0u-s/Amca   # works, less isolated
```

Optional extras:

| extra | what it buys | without it |
|---|---|---|
| `tui` | arrow-key pickers (InquirerPy) | numbered stdin prompts |
| `remote` | `amcapl install` from GitHub (requests) | `builtin` source only |
| `all` | both | |

```bash
uv tool install --with 'amca[all]' --python 3.13 git+https://github.com/Delici0u-s/Amca
```

There are **no required runtime dependencies**. A broken optional wheel can
degrade a feature; it can never stop amca from starting.

### Upgrading

```bash
uv tool upgrade amca        # or: pipx reinstall amca
```

That is the whole maintenance story. There is no build step, no venv to
rebuild, no binary to recompile after a system update.

### From a checkout

```bash
git clone https://github.com/Delici0u-s/Amca && cd Amca
uv tool install --editable .     # or: pip install -e '.[all,dev]'
```

---

## First run

```bash
amcapl install meson autoscript   # from the copies bundled in the wheel, offline
amca new                          # mark the current directory as a project root
amca                              # run whatever applies
```

`amca new` creates `.Amca/` holding per-project plugin state and argument files.
It is optional — without a root, amca uses the current directory.

---

## Commands

### `amca`

| | |
|---|---|
| `amca` / `amca run` | run every enabled plugin whose `should_load` matches |
| `amca new` / `amca remove` | create / delete the `.Amca` root |
| `amca root show\|ignore\|unignore\|clear-ignored` | root detection |
| `amca args [PLUGIN]` | edit this project's default arguments for a plugin |
| `amca plugins` | installed plugins and their markers |
| `amca config …` | see below |
| `amca doctor` | check tools, paths, plugin health, subprocess environment |

### `amcapl`

| | |
|---|---|
| `amcapl list [--available]` | what is installed / what sources offer |
| `amcapl install NAME…` | fetch and enable |
| `amcapl enable\|disable\|toggle [NAME…]` | omit names for a picker |
| `amcapl uninstall NAME…` | delete from disk |
| `amcapl update [NAME…]` | re-fetch (`*` or nothing = all) |
| `amcapl call NAME -- ARGS` | run one plugin directly, skipping `should_load` |

---

## Plugin markers

Arguments after `---name` go to that plugin, until the next marker:

```bash
amca ---meson -s -j8 ---autoscript deploy --dry
```

Markers are `plugins.marker_prefix` (default `---`) plus the plugin's folder
name, with underscores written as dashes. `amca plugins` prints them.

**An unrecognised marker is an error.** It names what it expected. The old
version split argv on the prefix and then silently discarded anything that
was not an exact match, so a typo made your arguments vanish with no output.

A bare `--` stops marker parsing, for the rare case of a value that starts
with the prefix:

```bash
amca config set plugins.marker_prefix -- +++
```

Per-project defaults live in `.Amca/args/<plugin>.args`, one argument per line,
`#` for comments. They are prepended to whatever you type. Edit with
`amca args meson`.

---

## Configuration

One file, `$XDG_CONFIG_HOME/amca/config.json` (`amca config path` prints it).
Four layers, lowest priority first:

```
built-in default  ->  config file  ->  AMCA_* env var  ->  command-line flag
```

**Only `amca config set` writes to disk.** Command-line flags are in-memory for
that run and nothing else.

```bash
amca config list --origin          # every setting, its value, and which layer won
amca config list --changed         # only what differs from the defaults
amca config get plugins.marker_prefix
amca config set plugins.marker_prefix '+++'
amca config unset core.editor      # back to the default
amca config describe log.mode      # type, default, env var name
amca config edit                   # open the JSON
```

`--origin` is the answer to "I changed a value and nothing happened". It shows
whether your edit is being overridden by an env var, whether the key is real,
and whether the file parsed at all. An unknown key is reported as a warning
rather than ignored.

Every setting also has an env var: `plugins.marker_prefix` →
`AMCA_PLUGINS_MARKER_PREFIX`.

Settings: `core.debug`, `core.greet`, `core.editor`, `root.folder_name`,
`root.search_depth`, `root.ask_to_create`, `root.ignored_paths`, `log.mode`,
`log.level`, `log.prefix`, `plugins.dir`, `plugins.enabled`,
`plugins.marker_prefix`, `plugins.on_error`, `plugins.on_missing`,
`plugins.announce_loaded`, `plugins.sources`. Run `amca config describe` for
all of them.

### External tools

Override any tool amca shells out to:

```bash
export AMCA_TOOL_MESON=/opt/meson/bin/meson
export AMCA_TOOL_NINJA=samu
```

---

## Migrating from 2.x

```bash
amca config migrate --dry-run   # show what would be imported
amca config migrate             # do it
```

Keys were renamed and several boolean pairs became enums:

| 2.x | 3.x |
|---|---|
| `args.plugin_prefix` | `plugins.marker_prefix` |
| `generic.plugin_path` | `plugins.dir` |
| `generic.exit_on_plugin_error` | `plugins.on_error` = `continue`\|`abort` |
| `generic.exit_on_plugin_not_found` | `plugins.on_missing` = `ignore`\|`warn`\|`abort` |
| `logging.print_loaded` | `plugins.announce_loaded` |
| `extreamly_important.greet_user` | `core.greet` |

Then remove the old install: delete `~/.config/Amca/`, and the `amca`/`amcapl`
binaries the old installer copied into your bin directory plus the `PATH` line
it added to your shell rc.

Existing plugins keep working — the loader detects the old five-argument
`should_load(amca_root_dir, amca_root_plugin_dir, working_dir, dir_parser, args)`
shape and adapts it. Port them when convenient.

---

## Writing a plugin

A plugin is a directory in `plugins.dir` containing `plugin.py`:

```python
from amca.api import Plugin, PluginContext, PluginError
from amca.core import proc


class cargo(Plugin):
    description = "cargo build/run"

    def should_load(self, ctx: PluginContext) -> bool:
        # Cheap. Called for every enabled plugin on every invocation.
        return ctx.project_dir_info().has_file("Cargo.toml")

    def load(self, ctx: PluginContext) -> int:
        if ctx.dry_run:
            ctx.log.log("would run cargo build")
            return 0
        cargo = proc.resolve_tool("cargo", hint="install rustup")
        return proc.call([cargo, "build", *ctx.args], cwd=str(ctx.project_dir))
```

`PluginContext` carries `args`, `working_dir`, `root`, `plugin_dir` (your
private per-project directory, already created), `dirs`, `log`, `dry_run`.

Import `amca.api` directly — amca is an installed package. Do **not** vendor
copies of amca's internals into your plugin, which is what the 2.x presets had
to do when amca was a frozen binary with nothing importable.

Raise `PluginError` for a clean message with no traceback. Return an exit
status; `0` or `None` means success.

Install a local plugin directory:

```bash
amca config set plugins.sources builtin,/home/you/my-plugins
amcapl install cargo
```

---

## Bundled plugins

**meson** — `setup → reconfigure → compile → install → test → run`. Reads
`amca_var__meson__*` from `meson.build`; `amca ---meson --print-template`
prints a starter. `reconfigure` re-runs meson only when the *set* of source
files changes. Syncs `.vscode/launch.json` and `.clangd` to the current build
directory.

**autoscript** — runs `amca_auto_script[.sh|.bash|.zsh]` (`.ps1`/`.bat`/`.cmd`
on Windows) from the working directory, falling back to the root. Everything
after the marker is forwarded. `amca ---autoscript --new` creates one.

---

## Development

```bash
pip install -e '.[all,dev]'
pytest                      # 39 unit tests, <1s
python tests/e2e.py         # 100-case end-to-end matrix, subprocesses
python tests/e2e.py --list  # show the matrix without running it
python tests/e2e.py -k markers -v
ruff check src tests
mypy src
```

`tests/test_regressions.py` is a list of defects that shipped in 2.x, one test
each. Add to it rather than deleting from it.

`tests/e2e.py` runs the real console scripts against throwaway config and
project directories. Cases marked `!` exercise a mistake, hostile argv, or a
broken component — those matter more than the happy paths. `tests/fixtures/probe/`
is a plugin that dumps its whole `PluginContext` as JSON and can be made to
fail in any way via `PROBE_*` environment variables, so one fixture covers
every failure mode.

## Platform support

| | status |
|---|---|
| Linux | fully tested — 67 unit tests + a 100-case end-to-end matrix run on every change |
| macOS | code paths tested by simulation; not executed on a real machine |
| Windows | code paths tested by simulation; not executed on a real machine |

`tests/test_platform.py` patches `os.name` / `sys.platform` and reloads the
affected modules to exercise the Windows and macOS branches: config directory
resolution (`%APPDATA%`, `~/Library/Application Support`, XDG), the `.exe`
suffix on built binaries, the autoscript interpreter table (`.ps1` via
PowerShell with `-ExecutionPolicy Bypass`, `.bat`/`.cmd` via `cmd /C`),
non-POSIX `shlex` splitting so Windows paths keep their backslashes, the
default editor, colour detection, and read-only file deletion.

That verifies the branches are correct and reachable. It does not verify that
Windows behaves as expected — if you hit something, `amca doctor` output is the
useful thing to attach to an issue.

Known Windows caveats:

- Plugin folder names are matched case-sensitively, so a folder named `Meson`
  will not answer to `---meson` even though NTFS considers them the same file.
  Keep plugin folder names lowercase.
- ANSI colour needs Windows Terminal, ConEmu/ANSICON, or a console that accepts
  `ENABLE_VIRTUAL_TERMINAL_PROCESSING`. amca tries to switch it on and silently
  falls back to plain text if it cannot.
- The bundled `autoscript` plugin does not offer an extensionless script on
  Windows, since such a file is not executable there.

## License

GPL-3.0-or-later. See [LICENSE](LICENSE).
