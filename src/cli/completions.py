"""Shell completion for ``amca`` and ``amcapl``.

The scripts live here as string constants rather than as data files on disk.
That is deliberate: package data is easy to get wrong (the ``meson.build.template``
was silently dropped from an early wheel by a too-narrow glob), and a completion
script that is missing from an install is worse than none at all.

Everything dynamic — plugin names, markers, config keys — is fetched by calling
amca itself, so completions stay correct when you install a plugin or change
``plugins.marker_prefix`` without regenerating anything.
"""

from __future__ import annotations

from collections.abc import Sequence

__all__ = [
    "SHELLS",
    "InstallResult",
    "detect_shell",
    "install",
    "install_hint",
    "is_installed",
    "script_for",
    "target_path",
    "uninstall",
]

RC_START = "# >>> amca completion >>>"
RC_END = "# <<< amca completion <<<"

SHELLS = ("bash", "zsh", "fish")

_BASH = r"""# amca bash completion.  Install with:
#   amca completions bash > ~/.local/share/bash-completion/completions/amca
#   ln -sf amca ~/.local/share/bash-completion/completions/amcapl

_amca_plugins()  { @AMCA@ plugins --names   2>/dev/null; }
_amca_markers()  { @AMCA@ plugins --markers 2>/dev/null; }
_amca_keys()     { @AMCA@ config list --keys 2>/dev/null; }

_amca_global_opts='--help --version --config-dir --debug --log-mode --log-level
--log-prefix --plugin-dir --depth --editor --marker-prefix --on-error --on-missing'

_amca() {
    local cur prev
    cur="${COMP_WORDS[COMP_CWORD]}"
    prev="${COMP_WORDS[COMP_CWORD-1]}"

    case "$prev" in
        --log-mode)    COMPREPLY=($(compgen -W 'console file both silent' -- "$cur")); return;;
        --log-level)   COMPREPLY=($(compgen -W 'INFO SUCCESS WARN ERROR FATAL' -- "$cur")); return;;
        --log-prefix)  COMPREPLY=($(compgen -W 'none minimal simple normal verbose' -- "$cur")); return;;
        --on-error)    COMPREPLY=($(compgen -W 'continue abort' -- "$cur")); return;;
        --on-missing)  COMPREPLY=($(compgen -W 'ignore warn abort' -- "$cur")); return;;
        --config-dir|--plugin-dir) COMPREPLY=($(compgen -d -- "$cur")); return;;
        get|set|unset|describe) COMPREPLY=($(compgen -W "$(_amca_keys)" -- "$cur")); return;;
        args|a)        COMPREPLY=($(compgen -W "$(_amca_plugins)" -- "$cur")); return;;
    esac

    # A marker prefix is not necessarily '-', so check markers before options.
    local markers; markers="$(_amca_markers)"
    if [[ -n "$markers" ]]; then
        local m
        for m in $markers; do
            if [[ "$m" == "$cur"* ]]; then
                COMPREPLY+=("$m")
            fi
        done
        [[ ${#COMPREPLY[@]} -gt 0 ]] && return
    fi

    if [[ "$cur" == -* ]]; then
        COMPREPLY=($(compgen -W "$_amca_global_opts --dry-run" -- "$cur")); return
    fi

    local sub=''
    local i
    for ((i=1; i<COMP_CWORD; i++)); do
        case "${COMP_WORDS[i]}" in
            run|r|new|n|remove|rm|root|args|a|config|doctor|plugins|completions)
                sub="${COMP_WORDS[i]}"; break;;
        esac
    done

    case "$sub" in
        config) COMPREPLY=($(compgen -W 'list ls get set unset path edit describe migrate' -- "$cur"));;
        root)   COMPREPLY=($(compgen -W 'show ignore unignore clear-ignored' -- "$cur"));;
        completions) COMPREPLY=($(compgen -W 'bash zsh fish' -- "$cur"));;
        '')     COMPREPLY=($(compgen -W 'run new remove root args config doctor plugins completions' -- "$cur"));;
    esac
}
complete -F _amca @NAMES@

_amcapl() {
    local cur prev
    cur="${COMP_WORDS[COMP_CWORD]}"
    prev="${COMP_WORDS[COMP_CWORD-1]}"
    case "$prev" in
        enable|e|disable|d|toggle|t|uninstall|u|update|up|call|c)
            COMPREPLY=($(compgen -W "$(_amca_plugins)" -- "$cur")); return;;
        install|i)
            COMPREPLY=($(compgen -W "$(@AMCAPL@ list --available --names 2>/dev/null)" -- "$cur")); return;;
    esac
    if [[ "$cur" == -* ]]; then
        COMPREPLY=($(compgen -W "$_amca_global_opts --available --force --no-enable --source --yes" -- "$cur")); return
    fi
    COMPREPLY=($(compgen -W 'list enable disable toggle install uninstall update call' -- "$cur"))
}
complete -F _amcapl @PLNAMES@
"""

