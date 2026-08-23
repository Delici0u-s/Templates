# Amca

**One command that knows what to do in whatever directory you are standing in.**

You have a C project built with meson, a Python thing with a build script, and
a dozen repos that each need some slightly different incantation. Amca is the
command you type in all of them. It looks at the directory, works out which of
its plugins apply, and runs them.

```console
$ cd ~/code/renderer          # has a meson.build
$ amca
[setup] meson setup /home/you/code/renderer/build
[compile] meson compile -j 24
[install] meson install
[test] all tests passed
[run] /home/you/code/renderer/compiled/renderer
```

```console
$ cd ~/code/scraper           # has an amca_auto_script.sh
$ amca
[autoscript] sh /home/you/code/scraper/amca_auto_script.sh
```

Same keystroke. Amca itself does almost nothing — it decides *which* plugin
applies and hands it the arguments. The behaviour lives in plugins, and you
write your own.

---

## Requirements

Python 3.10 or newer. Nothing else — amca has **no required runtime
dependencies**, deliberately, so a broken third-party wheel can never stop it
from starting.

Plugins may have their own: the bundled `meson` plugin needs `meson`, which
needs `ninja` and a compiler.

## Install

```bash
uv tool install --python 3.13 --with 'amca[all]' git+https://github.com/Delici0u-s/Amca
```

`--python` pins a `uv`-managed interpreter so a distro Python upgrade cannot
break amca. Alternatives:

```bash
pipx install 'amca[all]'
pip install --user 'amca[all]'
```

| extra | gives you | without it |
|---|---|---|
| `tui` | arrow-key selection menus (InquirerPy) | numbered stdin prompts |
| `remote` | installing plugins from GitHub (requests) | bundled plugins only |
| `all` | both | |

Upgrading is `uv tool upgrade amca` or `pipx reinstall amca`. There is no build
step and nothing to recompile after a system update.

## First run

```bash
amcapl install meson autoscript   # from copies bundled in the wheel; works offline
cd ~/some/project
amca                              # run whatever applies
```

