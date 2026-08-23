"""Reading the ``amca_var__meson__*`` declarations out of a meson.build.

Parsed once per run into a :class:`MesonProject`. The previous version re-read
and re-regexed meson.build inside every one of the seven mode modules, each
with its own copy of the missing-variable error message, and each free to
disagree with the others about what a missing value meant.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

__all__ = ["SUPPORTED_TEMPLATE_VERSIONS", "MesonProject", "ProjectError"]

SUPPORTED_TEMPLATE_VERSIONS = ("2.0.1",)

_VAR = "amca_var__meson__"


class ProjectError(RuntimeError):
    """meson.build is missing something amca needs."""


def _read_var(text: str, name: str) -> str | None:
    pattern = re.compile(rf"^\s*{re.escape(name)}\s*=\s*['\"](.*?)['\"]", re.MULTILINE)
    match = pattern.search(text)
    return match.group(1) if match else None


@dataclass(frozen=True, slots=True)
class MesonProject:
    root: Path
    meson_file: Path
    template_version: str
    build_dir: Path
    executable_name: str
    #: Install directory, relative to the *build* directory.
    install_subdir: str

    @property
    def executable_path(self) -> Path:
        suffix = ".exe" if os.name == "nt" else ""
        return (self.build_dir / self.install_subdir / f"{self.executable_name}{suffix}").resolve()

    @property
    def install_dir(self) -> Path:
        return (self.build_dir / self.install_subdir).resolve()

    @classmethod
    def load(cls, meson_file: Path) -> MesonProject:
        try:
            text = meson_file.read_text(encoding="utf-8")
        except OSError as exc:
            raise ProjectError(f"cannot read {meson_file}: {exc}") from exc

        version = _read_var(text, f"{_VAR}version_behaviour")
        if version is None:
            raise ProjectError(
                f"{meson_file} has no {_VAR}version_behaviour.\n"
                f"  This meson.build predates the amca template. Add the amca "
                f"variable block, or run `amca ---meson --print-template`."
            )
        if version not in SUPPORTED_TEMPLATE_VERSIONS:
            raise ProjectError(
                f"{meson_file}: template version {version!r} is not supported by this "
                f"plugin (supported: {', '.join(SUPPORTED_TEMPLATE_VERSIONS)})"
            )

        missing: list[str] = []
        values: dict[str, str] = {}
        for key in ("build_dir", "executable_name", "install_dir"):
            value = _read_var(text, f"{_VAR}{key}")
            if value is None:
                missing.append(f"{_VAR}{key}")
            else:
                values[key] = value
        if missing:
            raise ProjectError(
                f"{meson_file} is missing: {', '.join(missing)}"
            )

        root = meson_file.parent.resolve()
        return cls(
            root=root,
            meson_file=meson_file,
            template_version=version,
            build_dir=(root / values["build_dir"]).resolve(),
            executable_name=values["executable_name"],
            install_subdir=values["install_dir"],
        )
