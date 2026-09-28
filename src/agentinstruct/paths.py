"""Portable names and confined paths shared by authoring and local outputs."""

import os
import re
import unicodedata
from pathlib import Path

_RESERVED = {"con", "prn", "aux", "nul"} | {
    f"{prefix}{number}" for prefix in ("com", "lpt") for number in range(1, 10)
}
_SYSTEM_ALIASES = {
    Path("/tmp"): Path("/private/tmp"),
    Path("/var"): Path("/private/var"),
    Path("/etc"): Path("/private/etc"),
}


def normalized_name(name: str) -> str:
    return unicodedata.normalize("NFC", name)


def portable_name(name: str) -> str:
    if (
        not name
        or name in {".", ".."}
        or name[-1] in {".", " "}
        or re.search(r'[\x00-\x1f<>:"/\\|?*]', name)
        or name.split(".")[0].casefold() in _RESERVED
        or len(name.encode("utf-8")) > 255
    ):
        raise ValueError(f"{name!r}: expected a portable name")
    return name


def unique_names(names: list[str], label: str) -> None:
    normalized = [normalized_name(name).casefold() for name in names]
    if len(set(normalized)) != len(normalized):
        raise ValueError(f"{label}: names collide after case normalization")


def relative_path(relative: str) -> Path:
    path = Path(relative)
    if path.is_absolute() or ".." in path.parts or "\\" in relative:
        raise ValueError(f"{relative}: expected a package-relative path")
    for part in path.parts:
        portable_name(part)
    return path


def package_path(root: Path, relative: str) -> Path:
    """Resolve exact spellings without following any package symbolic link."""
    path = root
    for part in relative_path(relative).parts:
        children = list(path.iterdir())
        unique_names([child.name for child in children], str(path.relative_to(root)))
        if part not in {child.name for child in children}:
            raise ValueError(f"{relative}: missing package file (exact case required)")
        path = path / part
        if path.is_symlink():
            raise ValueError(
                f"{relative}: symbolic links are not allowed in package paths"
            )
    if not path.resolve(strict=True).is_relative_to(root):
        raise ValueError(f"{relative}: path escapes the Task Package")
    return path


def seed_glob(pattern: str) -> str:
    if (
        not pattern
        or pattern.startswith("/")
        or "\\" in pattern
        or ":" in pattern
        or ".." in pattern.split("/")
        or any("**" in part and part != "**" for part in pattern.split("/"))
    ):
        raise ValueError("seed.glob must be a relative glob without traversal")
    return pattern


def output_path(value: str | Path) -> Path:
    """Reject static link aliases before an output can create or truncate data."""
    path = Path(os.path.abspath(value))
    current = Path(path.anchor)
    for part in path.parts[1:]:
        portable_name(part)
        current = current / part
        if current.is_symlink():
            if (
                current not in _SYSTEM_ALIASES
                or _SYSTEM_ALIASES[current] != current.resolve()
            ):
                raise ValueError(f"Output path contains symbolic links: {current}")
            current = current.resolve()
    if path.is_file() and path.stat().st_nlink > 1:
        raise ValueError(f"Output path has hard links: {path}")
    return path.resolve()
