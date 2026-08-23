"""Interactive prompts that work with or without InquirerPy.

InquirerPy is an optional extra. When it is absent — or when stdin is not a
terminal — these fall back to plain numbered input or to the supplied default.
The old code imported InquirerPy at module scope inside ``args_cli.py``, which
made a missing optional dependency crash ``amca --help``.
"""

from __future__ import annotations

import sys
from collections.abc import Sequence
from typing import Any

__all__ = ["confirm", "interactive", "multiselect", "select"]


def interactive() -> bool:
    return bool(sys.stdin.isatty() and sys.stdout.isatty())


def _inquirer() -> Any:
    try:
        from InquirerPy import inquirer

        return inquirer
    except Exception:
        return None


def confirm(question: str, *, default: bool = True) -> bool:
    if not interactive():
        return default
    suffix = " [Y/n] " if default else " [y/N] "
    while True:
        try:
            answer = input(question + suffix).strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            return False
        if not answer:
            return default
        if answer in ("y", "yes"):
            return True
        if answer in ("n", "no"):
            return False
        print("Please answer y or n.")


def select(message: str, choices: Sequence[str], *, allow_cancel: bool = True) -> str | None:
    """Pick one item. Returns None when cancelled or when nothing is selectable."""
    options = list(choices)
    if not options:
        return None
    if not interactive():
        return None

    inquirer = _inquirer()
    cancel = "· cancel ·"
    if inquirer is not None:
        try:
            picked = inquirer.select(
                message=message,
                choices=options + ([cancel] if allow_cancel else []),
            ).execute()
        except KeyboardInterrupt:
            return None
        return None if picked == cancel else str(picked)

    print(message)
    for index, option in enumerate(options, 1):
        print(f"  {index}) {option}")
    if allow_cancel:
        print("  0) cancel")
    while True:
        try:
            raw = input("Choice: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return None
        if raw == "0" and allow_cancel:
            return None
        if raw.isdigit() and 1 <= int(raw) <= len(options):
            return options[int(raw) - 1]
        print(f"Enter a number between {0 if allow_cancel else 1} and {len(options)}.")


def multiselect(
    message: str, choices: Sequence[str], *, preselected: Sequence[str] = ()
) -> list[str] | None:
    """Pick several items.

    Returns None when the user cancelled (Ctrl-C, EOF, or a non-interactive
    stream) and an empty list when they confirmed an empty selection. Those are
    different events and callers must be able to tell them apart: collapsing
    both into None made `amcapl install`, followed by a bare Enter, exit 1 with
    no output at all.
    """
    options = list(choices)
    if not options or not interactive():
        return None

    inquirer = _inquirer()
    if inquirer is not None:
        try:
            picked = inquirer.checkbox(
                message=message,
                # Not optional decoration: a checkbox that does not say space
                # toggles looks like a list that ignores Enter.
                instruction="(space to select, a for all, enter to confirm)",
                choices=[
                    {"name": option, "value": option, "enabled": option in preselected}
                    for option in options
                ],
            ).execute()
        except KeyboardInterrupt:
            return None
        return [str(item) for item in picked]

    print(f"{message}  (comma-separated numbers, 'a' for all, empty to cancel)")
    for index, option in enumerate(options, 1):
        mark = "*" if option in preselected else " "
        print(f"  {mark} {index}) {option}")
    try:
        raw = input("Choice: ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return None
    if not raw:
        return None
    if raw.lower() == "a":
        return options
    result: list[str] = []
    for token in raw.split(","):
        token = token.strip()
        if token.isdigit() and 1 <= int(token) <= len(options):
            result.append(options[int(token) - 1])
    return result