_ZSH = r"""#compdef @NAMES@ @PLNAMES@
# amca zsh completion.  Install with:
#   amca completions zsh > ~/.local/share/zsh/site-functions/_amca
# (any directory on $fpath works; run `compinit` afterwards)

_amca_plugin_names() { @AMCA@ plugins --names 2>/dev/null; }
_amca_marker_names() { @AMCA@ plugins --markers 2>/dev/null; }
_amca_config_keys()  { @AMCA@ config list --keys 2>/dev/null; }

_amca_global() {
    _arguments -C \
        '--config-dir[config directory for this run]:directory:_files -/' \
        '--debug[extra diagnostics and full tracebacks]' \
        '--log-mode[where log output goes]:mode:(console file both silent)' \
        '--log-level[minimum severity]:level:(INFO SUCCESS WARN ERROR FATAL)' \
        '--log-prefix[prefix decoration]:prefix:(none minimal simple normal verbose)' \
        '--plugin-dir[plugin directory]:directory:_files -/' \
        '--depth[root search depth]:n:' \
        '--editor[editor command]:cmd:_command_names -e' \
        '--marker-prefix[plugin marker prefix]:prefix:' \
        '--on-error[on plugin failure]:policy:(continue abort)' \
        '--on-missing[on missing plugin]:policy:(ignore warn abort)' \
        '--version[print version]' \
        '(-h --help)'{-h,--help}'[show help]'
}

_amca() {
    local -a markers subcommands
    markers=(${(f)"$(_amca_marker_names)"})
    subcommands=(
        'run:run applicable plugins'
        'new:create an amca root here'
        'remove:delete the amca root'
        'root:show or manage root detection'
        'args:edit per-project default arguments'
        'config:inspect or change settings'
        'doctor:check the installation'
        'plugins:list plugins and their markers'
        'completions:print a shell completion script'
    )

    # Markers are offered at every position: everything after one belongs to
    # the plugin, and amca cannot know that plugin's flags.
    if (( ${#markers} )); then
        _describe -t markers 'plugin marker' markers
    fi

    if (( CURRENT == 2 )); then
        _describe -t commands 'amca command' subcommands
        _amca_global
        return
    fi

    case ${words[2]} in
        config)
            if (( CURRENT == 3 )); then
                _values 'action' list ls get set unset path edit describe migrate
            elif [[ ${words[3]} == (get|set|unset|describe) ]] && (( CURRENT == 4 )); then
                local -a keys; keys=(${(f)"$(_amca_config_keys)"})
                _describe -t keys 'config key' keys
            fi
            ;;
        root)
            (( CURRENT == 3 )) && _values 'action' show ignore unignore clear-ignored
            ;;
        args|a)
            local -a plugins; plugins=(${(f)"$(_amca_plugin_names)"})
            _describe -t plugins 'plugin' plugins
            ;;
        completions)
            (( CURRENT == 3 )) && _values 'shell' bash zsh fish
            ;;
        *) _amca_global ;;
    esac
}

_amcapl() {
    local -a subcommands
    subcommands=(
        'list:show installed plugins'
        'enable:allow plugins to run'
        'disable:stop plugins from running'
        'toggle:flip plugins'
        'install:fetch plugins from a source'
        'uninstall:delete plugins from disk'
        'update:re-fetch installed plugins'
        'call:run one plugin directly'
    )
    if (( CURRENT == 2 )); then
        _describe -t commands 'amcapl command' subcommands
        _amca_global
        return
    fi
    case ${words[2]} in
        install|i)
            local -a available
            available=(${(f)"$(@AMCAPL@ list --available --names 2>/dev/null)"})
            _describe -t plugins 'available plugin' available
            ;;
        enable|e|disable|d|toggle|t|uninstall|u|update|up|call|c)
            local -a plugins; plugins=(${(f)"$(_amca_plugin_names)"})
            _describe -t plugins 'plugin' plugins
            ;;
        *) _amca_global ;;
    esac
}

case ${service:-$words[1]} in
    amcapl) _amcapl "$@" ;;
    *)      _amca   "$@" ;;
esac
"""

