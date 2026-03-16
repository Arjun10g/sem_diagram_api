from __future__ import annotations

from pathlib import Path


EXAMPLES_DIR = Path(__file__).resolve().parents[2] / "examples"


def load_example_file(filename: str) -> str:
    path = EXAMPLES_DIR / filename
    return path.read_text(encoding="utf-8")