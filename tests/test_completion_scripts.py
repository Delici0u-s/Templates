"""Execute the generated completion scripts, rather than only emitting them.

The existing coverage (e2e N1-N14) checks that a script is produced, is
non-empty, and calls amca by absolute path. Every one of those passed while
`amca <TAB>` offered plugin markers and no subcommands at all, because nothing
ever *ran* the shell function. These tests drive the real completion entry
points in a real shell.

Skipped when the shell is not installed, so CI on a minimal image stays green.
"""

from __future__ import annotations

import shutil
import subprocess
import textwrap

import pytest

from amca.cli import completions

BASH = shutil.which("bash")
pytestmark = pytest.mark.skipif(BASH is None, reason="bash not installed")


def _complete(script: str, line: str) -> list[str]:
    """Return the candidates bash's `_amca`/`_amcapl` would offer for *line*.

    A trailing space means the cursor sits on a new, empty word — the case that
    the marker bug turned into "every marker and nothing else".
    """
    func = "_amcapl" if line.split()[0] == "amcapl" else "_amca"
    harness = textwrap.dedent(
        f"""
        {script}
        COMP_WORDS=({line})
        [[ "{line}" == *" " ]] && COMP_WORDS+=("")
        COMP_CWORD=$(( ${{#COMP_WORDS[@]}} - 1 ))
        COMPREPLY=()
        {func}
        printf '%s\\n' "${{COMPREPLY[@]}}"
        """
    )
    out = subprocess.run(
        [BASH, "-c", harness], capture_output=True, text=True, check=True
    )
    return [line for line in out.stdout.splitlines() if line]


@pytest.fixture(scope="module")
def script() -> str:
    return completions.script_for("bash")


def test_script_is_syntactically_valid() -> None:
    for shell in ("bash",):
        text = completions.script_for(shell)
        subprocess.run([BASH, "-n"], input=text, text=True, check=True)


def test_bare_command_offers_subcommands(script: str) -> None:
    """`amca <TAB>` must list commands.

    Regression: the marker loop used `[[ "$m" == "$cur"* ]]`, which every
    marker satisfies when $cur is empty, and then returned early.
    """
    got = _complete(script, "amca ")
    assert "config" in got
    assert "doctor" in got
    assert "plugins" in got


def test_subcommand_values_are_not_shadowed_by_markers(script: str) -> None:
    got = _complete(script, "amca config ")
    assert "set" in got
    assert "describe" in got


def test_prefix_still_narrows_to_markers(script: str) -> None:
    got = _complete(script, "amca ---")
    assert got, "markers must still be offered"
    assert all(candidate.startswith("---") for candidate in got)


def test_option_values_are_exact(script: str) -> None:
    assert sorted(_complete(script, "amca --log-mode ")) == [
        "both",
        "console",
        "file",
        "silent",
    ]


def test_compreply_does_not_leak_between_invocations(script: str) -> None:
    """The marker branch appends; bash does not clear COMPREPLY for us."""
    harness = textwrap.dedent(
        f"""
        {script}
        COMP_WORDS=(amca --log-mode ""); COMP_CWORD=2; _amca
        COMP_WORDS=(amca "");            COMP_CWORD=1; _amca
        printf '%s\\n' "${{COMPREPLY[@]}}"
        """
    )
    out = subprocess.run(
        [BASH, "-c", harness], capture_output=True, text=True, check=True
    )
    assert "console" not in out.stdout.split()


def test_falls_back_to_filenames(script: str) -> None:
    """Plugin arguments are usually paths; amca cannot know a plugin's flags."""
    assert "-o default" in script


def test_fish_ships_a_separate_amcapl_file() -> None:
    """fish autoloads completions/<command>.fish, so amcapl needs its own."""
    assert completions._sibling_name("fish") == "amcapl.fish"
    pl = completions._pl_script_for("fish")
    assert "complete -c amcapl" in pl
    assert "@AMCA" not in pl, "placeholders must be substituted"


def test_zsh_binds_both_commands_from_one_file() -> None:
    assert completions.script_for("zsh").startswith("#compdef amca amcapl")
    assert completions._sibling_name("zsh") is None