_FISH = r"""# amca fish completion.  Install with:
#   amca completions fish > ~/.config/fish/completions/amca.fish

function __amca_plugins;  @AMCA@ plugins --names   2>/dev/null; end
function __amca_markers;  @AMCA@ plugins --markers 2>/dev/null; end
function __amca_keys;     @AMCA@ config list --keys 2>/dev/null; end
function __amca_no_sub;   not __fish_seen_subcommand_from run r new n remove rm root args a config doctor plugins completions; end

complete -c amca -f
complete -c amca -n __amca_no_sub -a run         -d 'run applicable plugins'
complete -c amca -n __amca_no_sub -a new         -d 'create an amca root here'
complete -c amca -n __amca_no_sub -a remove      -d 'delete the amca root'
complete -c amca -n __amca_no_sub -a root        -d 'root detection'
complete -c amca -n __amca_no_sub -a args        -d 'per-project default arguments'
complete -c amca -n __amca_no_sub -a config      -d 'inspect or change settings'
complete -c amca -n __amca_no_sub -a doctor      -d 'check the installation'
complete -c amca -n __amca_no_sub -a plugins     -d 'list plugins and markers'
complete -c amca -n __amca_no_sub -a completions -d 'print a completion script'

complete -c amca -a '(__amca_markers)' -d 'plugin marker'
complete -c amca -n '__fish_seen_subcommand_from config; and __fish_seen_subcommand_from get set unset describe' -a '(__amca_keys)'
complete -c amca -n '__fish_seen_subcommand_from config' -a 'list get set unset path edit describe migrate'
complete -c amca -n '__fish_seen_subcommand_from root'   -a 'show ignore unignore clear-ignored'
complete -c amca -n '__fish_seen_subcommand_from args'   -a '(__amca_plugins)'
complete -c amca -n '__fish_seen_subcommand_from completions' -a 'bash zsh fish'

complete -c amca -l log-mode   -x -a 'console file both silent'
complete -c amca -l log-level  -x -a 'INFO SUCCESS WARN ERROR FATAL'
complete -c amca -l log-prefix -x -a 'none minimal simple normal verbose'
complete -c amca -l on-error   -x -a 'continue abort'
complete -c amca -l on-missing -x -a 'ignore warn abort'
complete -c amca -l config-dir -x -a '(__fish_complete_directories)'
complete -c amca -l plugin-dir -x -a '(__fish_complete_directories)'
complete -c amca -l debug   -d 'extra diagnostics'
complete -c amca -l dry-run -d 'show what would run'

complete -c amcapl -f
complete -c amcapl -n 'not __fish_seen_subcommand_from list enable disable toggle install uninstall update call' \
    -a 'list enable disable toggle install uninstall update call'
complete -c amcapl -n '__fish_seen_subcommand_from install' -a '(@AMCAPL@ list --available --names 2>/dev/null)'
complete -c amcapl -n '__fish_seen_subcommand_from enable disable toggle uninstall update call' -a '(__amca_plugins)'
"""

_SCRIPTS = {"bash": _BASH, "zsh": _ZSH, "fish": _FISH}

_HINTS = {
    "bash": (
        "mkdir -p ~/.local/share/bash-completion/completions\n"
        "  amca completions bash > ~/.local/share/bash-completion/completions/amca\n"
        "  ln -sf amca ~/.local/share/bash-completion/completions/amcapl\n"
        "  exec bash"
    ),
    "zsh": (
        "mkdir -p ~/.local/share/zsh/site-functions\n"
        "  amca completions zsh > ~/.local/share/zsh/site-functions/_amca\n"
        "  # ensure that directory is on $fpath, e.g. in ~/.zshrc before compinit:\n"
        "  #   fpath=(~/.local/share/zsh/site-functions $fpath)\n"
        "  exec zsh"
    ),
    "fish": (
        "mkdir -p ~/.config/fish/completions\n"
        "  amca completions fish > ~/.config/fish/completions/amca.fish\n"
        "  # amcapl completions are in the same file; fish picks them up on next start"
    ),
}


def _executable(name: str) -> str:
    """Absolute path to an amca console script, when we can find one.

    The completion script shells out to amca for plugin names, markers and
    config keys. If it calls a bare `amca` that is not on PATH — the normal
    case for a venv or an alias like `a3=/tmp/venv/bin/amca` — every dynamic
    completion silently returns nothing and the whole thing looks broken.
    Baking in the absolute path of the interpreter that generated the script
    makes it work regardless of PATH.
    """
    import shutil
    import sys
    from pathlib import Path as _Path

    sibling = _Path(sys.executable).parent / name
    if sibling.is_file():
        return str(sibling)
    found = shutil.which(name)
    return found or name


