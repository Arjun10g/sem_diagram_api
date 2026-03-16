from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from typing import Final


# ============================================================
# Exceptions
# ============================================================

class GraphvizNotInstalledError(RuntimeError):
    """Raised when the Graphviz `dot` executable is not available."""


class GraphvizExecutionError(RuntimeError):
    """Raised when Graphviz fails to render DOT input."""


# ============================================================
# Constants
# ============================================================

DEFAULT_DOT_TIMEOUT_SECONDS: Final[int] = 15
SUPPORTED_TEXT_FORMATS: Final[set[str]] = {"svg", "plain"}
SUPPORTED_BINARY_FORMATS: Final[set[str]] = {"png", "pdf"}
SUPPORTED_FORMATS: Final[set[str]] = SUPPORTED_TEXT_FORMATS | SUPPORTED_BINARY_FORMATS


# ============================================================
# Public API
# ============================================================

def dot_to_svg(dot: str) -> str:
    """
    Convert DOT to SVG text.
    """
    return render_dot_to_text(dot, "svg")


def dot_to_plain(dot: str) -> str:
    """
    Convert DOT to Graphviz plain text output.
    """
    return render_dot_to_text(dot, "plain")


def dot_to_png_bytes(dot: str) -> bytes:
    """
    Convert DOT to PNG bytes.
    """
    return render_dot_to_bytes(dot, "png")


def dot_to_pdf_bytes(dot: str) -> bytes:
    """
    Convert DOT to PDF bytes.
    """
    return render_dot_to_bytes(dot, "pdf")


def render_dot_to_text(
    dot: str,
    fmt: str,
    *,
    timeout_seconds: int = DEFAULT_DOT_TIMEOUT_SECONDS,
) -> str:
    """
    Render DOT to a text-based Graphviz format such as svg or plain.
    """
    fmt = _normalize_format(fmt)

    if fmt not in SUPPORTED_TEXT_FORMATS:
        raise ValueError(
            f"Format '{fmt}' is not a supported text format. "
            f"Supported text formats: {sorted(SUPPORTED_TEXT_FORMATS)}"
        )

    return render_dot_to_bytes(
        dot,
        fmt,
        timeout_seconds=timeout_seconds,
    ).decode("utf-8")


def render_dot_to_bytes(
    dot: str,
    fmt: str,
    *,
    timeout_seconds: int = DEFAULT_DOT_TIMEOUT_SECONDS,
) -> bytes:
    """
    Render DOT to raw bytes for any supported Graphviz output format.

    Supported formats:
    - svg
    - plain
    - png
    - pdf
    """
    _validate_dot_input(dot)
    _check_graphviz_available()

    fmt = _normalize_format(fmt)
    if fmt not in SUPPORTED_FORMATS:
        raise ValueError(
            f"Unsupported Graphviz format '{fmt}'. "
            f"Supported formats: {sorted(SUPPORTED_FORMATS)}"
        )

    dot_path = _write_temp_dot_file(dot)

    try:
        return _run_graphviz(dot_path, fmt, timeout_seconds=timeout_seconds)
    finally:
        _safe_remove(dot_path)


# ============================================================
# Validation / availability
# ============================================================

def _check_graphviz_available() -> None:
    """
    Ensure the `dot` executable is available on the system.
    """
    if shutil.which("dot") is None:
        raise GraphvizNotInstalledError(
            "Graphviz 'dot' executable not found in PATH. "
            "Install Graphviz to enable rendering."
        )


def _validate_dot_input(dot: str) -> None:
    if not isinstance(dot, str):
        raise TypeError(f"DOT input must be a string, got {type(dot).__name__}.")

    if not dot.strip():
        raise ValueError("DOT input must not be blank.")


def _normalize_format(fmt: str) -> str:
    if not isinstance(fmt, str):
        raise TypeError(f"Graphviz format must be a string, got {type(fmt).__name__}.")
    return fmt.strip().lower()


# ============================================================
# Temp file helpers
# ============================================================

def _write_temp_dot_file(dot: str) -> str:
    """
    Write DOT text to a temporary .dot file and return its path.
    """
    with tempfile.NamedTemporaryFile(
        mode="w",
        suffix=".dot",
        delete=False,
        encoding="utf-8",
    ) as handle:
        handle.write(dot)
        return handle.name


def _safe_remove(path: str) -> None:
    try:
        os.remove(path)
    except OSError:
        pass


# ============================================================
# Graphviz execution
# ============================================================

def _run_graphviz(
    dot_path: str,
    fmt: str,
    *,
    timeout_seconds: int,
) -> bytes:
    """
    Run Graphviz `dot` and return stdout bytes.
    """
    cmd = ["dot", f"-T{fmt}", dot_path]

    try:
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        raise GraphvizExecutionError(
            f"Graphviz timed out after {timeout_seconds} seconds while rendering '{fmt}'."
        ) from exc
    except OSError as exc:
        raise GraphvizExecutionError(
            f"Failed to execute Graphviz 'dot': {exc}"
        ) from exc

    if result.returncode != 0:
        stderr_text = result.stderr.decode("utf-8", errors="ignore").strip()
        raise GraphvizExecutionError(
            f"Graphviz failed while rendering '{fmt}'."
            + (f"\n{stderr_text}" if stderr_text else "")
        )

    return result.stdout