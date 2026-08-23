"""Plugins bundled with amca, installable offline via `amcapl install`.

Deliberately a separate top-level package rather than part of `amca` itself.
These are *content*, not application code: amca never imports them — it copies
a directory out of here into the user's plugin directory, where the loader
imports it as `amca_plugin_<name>`. Living under `src/amca/` gave them a second
importable path (`amca.presets.meson.plugin`) that nothing should ever use, and
implied they were part of the program rather than examples shipped alongside it.

They are still inside the wheel, so `amcapl install meson` works with no
network. See pyproject.toml — `packages.find` has two roots.

To add one: drop a directory here containing `plugin.py`. Copy `example/`.
"""