Tab-completion installs itself the first time you run amca interactively. See
[Shell completion](#shell-completion).

Optionally mark a project root:

```bash
amca new     # creates .Amca/ for per-project plugin state and argument files
```

Without a root, amca uses the current directory. With one, `amca` works from
any subdirectory of the project.

---

## Plugins

A plugin decides whether it applies (`should_load`) and then does the work
(`load`). Amca runs every enabled plugin that applies.

```bash
amcapl list                    # what is installed, and its marker
amcapl install NAME…           # fetch and enable
amcapl enable | disable | toggle [NAME…]
amcapl uninstall NAME…
amcapl update [NAME…]
amcapl call NAME -- ARGS       # run one directly, skipping should_load
```

Omit the names and you get a picker. **In the checkbox, space selects and enter
confirms** — enter on its own selects nothing.

### Passing arguments to a plugin

Everything after a **marker** goes to that plugin, until the next marker:

```bash
amca ---meson -s -j8              # clean, then full pipeline, 8 jobs
amca ---meson compile             # one step
amca ---autoscript deploy --dry   # forwarded to your script
```

A marker is `plugins.marker_prefix` (default `---`) plus the plugin's folder
name, underscores written as dashes. `amca plugins --markers` prints the exact
strings this directory accepts.

**Naming a plugin runs only that plugin.** `amca ---meson compile` will not also
fire autoscript, even if the directory has a script. With no markers, `amca`
runs everything applicable — the usual case. Set `plugins.marker_scope=all` if
you want a marker to add arguments without narrowing the run.

**An unrecognised marker is an error**, and it suggests the fix:

```console
$ amca ---autoScr
amca: unknown plugin marker '---autoScr'
  did you mean: ---autoscript
  known markers: ---autoscript, ---meson
```

A bare `--` stops marker parsing, for values that begin with the prefix:

```bash
amca config set plugins.marker_prefix -- +++
```

Avoid shell glob or history characters (`* ? [ ] { } ~ !`) in the prefix — your
shell expands the marker before amca sees it. `config set` warns if you try.

### Per-project default arguments

`.Amca/args/<plugin>.args`, one argument per line, `#` for comments. They are
placed before anything you type, so a project can pin `--buildtype=debug` while
a command-line flag still overrides it.

```bash
amca args meson        # opens it in $EDITOR
amca args meson --show
```

---

## Bundled plugins

### `example`

A working plugin whose only purpose is to be copied. Sixty commented lines
covering selection, `--dry-run`, `PluginError`, tool resolution and logging.

```bash
amcapl install example
amca ---example --show     # prints every PluginContext field and what it is for
```

Start here rather than from one of the real presets.

### `meson`

Pipeline: `setup → reconfigure → compile → install → test → run`.

```bash
amca ---meson                 # whole pipeline
amca ---meson compile         # one step
amca ---meson -s              # clean first
amca ---meson -n t -n e       # skip test and run
amca ---meson -Ab "--buildtype=debug" -Ae "--verbose"
amca ---meson --print-template > meson.build
```

Applies to any directory whose `meson.build` carries the amca variable block:

```meson
amca_var__meson__version_behaviour = '2.0.1'
amca_var__meson__build_dir         = 'build'
amca_var__meson__executable_name   = 'myapp'
amca_var__meson__install_dir       = '../compiled'   # relative to build_dir
```

`reconfigure` re-runs meson only when the *set* of source files changes —
ninja handles content changes. `.vscode/launch.json` and `.clangd` are kept
pointing at the current build directory.

### `autoscript`

Runs `amca_auto_script[.sh|.bash|.zsh]` (`.ps1`/`.bat`/`.cmd` on Windows) from
the working directory, falling back to the project root. Arguments are
forwarded to the script.

```bash
amca ---autoscript --new       # create one (asks which shell)
amca ---autoscript build       # forwarded
amca ---autoscript -- --help   # forward --help verbatim to the script
```

---

## Writing a plugin

A plugin is a directory containing `plugin.py` with exactly one subclass of
`amca.api.Plugin`:

```python
from amca.api import Plugin, PluginContext, PluginError
from amca.core import proc


class cargo(Plugin):
    description = "cargo build/run"

    def should_load(self, ctx: PluginContext) -> bool:
        # Cheap — called for every enabled plugin on every invocation.
        return ctx.project_dir_info().has_file("Cargo.toml")

    def load(self, ctx: PluginContext) -> int:
        if ctx.dry_run:
            ctx.log.log("would run cargo build")
            return 0
        cargo = proc.resolve_tool("cargo", hint="install rustup")
        return proc.call([cargo, "build", *ctx.args], cwd=str(ctx.project_dir))
```

`PluginContext` carries `args`, `working_dir`, `root`, `plugin_dir` (your
private per-project directory, already created), `dirs`, `log` and `dry_run`.

Import `amca.api` directly — amca is an installed package. Do not vendor copies
of its internals. Raise `PluginError` for a clean message with no traceback.
Return an exit status; `0` or `None` means success.

Subdirectories work and are namespaced per plugin, so two plugins can both have
an `_impl/` without colliding:

```
my-plugin/
    plugin.py
    _impl/
        __init__.py
```

### Where plugins live

Three different places, easy to conflate:

| | |
|---|---|
| `~/.config/amca/plugins/` | **installed** — what actually runs. `amcapl` manages it; `plugins.dir` moves it. |
| `plugins/amca_presets/` in this repo | the three bundled with amca, so `amcapl install` works offline |
| anywhere you like | **yours** |

Your own plugins do not belong in this repo. Add a source:

```bash
amca config set plugins.sources builtin,/home/you/my-amca-plugins
amcapl install cargo
amcapl update cargo            # re-copy after editing
```

While iterating, skip the copy entirely:

```bash
amca --plugin-dir ~/my-amca-plugins ---cargo build
```

---

## Configuration

One file, `$XDG_CONFIG_HOME/amca/config.json`. Four layers, lowest priority
first:

```
built-in default  →  config file  →  AMCA_* env var  →  command-line flag
```

**Only `amca config set` writes to disk.** Command-line flags apply to that run
and nothing else.

```bash
amca config list --origin      # every setting, its value, and which layer won
amca config list --changed
amca config get plugins.marker_prefix
amca config set plugins.marker_prefix '+++'
amca config unset core.editor
amca config describe log.mode  # type, default, env var name
amca config edit
amca config path
```

`--origin` answers "I changed it and nothing happened": it shows whether an env
var is overriding your edit, whether the key is real (unknown keys are reported,
not ignored), and which file is actually in use.

Hand-editing the JSON is fully supported — `config set` is a convenience.
Nested and dotted keys both work:

```json
{
  "plugins": { "marker_prefix": "+++", "enabled": ["meson"] },
  "log": { "level": "WARN" }
}
```

Every setting has an env var: `plugins.marker_prefix` →
`AMCA_PLUGINS_MARKER_PREFIX`.

<details>
<summary>All settings</summary>

| key | default | |
|---|---|---|
| `core.debug` | `false` | extra diagnostics and full tracebacks |
| `core.greet` | `false` | print a greeting on every invocation |
| `core.editor` | `$VISUAL`/`$EDITOR`/`nano` | editor for `amca args` |
| `root.folder_name` | `.Amca` | marker directory identifying a project root |
| `root.search_depth` | `5` | how far up to look for it |
| `root.ask_to_create` | `true` | offer to create one (TTY only) |
| `root.ignored_paths` | `[]` | where not to ask; `amca root ignore` |
| `log.mode` | `console` | `console`, `file`, `both`, `silent` |
| `log.level` | `INFO` | `INFO`, `SUCCESS`, `WARN`, `ERROR`, `FATAL` |
| `log.prefix` | `none` | `none`, `minimal`, `simple`, `normal`, `verbose` |
| `plugins.dir` | `<config>/plugins` | where installed plugins live |
| `plugins.enabled` | `[]` | which may run; `amcapl enable` |
| `plugins.marker_prefix` | `---` | |
| `plugins.marker_scope` | `selected` | `selected` or `all` |
| `plugins.on_error` | `continue` | or `abort` |
| `plugins.on_missing` | `warn` | `ignore`, `warn`, `abort` |
| `plugins.announce_loaded` | `false` | log each plugin as it runs |
| `plugins.sources` | `builtin, github:…` | where `amcapl install` looks |

</details>

### External tools

```bash
export AMCA_TOOL_MESON=/opt/meson/bin/meson
export AMCA_TOOL_NINJA=samu
```

---

## Shell completion

**Usually nothing to do.** The first time you run amca interactively it writes
a completion script to your shell's per-user completion directory and says so
once. bash and fish pick it up on the next shell.

zsh only reads directories on `$fpath`, so it needs one extra line:

```bash
amca completions --install --rc     # adds a delimited block to ~/.zshrc
exec zsh
```

```bash
amca completions --status           # per shell: installed? active? which helper?
amca completions --uninstall        # removes the file and the rc block
amca completions bash > somewhere   # just print it
export AMCA_NO_AUTO_COMPLETION=1    # opt out entirely
```

A wheel cannot run code at install time (PEP 427), so `pip`, `pipx` and `uv
tool` have no way to register completions — only a distro package can. Doing it
on first run is the closest equivalent that works for every install method.
Nothing is added to a shell rc file unless you pass `--rc`.

**Using an alias?** The generated script calls amca by absolute path, so a venv
install off `PATH` still completes — but the alias needs registering:

```bash
amca completions --install --command a3
# zsh also needs, in your rc:  compdef _amca a3
```

Completion is dynamic: plugin names, markers and config keys come from amca at
completion time, so installing a plugin or changing the prefix takes effect
immediately. The helpers are scriptable on their own:

```bash
amca plugins --names
amca plugins --markers
amca config list --keys
```

---

## When something is wrong

```bash
amca doctor
```

Checks paths, which config layer each non-default setting came from, root
resolution, every plugin's health, external tools, and the subprocess
environment. Exits non-zero when it finds a problem. It is the right thing to
paste into an issue.

---

## Upgrading from amca 2.x

```bash
amca config migrate --dry-run     # show what would be imported
amca config migrate
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

Then remove the old install **before** deleting the old checkout — the
uninstaller is the only thing that knows to strip the `# >>> amca PATH >>>`
block from your shell rc:

```bash
python install_uninstall_update.py uninstall --keep-config
```

Existing plugins keep working: the loader detects the old five-argument
`should_load(amca_root_dir, amca_root_plugin_dir, working_dir, dir_parser, args)`
and adapts it. Port them when convenient.

If you upgrade by extracting a release over an old checkout, note that
unzipping does not delete removed files — `amca doctor` will tell you if a
stale `src/amca/presets/` is left behind.

---

## What changed in 3.0

Amca 2.x shipped as a PyInstaller `--onefile` binary rebuilt at install time.
That put a private copy of CPython on `LD_LIBRARY_PATH` for every child
process, so after a distro Python upgrade the system `meson` loaded amca's
stale `libpython` and died with `internal Python C API version mismatch`. It
came back every few weeks and reinstalling was the only fix.

3.0 is a normal Python package, which makes that class of bug structurally
impossible. Along the way:

- CLI flags no longer write to your config file. In 2.x, `--debug` permanently
  rewrote the JSON — even when the command then failed to parse.
- Plugin markers have one definition instead of two disagreeing ones. A typo
  used to split argv and silently discard everything after it.
- Root discovery no longer runs at import time, so `amca --help` cannot block
  on a prompt and `--depth` affects the search it configures.
- Plugins import `amca.api` instead of vendoring copies of amca's internals.
- Two plugins can have identically named submodules without shadowing.

---

## Development

```bash
git clone https://github.com/Delici0u-s/Amca && cd Amca
pip install -e '.[all,dev]'

pytest -q                    # 79 unit tests, under a second
python tests/e2e.py          # 131-case end-to-end matrix, real subprocesses
python tests/e2e.py --list   # the matrix without running it
python tests/e2e.py -k markers -v
ruff check src tests plugins
mypy
```

Layout:

```
src/amca/              the application
plugins/amca_presets/  bundled plugins — content, not application code
tests/
```

`tests/test_regressions.py` is one test per defect that shipped in 2.x. Add to
it rather than deleting from it. `tests/e2e.py` runs the real console scripts
against throwaway config and project directories; cases marked `!` exercise a
mistake, hostile argv, or a broken component, and there are more of those than
happy paths. `tests/fixtures/probe/` is a plugin that dumps its whole
`PluginContext` as JSON and can be driven into any failure mode with `PROBE_*`
environment variables.

Releasing: see [RELEASING.md](RELEASING.md).

## Platform support

| | |
|---|---|
| Linux | fully tested |
| macOS | code paths tested by simulation, not executed |
| Windows | code paths tested by simulation, not executed |

`tests/test_platform.py` patches `os.name` / `sys.platform` and reloads the
affected modules to exercise the non-Linux branches: config directories, the
`.exe` suffix, the autoscript interpreter table, non-POSIX `shlex` splitting,
colour detection, read-only file deletion. That verifies the branches are
correct and reachable — not that Windows behaves as expected.

Windows caveats: plugin folder names are matched case-sensitively, so keep them
lowercase; ANSI colour needs Windows Terminal or a console accepting
`ENABLE_VIRTUAL_TERMINAL_PROCESSING`; `autoscript` does not offer an
extensionless script, since such a file is not executable there.

## License

GPL-3.0-or-later. See [LICENSE](LICENSE).
