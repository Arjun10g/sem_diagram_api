from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any

from app.services.dot_renderer import DotRenderOptions, render_sem_graph_to_dot
from app.services.graph_builder import build_sem_graph
from app.services.parser import parse_sem_syntax
from app.services.validator import validate_sem_graph


class RenderServiceError(Exception):
    """Base exception for render service failures."""


class RenderValidationError(RenderServiceError):
    """Raised when user input or graph validation fails."""


class RenderPipelineError(RenderServiceError):
    """Raised when an unexpected pipeline failure occurs."""


# ============================================================
# Serialization helpers
# ============================================================

def _to_dict(obj: Any) -> dict[str, Any]:
    """
    Convert a model object into a plain dict.

    Supports:
    - dict
    - dataclass
    - pydantic model (model_dump)
    - plain object with __dict__
    """
    if obj is None:
        return {}

    if isinstance(obj, dict):
        return obj

    if is_dataclass(obj):
        return asdict(obj)

    if hasattr(obj, "model_dump"):
        return obj.model_dump()

    if hasattr(obj, "__dict__"):
        return {
            key: value
            for key, value in vars(obj).items()
            if not key.startswith("_")
        }

    return {"value": str(obj)}


def _serialize_node(node: Any) -> dict[str, Any]:
    data = _to_dict(node)

    node_id = data.get("name") or data.get("graph_id") or data.get("label")
    label = data.get("label") or data.get("name") or node_id
    kind = data.get("node_type", "unknown")
    role = data.get("role")

    reserved = {"name", "graph_id", "label", "node_type", "role"}
    attrs = {k: v for k, v in data.items() if k not in reserved}

    return {
        "id": None if node_id is None else str(node_id),
        "label": None if label is None else str(label),
        "kind": str(kind),
        "role": None if role is None else str(role),
        "attrs": attrs,
    }


def _serialize_edge(edge: Any) -> dict[str, Any]:
    data = _to_dict(edge)

    source = data.get("source")
    target = data.get("target")
    relation = data.get("relation", "path")
    label = data.get("label")
    directed = data.get("directed", True)

    reserved = {"source", "target", "relation", "label", "directed"}
    attrs = {k: v for k, v in data.items() if k not in reserved}

    return {
        "source": None if source is None else str(source),
        "target": None if target is None else str(target),
        "relation": str(relation),
        "label": None if label is None else str(label),
        "directed": bool(directed),
        "attrs": attrs,
    }


def _serialize_message(message: Any) -> dict[str, Any]:
    """
    Normalize graph/service messages into:
    {
      "level": "info" | "warning" | "error",
      "code": str | None,
      "text": str,
      "line_no": int | None,
      "context": str | None
    }
    """
    if isinstance(message, str):
        return {
            "level": "info",
            "code": None,
            "text": message,
            "line_no": None,
            "context": None,
        }

    data = _to_dict(message)

    level = str(data.get("severity", data.get("level", "info"))).lower()
    if level not in {"info", "warning", "error"}:
        level = "info"

    return {
        "level": level,
        "code": data.get("code"),
        "text": str(data.get("message", data.get("text", ""))),
        "line_no": data.get("line_no"),
        "context": data.get("context"),
    }


def _extract_nodes(graph: Any) -> list[dict[str, Any]]:
    return [_serialize_node(node) for node in getattr(graph, "nodes", []) or []]


def _extract_edges(graph: Any) -> list[dict[str, Any]]:
    return [_serialize_edge(edge) for edge in getattr(graph, "edges", []) or []]


def _extract_messages(graph: Any) -> list[dict[str, Any]]:
    return [_serialize_message(msg) for msg in getattr(graph, "messages", []) or []]


# ============================================================
# Option handling
# ============================================================

def _coerce_service_options(options: dict[str, Any] | None) -> dict[str, Any]:
    """
    Normalize high-level service options.

    These options include validation behavior and render options.
    """
    options = options or {}

    return {
        "strict_validation": bool(options.get("strict_validation", True)),
        "render": dict(options.get("render", {})),
    }


def _build_render_options(render_options: dict[str, Any]) -> DotRenderOptions:
    """
    Convert API-level render options into DotRenderOptions.

    Unknown keys are ignored so the API can evolve safely.
    """
    base = DotRenderOptions()
    valid_fields = set(base.__dataclass_fields__.keys())

    filtered = {
        key: value
        for key, value in render_options.items()
        if key in valid_fields
    }

    return DotRenderOptions(**filtered)


# ============================================================
# Main render pipeline
# ============================================================

def render_from_syntax(
    syntax: str,
    options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Full SEM rendering pipeline.

    Input:
        syntax: lavaan-style SEM syntax
        options: optional service/render options, e.g.
            {
                "strict_validation": true,
                "render": {
                    "rankdir": "TB",
                    "layout_preset": "sem",
                    "show_variances": false,
                    "show_intercepts": true,
                    "latent_fillcolor": "#EAF2FF",
                    "regression_color": "#2F5C85"
                }
            }

    Returns:
        {
            "dot": str,
            "nodes": list[dict],
            "edges": list[dict],
            "messages": list[dict],
            "metadata": dict
        }
    """
    if not isinstance(syntax, str):
        raise RenderValidationError("syntax must be a string")

    syntax = syntax.strip()
    if not syntax:
        raise RenderValidationError("syntax must not be blank")

    service_opts = _coerce_service_options(options)
    render_opts = _build_render_options(service_opts["render"])

    try:
        parsed_graph = parse_sem_syntax(syntax)
        semantic_graph = build_sem_graph(parsed_graph)
        validated_graph = validate_sem_graph(semantic_graph)
    except ValueError as exc:
        raise RenderValidationError(str(exc)) from exc
    except Exception as exc:
        raise RenderPipelineError(f"Unexpected pipeline failure: {exc}") from exc

    if service_opts["strict_validation"] and validated_graph.has_errors():
        messages = _extract_messages(validated_graph)
        error_text = "; ".join(
            msg["text"] for msg in messages if msg["level"] == "error"
        ) or "Graph validation failed."
        raise RenderValidationError(error_text)

    try:
        dot = render_sem_graph_to_dot(validated_graph, options=render_opts)
    except ValueError as exc:
        raise RenderValidationError(f"DOT rendering failed: {exc}") from exc
    except Exception as exc:
        raise RenderPipelineError(f"Unexpected DOT renderer failure: {exc}") from exc

    return {
        "dot": dot,
        "nodes": _extract_nodes(validated_graph),
        "edges": _extract_edges(validated_graph),
        "messages": _extract_messages(validated_graph),
        "metadata": getattr(validated_graph, "metadata", {}) or {},
    }