def script_for(shell: str, *, names: Sequence[str] = (), pl_names: Sequence[str] = ()) -> str:
    """Render the completion script.

    *names* / *pl_names* add extra command names to register, for people who
    invoke amca through an alias or a wrapper.
    """
    try:
        template = _SCRIPTS[shell]
    except KeyError:
        raise ValueError(
            f"unsupported shell {shell!r} (supported: {', '.join(SHELLS)})"
        ) from None

    all_names = list(dict.fromkeys(["amca", *names]))
    # A name may only be bound to one completion function; bash's `complete -F`
    # is last-write-wins and zsh's #compdef would list it twice.
    all_pl_names = [n for n in dict.fromkeys(["amcapl", *pl_names]) if n not in all_names]
    return (
        template
        .replace("@AMCAPL@", _executable("amcapl"))
        .replace("@AMCA@", _executable("amca"))
        .replace("@PLNAMES@", " ".join(all_pl_names))
        .replace("@NAMES@", " ".join(all_names))
    )


def install_hint(shell: str) -> str:
    return _HINTS.get(shell, "")


# ── Automatic installation ───────────────────────────────────────────────────
#
# Why this exists at all: a wheel cannot run code at install time (PEP 427), so
# `pip install amca` physically cannot register a completion script the way an
# RPM or DEB can. Every Python CLI with "automatic" completion is really doing
# one of three things — shipping a distro package, asking you to put a line in
# your rc file, or writing the file itself on first run. This is the third.
#
# The rules we hold ourselves to:
#   * write only into the standard per-user completion directories, which is
#     exactly what a package manager would do;
#   * never touch a shell rc file unless explicitly asked (--rc);
#   * say what was done, once, and never mention it again;
#   * be trivially disabled (AMCA_NO_AUTO_COMPLETION=1) and trivially undone
#     (amca completions --uninstall).

import os
from dataclasses import dataclass
from pathlib import Path

ENV_DISABLE = "AMCA_NO_AUTO_COMPLETION"

#: Written once the first-run installer has had its say, so it never repeats.
MARKER_FILENAME = "completion-installed"


def _xdg(var: str, default: str) -> Path:
    value = os.environ.get(var)
    return Path(value) if value else Path.home() / default


def target_path(shell: str) -> Path:
    """Where this shell looks for a per-user completion file.

    bash-completion v2 and fish both scan their XDG directories with no
    configuration at all, so a file dropped there works on the next shell.
    zsh only reads directories on ``$fpath``, which is why it needs one extra
    line — see :func:`needs_fpath_line`.
    """
    if shell == "bash":
        user_dir = os.environ.get("BASH_COMPLETION_USER_DIR")
        base = Path(user_dir) if user_dir else _xdg("XDG_DATA_HOME", ".local/share") / "bash-completion"
        return base / "completions" / "amca"
    if shell == "zsh":
        return _xdg("XDG_DATA_HOME", ".local/share") / "zsh" / "site-functions" / "_amca"
    if shell == "fish":
        return _xdg("XDG_CONFIG_HOME", ".config") / "fish" / "completions" / "amca.fish"
    raise ValueError(f"unsupported shell {shell!r}")


def detect_shell() -> str | None:
    """Guess the user's shell from $SHELL. None when it is not one we support."""
    name = Path(os.environ.get("SHELL", "")).name
    return name if name in SHELLS else None


def is_installed(shell: str) -> bool:
    try:
        return target_path(shell).is_file()
    except ValueError:
        return False


def needs_fpath_line(shell: str) -> bool:
    """True when zsh will not find the file we just wrote.

    zsh does not export ``$fpath``, so this cannot be answered exactly from
    outside zsh. ``$FPATH`` is checked when present, and otherwise the
    conservative answer is "yes, tell them" — a redundant hint is a much
    smaller cost than completion that silently does nothing.
    """
    if shell != "zsh":
        return False
    directory = str(target_path("zsh").parent)
    if directory in os.environ.get("FPATH", "").split(":"):
        return False
    # An fpath block we added earlier counts: FPATH is usually not exported, so
    # without this check --status kept telling users to fix an already-fixed
    # setup.
    try:
        return RC_START not in _zshrc().read_text(encoding="utf-8")
    except OSError:
        return True


@dataclass(frozen=True, slots=True)
class InstallResult:
    shell: str
    path: Path
    written: bool
    rc_patched: bool = False
    rc_file: Path | None = None
    note: str = ""


def _zshrc() -> Path:
    zdotdir = os.environ.get("ZDOTDIR")
    return (Path(zdotdir) if zdotdir else Path.home()) / ".zshrc"


