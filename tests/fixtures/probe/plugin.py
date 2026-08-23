"""Probe plugin: dumps its entire PluginContext as one JSON line.

Not shipped in the wheel — this lives in tests/fixtures and is copied into a
scratch plugin directory by the end-to-end harness. Its behaviour is driven
entirely by environment variables so a single plugin can simulate every failure
mode without needing a dozen near-identical fixtures.

    PROBE_NAME        folder/marker name to report as (default: probe)
    PROBE_SHOULD_LOAD 1|0        - what should_load returns
    PROBE_SHOULD_RAISE 1         - raise inside should_load
    PROBE_RETURN      int        - exit status to return from load
    PROBE_RAISE       plugin|generic|keyboard|systemexit
    PROBE_SLEEP       float      - seconds to sleep inside load
"""

from __future__ import annotations

import json
import os
import sys
import time

from amca.api import Plugin, PluginContext, PluginError

NAME = os.environ.get("PROBE_NAME", "probe")


class probe(Plugin):
    name = NAME
    description = "records what it was handed"

    def should_load(self, ctx: PluginContext) -> bool:
        if os.environ.get(f"PROBE_SHOULD_RAISE_{NAME.upper()}") == "1":
            raise RuntimeError("deliberate should_load failure")
        if os.environ.get("PROBE_SHOULD_RAISE") == "1":
            raise RuntimeError("deliberate should_load failure")
        flag = os.environ.get(f"PROBE_SHOULD_LOAD_{NAME.upper()}") or os.environ.get(
            "PROBE_SHOULD_LOAD", "1"
        )
        return flag == "1"

    def load(self, ctx: PluginContext) -> int:
        record = {
            "plugin": NAME,
            "args": ctx.args,
            "argc": len(ctx.args),
            "dry_run": ctx.dry_run,
            "working_dir": str(ctx.working_dir.path),
            "root": str(ctx.root.path) if ctx.root else None,
            "plugin_dir": str(ctx.plugin_dir) if ctx.plugin_dir else None,
            "plugin_dir_exists": bool(ctx.plugin_dir and ctx.plugin_dir.is_dir()),
            "project_dir": str(ctx.project_dir),
            "cwd": os.getcwd(),
        }
        print("PROBE " + json.dumps(record, ensure_ascii=False), flush=True)

        delay = os.environ.get("PROBE_SLEEP")
        if delay:
            time.sleep(float(delay))

        mode = os.environ.get(f"PROBE_RAISE_{NAME.upper()}") or os.environ.get("PROBE_RAISE", "")
        if mode == "plugin":
            raise PluginError("deliberate PluginError")
        if mode == "generic":
            raise ValueError("deliberate uncaught exception")
        if mode == "keyboard":
            raise KeyboardInterrupt
        if mode == "systemexit":
            sys.exit(43)

        code = os.environ.get(f"PROBE_RETURN_{NAME.upper()}") or os.environ.get("PROBE_RETURN", "0")
        return int(code)
