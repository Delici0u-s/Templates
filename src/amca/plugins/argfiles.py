"""Per-project default arguments: ``<root>/.amca/args/<plugin>.args``.

One argument per line, ``#`` comments and blank lines ignored. The tokens are
placed *before* whatever the user typed after the plugin's marker, so a project
can pin ``--buildtype=debug`` while a command-line flag still overrides it.

This lives in ``plugins/`` rather than in the ``amca args`` command module
because both the editor command and the run loop need it, and having the run
loop import from ``cli.commands`` created an import cycle.
"""

from __future__ import annotations

from pathlib import Path

__all__ = ["ARG_TEMPLATE", "read_arg_file", "write_template"]

ARG_TEMPLATE = """\
# Default arguments for the '{name}' plugin in this project.
# One argument per line. Lines starting with # are ignored.
# These are placed *before* anything you type after {prefix}{name}.
"""


def read_arg_file(path: Path) -> list[str]:
    """Parse an ``.args`` file into a token list.

    A missing or unreadable file yields an empty list — a project without
    defaults is the normal case, not an error.

    Complexity: O(lines).
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    return [
        stripped
        for line in text.splitlines()
        if (stripped := line.strip()) and not stripped.startswith("#")
    ]


def write_template(path: Path, name: str, prefix: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(ARG_TEMPLATE.format(name=name, prefix=prefix), encoding="utf-8")
