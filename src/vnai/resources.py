"""Resolve the same authored data in a checkout and an installed wheel."""

from importlib.resources import files
from pathlib import Path


def data_path(relative: str) -> Path:
    root = Path(__file__).resolve().parents[2]
    if (root / "pyproject.toml").is_file() and (root / "knowledge").is_dir():
        return root / relative
    return Path(str(files("vnai").joinpath("_data", relative)))
