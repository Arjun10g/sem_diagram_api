from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from app.models.request_models import (
    HealthResponseModel,
    ParseRequest,
    RenderRequest,
)
from app.models.response_models import (
    ConstraintResponse,
    DefinedParameterResponse,
    EdgeResponse,
    MessageResponse,
    NodeResponse,
    ParameterSpecResponse,
    ParseResponse,
    ParsedStatementResponse,
    RenderResponse,
)
from app.services.dot_renderer import DotRenderOptions
from app.services.pipeline import run_parse_pipeline, run_render_pipeline
from app.utils.example_loader import load_example_file
from app.utils.graphviz_helpers import dot_to_pdf_bytes, dot_to_png_bytes

router = APIRouter()

_ALLOWED_EXAMPLES = {"cfa.txt", "sem.txt", "mediation.txt", "growth.txt"}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _render_opts(request: RenderRequest) -> DotRenderOptions:
    return DotRenderOptions(**request.render.model_dump())

def _stmt_resp(stmt) -> ParsedStatementResponse:
    return ParsedStatementResponse(
        stmt_type=stmt.stmt_type.value, lhs=stmt.lhs, rhs=stmt.rhs,
        operator=stmt.operator, line_no=stmt.line_no, raw=stmt.raw,
        parameter=ParameterSpecResponse(**stmt.parameter.to_dict()),
        metadata=stmt.metadata,
    )

def _msg_resps(graph, include: bool) -> list[MessageResponse]:
    if not include: return []
    return [MessageResponse(**m.to_dict()) for m in graph.messages]

def _node_resps(graph, include: bool) -> list[NodeResponse]:
    if not include: return []
    return [NodeResponse(**n.to_dict()) for n in graph.nodes]

def _edge_resps(graph, include: bool) -> list[EdgeResponse]:
    if not include: return []
    return [EdgeResponse(
        source=e.source, target=e.target, relation=e.relation.value,
        parameter=ParameterSpecResponse(**e.parameter.to_dict()),
        directed=e.directed, bidirectional=e.bidirectional,
        label=e.label, graph_attrs=e.graph_attrs, metadata=e.metadata,
    ) for e in graph.edges]

def _meta(graph, include: bool) -> dict:
    return graph.metadata if include else {}

def _run(request: RenderRequest, *, include_dot: bool, include_svg: bool) -> dict:
    return run_render_pipeline(
        syntax=request.syntax,
        render_options=_render_opts(request),
        include_dot=include_dot,
        include_svg=include_svg,
        strict_validation=request.strict_validation,
    )


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/health", response_model=HealthResponseModel)
def health() -> HealthResponseModel:
    return HealthResponseModel()

@router.get("/examples")
def list_examples() -> dict:
    return {"examples": sorted(_ALLOWED_EXAMPLES)}

@router.get("/examples/{filename}")
def get_example(filename: str) -> dict:
    if filename not in _ALLOWED_EXAMPLES:
        raise HTTPException(status_code=404, detail="Example not found")
    return {"filename": filename, "syntax": load_example_file(filename)}

@router.post("/parse", response_model=ParseResponse)
def parse_endpoint(request: ParseRequest) -> ParseResponse:
    g = run_parse_pipeline(request.syntax)
    return ParseResponse(
        parsed_statements=[_stmt_resp(s) for s in g.statements],
        defined_parameters=[DefinedParameterResponse(**d.to_dict()) for d in g.defined_parameters],
        constraints=[ConstraintResponse(**c.to_dict()) for c in g.constraints],
        messages=[MessageResponse(**m.to_dict()) for m in g.messages],
        metadata=g.metadata,
    )

@router.post("/render", response_model=RenderResponse)
def render_endpoint(request: RenderRequest) -> RenderResponse:
    result = _run(request, include_dot=request.include_dot, include_svg=request.include_svg)
    g = result["graph"]
    return RenderResponse(
        dot=result.get("dot") if request.include_dot else None,
        svg=result.get("svg"),
        nodes=_node_resps(g, request.include_graph_json),
        edges=_edge_resps(g, request.include_graph_json),
        parsed_statements=[_stmt_resp(s) for s in g.statements],
        defined_parameters=[DefinedParameterResponse(**d.to_dict()) for d in g.defined_parameters],
        constraints=[ConstraintResponse(**c.to_dict()) for c in g.constraints],
        messages=_msg_resps(g, request.include_messages),
        metadata=_meta(g, request.include_validation_metadata),
    )

@router.post("/render/svg")
def render_svg_endpoint(request: RenderRequest) -> dict:
    result = _run(request, include_dot=False, include_svg=True)
    g = result["graph"]
    return {
        "svg": result.get("svg"),
        "messages": [m.model_dump() for m in _msg_resps(g, request.include_messages)],
        "metadata": _meta(g, request.include_validation_metadata),
    }

@router.post("/render/png")
def render_png_endpoint(request: RenderRequest) -> Response:
    result = _run(request, include_dot=True, include_svg=False)
    dot = result.get("dot")
    if not dot:
        raise HTTPException(status_code=500, detail="DOT rendering failed")
    try:
        return Response(content=dot_to_png_bytes(dot), media_type="image/png")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"PNG rendering failed: {exc}") from exc

@router.post("/render/pdf")
def render_pdf_endpoint(request: RenderRequest) -> Response:
    result = _run(request, include_dot=True, include_svg=False)
    dot = result.get("dot")
    if not dot:
        raise HTTPException(status_code=500, detail="DOT rendering failed")
    try:
        return Response(content=dot_to_pdf_bytes(dot), media_type="application/pdf")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"PDF rendering failed: {exc}") from exc
