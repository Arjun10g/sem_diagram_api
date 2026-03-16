from __future__ import annotations

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class ParameterSpecResponse(BaseModel):
    label: Optional[str] = None
    fixed: Optional[float] = None
    start: Optional[float] = None
    free: bool = True


class ParsedStatementResponse(BaseModel):
    stmt_type: str
    lhs: str
    rhs: str
    operator: str
    line_no: int
    raw: str
    parameter: ParameterSpecResponse
    metadata: Dict[str, Any] = Field(default_factory=dict)


class NodeResponse(BaseModel):
    name: str
    node_type: str
    role: str
    graph_id: Optional[str] = None
    label: Optional[str] = None
    layer: Optional[str] = None
    group: Optional[str] = None
    x: Optional[float] = None
    y: Optional[float] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class EdgeResponse(BaseModel):
    source: str
    target: str
    relation: str
    parameter: ParameterSpecResponse
    directed: bool
    bidirectional: bool
    label: Optional[str] = None
    graph_attrs: Dict[str, Any] = Field(default_factory=dict)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class DefinedParameterResponse(BaseModel):
    name: str
    expression: str
    line_no: int
    raw: str


class ConstraintResponse(BaseModel):
    expression: str
    line_no: int
    raw: str


class MessageResponse(BaseModel):
    severity: str
    code: str
    message: str
    line_no: Optional[int] = None
    context: Optional[str] = None


class ParseResponse(BaseModel):
    parsed_statements: List[ParsedStatementResponse] = Field(default_factory=list)
    defined_parameters: List[DefinedParameterResponse] = Field(default_factory=list)
    constraints: List[ConstraintResponse] = Field(default_factory=list)
    messages: List[MessageResponse] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class RenderResponse(BaseModel):
    dot: Optional[str] = None
    svg: Optional[str] = None
    nodes: List[NodeResponse] = Field(default_factory=list)
    edges: List[EdgeResponse] = Field(default_factory=list)
    parsed_statements: List[ParsedStatementResponse] = Field(default_factory=list)
    defined_parameters: List[DefinedParameterResponse] = Field(default_factory=list)
    constraints: List[ConstraintResponse] = Field(default_factory=list)
    messages: List[MessageResponse] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)