def _patch_rc(shell: str) -> tuple[bool, Path | None]:
    """Append a clearly delimited block to the rc file. Idempotent."""
    if shell != "zsh":
        return False, None
    rc = _zshrc()
    try:
        existing = rc.read_text(encoding="utf-8") if rc.exists() else ""
    except OSError:
        return False, rc
    if RC_START in existing:
        return False, rc

    directory = target_path("zsh").parent
    block = (
        f"\n{RC_START}\n"
        f"fpath=({directory} $fpath)\n"
        f"autoload -Uz compinit && compinit\n"
        f"{RC_END}\n"
    )
    try:
        with rc.open("a", encoding="utf-8") as handle:
            handle.write(block)
    except OSError:
        return False, rc
    return True, rc


def install(
    shell: str,
    *,
    patch_rc: bool = False,
    names: Sequence[str] = (),
    pl_names: Sequence[str] = (),
) -> InstallResult:
    """Write the completion script to the shell's per-user directory."""
    path = target_path(shell)
    script = script_for(shell, names=names, pl_names=pl_names)
    written = False
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists() or path.read_text(encoding="utf-8") != script:
            path.write_text(script, encoding="utf-8")
            written = True
        if shell == "bash":
            # bash-completion loads by command name, so amcapl needs its own
            # entry. A copy rather than a symlink: some filesystems and some
            # backup tools do not carry symlinks well, and the file is tiny.
            sibling = path.with_name("amcapl")
            if not sibling.exists() or sibling.read_text(encoding="utf-8") != script:
                sibling.write_text(script, encoding="utf-8")
    except OSError as exc:
        return InstallResult(shell, path, False, note=f"could not write: {exc}")

    rc_patched, rc_file = (_patch_rc(shell) if patch_rc else (False, None))
    note = ""
    if shell == "zsh" and not rc_patched and needs_fpath_line("zsh"):
        note = (
            f"zsh only reads directories on $fpath. Add this to {_zshrc()} before "
            f"compinit:\n    fpath=({path.parent} $fpath)\n"
            f"  or let amca do it:  amca completions --install --rc"
        )
    return InstallResult(shell, path, written, rc_patched, rc_file, note)


def uninstall(shell: str) -> tuple[list[Path], list[Path]]:
    """Remove the completion file(s) and any rc block we added.

    Returns (deleted files, edited files) — reporting an rc file we merely
    edited as "removed" reads like amca deleted someone's ~/.zshrc.
    """
    removed: list[Path] = []
    edited: list[Path] = []
    path = target_path(shell)
    for candidate in (path, path.with_name("amcapl") if shell == "bash" else None):
        if candidate is not None and candidate.exists():
            try:
                candidate.unlink()
                removed.append(candidate)
            except OSError:
                pass

    if shell == "zsh":
        rc = _zshrc()
        try:
            text = rc.read_text(encoding="utf-8")
        except OSError:
            return removed, edited
        if RC_START in text and RC_END in text:
            head, _, rest = text.partition(RC_START)
            _, _, tail = rest.partition(RC_END)
            try:
                rc.write_text(head.rstrip("\n") + "\n" + tail.lstrip("\n"), encoding="utf-8")
                edited.append(rc)
            except OSError:
                pass
    return removed, edited


def maybe_auto_install(state_dir: Path, *, interactive: bool) -> str | None:
    """First-run hook. Returns a one-time message, or None to stay silent.

    Deliberately conservative: only on a real terminal, only once ever, only
    for a shell we recognise, and never touching an rc file. Anything that
    fails, fails quietly — completion is a nicety and must not be able to
    break an invocation.
    """
    if os.environ.get(ENV_DISABLE):
        return None
    if not interactive:
        return None

    marker = state_dir / MARKER_FILENAME
    if marker.exists():
        return None

    shell = detect_shell()
    try:
        state_dir.mkdir(parents=True, exist_ok=True)
        marker.write_text(f"{shell or 'unknown'}\n", encoding="utf-8")
    except OSError:
        return None       # cannot record it, so do not risk repeating it

    if shell is None:
        return None
    if is_installed(shell):
        return None

    result = install(shell)
    if not result.written:
        return None

    if result.note:
        # zsh: the file is written but inert until $fpath knows about it. Do
        # not claim success we have not achieved.
        message = (
            f"amca: wrote {shell} tab-completion to {result.path}, "
            f"but it is not active yet.\n  " + result.note
        )
    else:
        message = f"amca: installed {shell} tab-completion to {result.path}"
    message += (
        f"\n  (one-time setup; undo with `amca completions --uninstall`, "
        f"disable with {ENV_DISABLE}=1)"
    )
    return message
