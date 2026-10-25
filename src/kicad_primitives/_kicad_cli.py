"""Private lazy kicad-cli discovery (ADR 0007). Not a public module."""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path


class KicadCliNotFoundError(RuntimeError):
    """No usable kicad-cli executable could be resolved."""


_PLATFORM_CANDIDATES: dict[str, tuple[Path, ...]] = {
    "darwin": (
        Path("/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli"),
        Path("/Applications/KiCad/kicad-cli"),
    ),
    "win32": (
        Path(r"C:\Program Files\KiCad\10.0\bin\kicad-cli.exe"),
        Path(r"C:\Program Files\KiCad\9.0\bin\kicad-cli.exe"),
        Path(r"C:\Program Files\KiCad\8.0\bin\kicad-cli.exe"),
    ),
}


def _is_executable(path: Path) -> bool:
    try:
        return path.is_file() and os.access(path, os.X_OK)
    except OSError:
        return False


def resolve_kicad_cli(explicit: str | Path | None = None) -> Path:
    """Resolve kicad-cli: explicit path, KICAD_CLI, platform defaults, then PATH.

    Discovery runs only when called. Failure raises KicadCliNotFoundError and is
    distinct from later operation failures (non-zero exit, bad output).
    """
    if explicit is not None:
        path = Path(explicit).expanduser()
        if not _is_executable(path):
            raise KicadCliNotFoundError(f"kicad-cli not executable: {path}")
        return path.resolve()

    env = os.environ.get("KICAD_CLI")
    if env:
        path = Path(env).expanduser()
        if not _is_executable(path):
            raise KicadCliNotFoundError(f"KICAD_CLI is not executable: {path}")
        return path.resolve()

    for candidate in _PLATFORM_CANDIDATES.get(sys.platform, ()):
        if _is_executable(candidate):
            return candidate.resolve()

    which = shutil.which("kicad-cli")
    if which is not None:
        path = Path(which)
        if _is_executable(path):
            return path.resolve()

    raise KicadCliNotFoundError(
        "kicad-cli not found (explicit path, KICAD_CLI, platform defaults, PATH)"
    )
