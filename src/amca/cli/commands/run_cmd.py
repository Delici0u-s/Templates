"""``amca run`` — the default command."""

from __future__ import annotations

import argparse

from ...core.context import amcaContext
from ...plugins.registry import Registry

__all__ = ["handle"]


def handle(
    ctx: amcaContext,
    args: argparse.Namespace,
    plugin_args: dict[str, list[str]],
) -> int:
    # Root discovery is interactive here and only here: this is the one command
    # where "you are not in a project yet" is worth asking about.
    ctx.find_root(interactive=True)

    registry = Registry(ctx)
    if not registry.entries:
        ctx.log.warning(
            f"no plugins installed in {ctx.plugins_dir}\n"
            f"  install one with:  amcapl install meson"
        )
        return 0
    if not registry.enabled_names():
        ctx.log.warning(
            "no plugins are enabled\n"
            "  enable one with:  amcapl enable"
        )
        return 0

    return registry.run(plugin_args, dry_run=bool(getattr(args, "dry_run", False)))
