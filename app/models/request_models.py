from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


class RenderOptionsModel(BaseModel):
    """API-facing render options. Maps onto DotRenderOptions in dot_renderer.py."""

    # ── Layout ────────────────────────────────────────────────────────────────
    rankdir: str = Field(default="TB")
    splines: str = Field(default="spline")
    overlap: str = Field(default="false")
    ranksep: float = Field(default=1.0, ge=0.0)
    nodesep: float = Field(default=0.45, ge=0.0)
    pad: float = Field(default=0.3, ge=0.0)
    layout_preset: str = Field(default="sem")
    concentrate: bool = False
    newrank: bool = True

    # ── Visibility ────────────────────────────────────────────────────────────
    show_intercepts: bool = True
    show_variances: bool = False
    show_covariances: bool = True
    show_edge_labels: bool = True
    show_error_nodes: bool = True
    show_constant_nodes: bool = True
    show_residuals: bool = True

    # ── Layout heuristics ─────────────────────────────────────────────────────
    group_indicators_by_factor: bool = True
    put_latents_same_rank: bool = True
    try_group_exogenous_structural_nodes: bool = True
    try_group_errors_near_targets: bool = True

    # ── Labels ────────────────────────────────────────────────────────────────
    use_html_labels: bool = False
    show_fixed_values: bool = True
    show_parameter_labels: bool = True
    show_start_values_in_tooltip: bool = True

    # ── Graph title ───────────────────────────────────────────────────────────
    graph_label: str = ""
    graph_labelloc: str = "t"

    # ── Fonts ─────────────────────────────────────────────────────────────────
    graph_fontname: str = "Helvetica"
    node_fontname: str = "Helvetica"
    edge_fontname: str = "Helvetica"
    graph_fontsize: int = Field(default=11, ge=1)
    node_fontsize: int = Field(default=11, ge=1)
    edge_fontsize: int = Field(default=10, ge=1)

    # ── Colors ────────────────────────────────────────────────────────────────
    background_color: str = "white"
    default_node_color: str = "#2B2B2B"
    default_edge_color: str = "#444444"
    latent_fillcolor: str = "#EAF2FF"
    latent_color: str = "#2B2B2B"
    observed_fillcolor: str = "#FFFFFF"
    observed_color: str = "#2B2B2B"
    intercept_fillcolor: str = "#FFF8DC"
    intercept_color: str = "#666666"
    error_fillcolor: str = "#FDECEC"
    error_color: str = "#8B3A3A"
    constant_fillcolor: str = "#F5F5F5"
    constant_color: str = "#666666"
    loading_color: str = "#444444"
    regression_color: str = "#2F5C85"
    covariance_color: str = "#7A4E2D"
    variance_color: str = "#888888"
    intercept_edge_color: str = "#666666"
    residual_edge_color: str = "#8B3A3A"

    # ── Node font colors ───────────────────────────────────────────────────────
    latent_fontcolor: str = "#0f172a"
    observed_fontcolor: str = "#0f172a"

    # ── Pen widths ────────────────────────────────────────────────────────────
    latent_penwidth: float = Field(default=1.2, ge=0.0)
    observed_penwidth: float = Field(default=1.2, ge=0.0)
    intercept_penwidth: float = Field(default=1.0, ge=0.0)
    error_penwidth: float = Field(default=1.0, ge=0.0)
    constant_penwidth: float = Field(default=1.0, ge=0.0)
    loading_penwidth: float = Field(default=1.3, ge=0.0)
    regression_penwidth: float = Field(default=1.3, ge=0.0)
    covariance_penwidth: float = Field(default=1.2, ge=0.0)
    variance_penwidth: float = Field(default=1.1, ge=0.0)
    intercept_edge_penwidth: float = Field(default=1.0, ge=0.0)
    residual_edge_penwidth: float = Field(default=1.0, ge=0.0)

    # ── Shapes / styles ───────────────────────────────────────────────────────
    latent_shape: str = "ellipse"
    observed_shape: str = "box"
    intercept_shape: str = "triangle"
    error_shape: str = "circle"
    constant_shape: str = "diamond"
    observed_style: str = "rounded,filled"
    latent_style: str = "filled"
    intercept_style: str = "filled"
    error_style: str = "filled,dashed"
    constant_style: str = "filled"

    # ── Node sizing (0.0 = auto) ───────────────────────────────────────────────
    latent_width: float = Field(default=0.0, ge=0.0)
    latent_height: float = Field(default=0.0, ge=0.0)
    observed_width: float = Field(default=0.0, ge=0.0)
    observed_height: float = Field(default=0.0, ge=0.0)

    # ── Factor clustering ─────────────────────────────────────────────────────
    draw_factor_clusters: bool = False
    cluster_fillcolor: str = "#F0F4FF"
    cluster_color: str = "#B8C8E8"
    cluster_penwidth: float = Field(default=0.8, ge=0.0)

    # ── Arrowheads — ALL ARROWHEAD FIELDS MUST APPEAR BEFORE THE VALIDATOR ────
    arrowsize: float = Field(default=0.8, ge=0.1)
    arrowhead_loading: str = "normal"
    arrowhead_regression: str = "normal"
    arrowhead_covariance: str = "normal"
    arrowtail_covariance: str = "normal"
    arrowhead_residual: str = "normal"

    # ── Edge geometry ─────────────────────────────────────────────────────────
    add_tooltips: bool = True
    minlen_loading: int = Field(default=2, ge=0)
    minlen_regression: int = Field(default=1, ge=0)
    minlen_residual: int = Field(default=1, ge=0)

    # ── Misc ──────────────────────────────────────────────────────────────────
    include_comments: bool = True

    # ── Validators (must come AFTER all field declarations) ───────────────────

    @field_validator("rankdir")
    @classmethod
    def validate_rankdir(cls, v: str) -> str:
        v = v.upper()
        if v not in {"TB", "LR", "BT", "RL"}:
            raise ValueError("rankdir must be one of: TB, LR, BT, RL")
        return v

    @field_validator("layout_preset")
    @classmethod
    def validate_layout_preset(cls, v: str) -> str:
        v = v.lower()
        if v not in {"sem", "compact", "wide"}:
            raise ValueError("layout_preset must be one of: sem, compact, wide")
        return v

    @field_validator("splines")
    @classmethod
    def validate_splines(cls, v: str) -> str:
        v = v.lower()
        if v not in {"spline", "true", "false", "curved", "ortho", "polyline", "line"}:
            raise ValueError("invalid splines value")
        return v

    @field_validator(
        "arrowhead_loading",
        "arrowhead_regression",
        "arrowhead_covariance",
        "arrowtail_covariance",
        "arrowhead_residual",
    )
    @classmethod
    def validate_arrowhead(cls, v: str) -> str:
        valid = {"normal", "vee", "open", "dot", "odot", "none",
                 "empty", "halfopen", "crow", "box", "diamond"}
        if v not in valid:
            raise ValueError(f"Invalid arrowhead: {v!r}")
        return v


class ParseRequest(BaseModel):
    syntax: str = Field(..., max_length=16_000, description="lavaan-style SEM syntax to parse")
    include_raw_statements: bool = True


class RenderRequest(BaseModel):
    syntax: str = Field(..., max_length=16_000, description="lavaan-style SEM syntax to render")
    strict_validation: bool = True
    render: RenderOptionsModel = Field(default_factory=RenderOptionsModel)
    include_dot: bool = True
    include_svg: bool = False
    include_graph_json: bool = True
    include_messages: bool = True
    include_validation_metadata: bool = True


class HealthResponseModel(BaseModel):
    status: str = "ok"
    service: str = "sem-diagram-api"
