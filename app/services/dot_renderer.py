from __future__ import annotations

import html
from dataclasses import dataclass
from typing import Dict, List, Optional, Set

from app.models.sem_graph import (
    Edge,
    EdgeRelation,
    Node,
    NodeType,
    SemGraph,
)


@dataclass
class DotRenderOptions:
    """Options controlling how the SEM graph is rendered to Graphviz DOT."""

    # Layout
    rankdir: str = "TB"
    splines: str = "spline"
    overlap: str = "false"
    ranksep: float = 1.0
    nodesep: float = 0.45
    pad: float = 0.25
    layout_preset: str = "sem"
    concentrate: bool = False
    newrank: bool = True

    # Visibility
    show_intercepts: bool = True
    show_variances: bool = False
    show_covariances: bool = True
    show_edge_labels: bool = True
    show_error_nodes: bool = True
    show_constant_nodes: bool = True
    show_residuals: bool = True

    # Layout heuristics
    group_indicators_by_factor: bool = True
    put_latents_same_rank: bool = True
    try_group_exogenous_structural_nodes: bool = True
    try_group_errors_near_targets: bool = True

    # Label behaviour
    use_html_labels: bool = False
    show_fixed_values: bool = True
    show_parameter_labels: bool = True
    show_start_values_in_tooltip: bool = True

    # Fonts
    graph_fontname: str = "Helvetica"
    node_fontname: str = "Helvetica"
    edge_fontname: str = "Helvetica"
    graph_fontsize: int = 11
    node_fontsize: int = 11
    edge_fontsize: int = 10

    # Colors
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

    # Pen widths
    latent_penwidth: float = 1.2
    observed_penwidth: float = 1.2
    intercept_penwidth: float = 1.0
    error_penwidth: float = 1.0
    constant_penwidth: float = 1.0
    loading_penwidth: float = 1.3
    regression_penwidth: float = 1.3
    covariance_penwidth: float = 1.2
    variance_penwidth: float = 1.1
    intercept_edge_penwidth: float = 1.0
    residual_edge_penwidth: float = 1.0

    # Shapes / styles
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

    # Node sizing (0.0 = auto)
    latent_width: float = 0.0
    latent_height: float = 0.0
    observed_width: float = 0.0
    observed_height: float = 0.0

    # Arrowheads
    arrowsize: float = 0.8
    arrowhead_loading: str = "normal"
    arrowhead_regression: str = "normal"
    arrowhead_covariance: str = "normal"
    arrowtail_covariance: str = "normal"

    # Edge geometry
    add_tooltips: bool = True
    minlen_loading: int = 2
    minlen_regression: int = 1
    minlen_residual: int = 1

    # Graph title
    graph_label: str = ""
    graph_labelloc: str = "t"

    # Factor clustering
    draw_factor_clusters: bool = False
    cluster_fillcolor: str = "#F0F4FF"
    cluster_color: str = "#B8C8E8"
    cluster_penwidth: float = 0.8

    # Node font color
    latent_fontcolor: str = "#0f172a"
    observed_fontcolor: str = "#0f172a"

    # Residual arrowhead
    arrowhead_residual: str = "normal"

    # Misc
    include_comments: bool = True


def render_sem_graph_to_dot(
    graph: SemGraph,
    options: Optional[DotRenderOptions] = None,
) -> str:
    """Render a SemGraph into Graphviz DOT source."""
    return _DotRenderer(graph=graph, options=options or DotRenderOptions()).render()


class _DotRenderer:
    def __init__(self, graph: SemGraph, options: DotRenderOptions):
        self.graph = graph
        self.options = options
        self.lines: List[str] = []
        self.node_lookup: Dict[str, Node] = {n.name: n for n in graph.nodes}

    def render(self) -> str:
        if not self.graph.nodes:
            return (
                'digraph SEM {\n'
                '  graph [layout=dot, bgcolor="white"];\n'
                '  node [shape=note, fontname=Helvetica];\n'
                '  empty [label="No valid SEM graph to render"];\n'
                '}'
            )
        self._start_graph()
        self._emit_graph_attributes()
        self._emit_global_defaults()
        self._emit_nodes()
        self._emit_rank_constraints()
        if self.options.draw_factor_clusters:
            self._emit_factor_clusters()
        self._emit_edges()
        self._end_graph()
        return "\n".join(self.lines)

    def _start_graph(self) -> None:
        self.lines.append("digraph SEM {")
        if self.options.include_comments:
            self.lines.append("  // Generated by dot_renderer.py")

    def _end_graph(self) -> None:
        self.lines.append("}")

    # ── Effective layout ──────────────────────────────────────────────────

    def _effective_ranksep(self) -> float:
        if self.options.layout_preset == "compact": return 0.65
        if self.options.layout_preset == "wide":    return 1.4
        return self.options.ranksep

    def _effective_nodesep(self) -> float:
        if self.options.layout_preset == "compact": return 0.28
        if self.options.layout_preset == "wide":    return 0.75
        return self.options.nodesep

    def _rankdir(self) -> str:
        return self.options.rankdir.upper()

    # ── Graph / global attributes ─────────────────────────────────────────

    def _emit_graph_attributes(self) -> None:
        o = self.options
        self.lines.append(
            f'  graph [layout=dot, '
            f'bgcolor="{_esc(o.background_color)}", '
            f'overlap={o.overlap}, '
            f'splines={o.splines}, '
            f'ranksep={self._effective_ranksep()}, '
            f'nodesep={self._effective_nodesep()}, '
            f'pad={o.pad}, '
            f'concentrate={str(o.concentrate).lower()}, '
            f'newrank={str(o.newrank).lower()}, '
            f'fontname="{_esc(o.graph_fontname)}", '
            f'fontsize={o.graph_fontsize}];'
        )
        self.lines.append(f"  rankdir={o.rankdir};")
        if o.graph_label:
            self.lines.append(
                f'  label="{_esc(o.graph_label)}"; labelloc="{o.graph_labelloc}"; ' 
                f'labelfontname="{_esc(o.graph_fontname)}"; labelfontsize={o.graph_fontsize + 2};' 
            )

    def _emit_global_defaults(self) -> None:
        o = self.options
        self.lines.append(
            f'  node [fontname="{_esc(o.node_fontname)}", '
            f'fontsize={o.node_fontsize}, '
            f'color="{o.default_node_color}"];'
        )
        self.lines.append(
            f'  edge [fontname="{_esc(o.edge_fontname)}", '
            f'fontsize={o.edge_fontsize}, '
            f'color="{o.default_edge_color}", '
            f'arrowsize={o.arrowsize}];'
        )

    # ── Visibility ────────────────────────────────────────────────────────

    def _nv(self, node: Node) -> bool:
        if node.node_type == NodeType.INTERCEPT and not self.options.show_intercepts: return False
        if node.node_type == NodeType.ERROR and not self.options.show_error_nodes: return False
        if node.node_type == NodeType.CONSTANT and not self.options.show_constant_nodes: return False
        return True

    def _ev(self, edge: Edge) -> bool:
        if edge.relation == EdgeRelation.INTERCEPT and not self.options.show_intercepts: return False
        if edge.relation == EdgeRelation.VARIANCE and not self.options.show_variances: return False
        if edge.relation == EdgeRelation.COVARIANCE and not self.options.show_covariances: return False
        if edge.relation == EdgeRelation.RESIDUAL and not self.options.show_residuals: return False
        s = self.node_lookup.get(edge.source)
        t = self.node_lookup.get(edge.target)
        if s is None or t is None: return False
        return self._nv(s) and self._nv(t)

    # ── Nodes ─────────────────────────────────────────────────────────────

    def _emit_nodes(self) -> None:
        for node in self.graph.nodes:
            if self._nv(node):
                self.lines.append(f"  {self._nid(node)} [{self._node_attrs(node)}];")

    def _node_attrs(self, node: Node) -> str:
        attrs: Dict[str, object] = {"label": self._node_label(node)}
        attrs.update(self._node_style(node))
        tgt = (node.metadata or {}).get("target")
        if tgt and (t := self.node_lookup.get(tgt)):
            attrs["group"] = self._nid(t)
        if self.options.add_tooltips:
            attrs["tooltip"] = self._node_tooltip(node)
        attrs.update({v: node.metadata[k] for k, v in
                      {"dot_color": "color", "dot_fillcolor": "fillcolor",
                       "dot_shape": "shape", "dot_style": "style",
                       "dot_penwidth": "penwidth"}.items()
                      if (node.metadata or {}).get(k) is not None})
        return _fmt(attrs)

    def _node_style(self, node: Node) -> Dict[str, object]:
        o = self.options
        if node.node_type == NodeType.LATENT:
            d = dict(shape=o.latent_shape, style=o.latent_style,
                     fillcolor=o.latent_fillcolor, color=o.latent_color,
                     penwidth=o.latent_penwidth, fontcolor=o.latent_fontcolor)
            if o.latent_width > 0:  d["width"] = o.latent_width
            if o.latent_height > 0: d["height"] = o.latent_height
            if o.latent_width > 0 or o.latent_height > 0: d["fixedsize"] = "false"
            return d
        if node.node_type == NodeType.OBSERVED:
            d = dict(shape=o.observed_shape, style=o.observed_style,
                     fillcolor=o.observed_fillcolor, color=o.observed_color,
                     penwidth=o.observed_penwidth, fontcolor=o.observed_fontcolor)
            if o.observed_width > 0:  d["width"] = o.observed_width
            if o.observed_height > 0: d["height"] = o.observed_height
            if o.observed_width > 0 or o.observed_height > 0: d["fixedsize"] = "false"
            return d
        if node.node_type == NodeType.INTERCEPT:
            return dict(shape=o.intercept_shape, style=o.intercept_style,
                        fillcolor=o.intercept_fillcolor, color=o.intercept_color,
                        penwidth=o.intercept_penwidth,
                        width=0.30, height=0.30, fixedsize="true")
        if node.node_type == NodeType.ERROR:
            return dict(shape=o.error_shape, style=o.error_style,
                        fillcolor=o.error_fillcolor, color=o.error_color,
                        penwidth=o.error_penwidth,
                        width=0.33, height=0.33, fixedsize="true")
        if node.node_type == NodeType.CONSTANT:
            return dict(shape=o.constant_shape, style=o.constant_style,
                        fillcolor=o.constant_fillcolor, color=o.constant_color,
                        penwidth=o.constant_penwidth)
        return {"shape": "box"}

    def _node_label(self, node: Node) -> str:
        lbl = node.label if node.label is not None else node.name
        return f"<{html.escape(lbl)}>" if self.options.use_html_labels else f'"{_esc(lbl)}"'

    def _node_tooltip(self, node: Node) -> str:
        parts = [f"name: {node.name}", f"type: {node.node_type.value}", f"role: {node.role.value}"]
        if node.layer: parts.append(f"layer: {node.layer}")
        if node.group: parts.append(f"group: {node.group}")
        return "\\n".join(parts)

    # ── Rank constraints ──────────────────────────────────────────────────

    def _emit_rank_constraints(self) -> None:
        if self.options.put_latents_same_rank:
            ids = [self._nid(n) for n in self.graph.nodes
                   if n.node_type == NodeType.LATENT and self._nv(n)]
            if len(ids) > 1:
                self.lines.append("  { rank=same; " + "; ".join(ids) + "; }")

        if self.options.group_indicators_by_factor:
            fi: Dict[str, List[str]] = {}
            for e in self.graph.edges:
                if e.relation == EdgeRelation.LOADING:
                    lst = fi.setdefault(e.source, [])
                    if e.target not in lst: lst.append(e.target)

            # Collect ALL indicators across all factors, deduplicated and
            # sorted by natural key.  A single combined set handles growth
            # curve models where every factor loads on every indicator.
            all_inds_ordered: List[str] = []
            seen_inds: set = set()
            for inds in fi.values():
                for nm in sorted(inds, key=_natsort):
                    if nm not in seen_inds:
                        seen_inds.add(nm)
                        all_inds_ordered.append(nm)

            # Sort the combined list one final time
            all_inds_ordered.sort(key=_natsort)
            ids = [self._nid(n) for nm in all_inds_ordered
                   if (n := self.node_lookup.get(nm)) and self._nv(n)]

            if len(ids) > 1:
                self.lines.append("  { rank=same; " + "; ".join(ids) + "; }")
                # Gentle ordering edges keep indicators in sorted left-to-right
                # order without fighting the loading edges.
                # constraint=false  — does NOT affect rank placement
                # weight=2          — soft nudge toward the correct order
                # style=invis       — completely hidden
                for a, b in zip(ids, ids[1:]):
                    self.lines.append(
                        f"  {a} -> {b} [style=invis, weight=1, constraint=true];")

        if self.options.try_group_exogenous_structural_nodes:
            srcs = {e.source for e in self.graph.edges if e.relation == EdgeRelation.REGRESSION}
            tgts = {e.target for e in self.graph.edges if e.relation == EdgeRelation.REGRESSION}
            ids = [self._nid(n) for nm in sorted(srcs - tgts)
                   if (n := self.node_lookup.get(nm)) and self._nv(n)]
            if len(ids) > 1:
                self.lines.append("  { rank=same; " + "; ".join(ids) + "; }")

        # Intercept triangles placement strategy:
        # In TB layout, factors → indicators is the main flow.  Intercept nodes
        # for indicators (INT__y1 etc.) should appear BELOW the indicator row,
        # keeping them completely clear of the factor→indicator crossing paths.
        # We achieve this by grouping all indicator intercept nodes into a
        # { rank=sink } block, which places them in the last rank tier.
        # Factor-level intercepts (INT__i, INT__s) have no observed indicators
        # below them, so they naturally sit above the factor row via the
        # high-weight edge pull — those stay without co-ranking.
        if self.options.show_intercepts:
            indicator_names = {
                e.target for e in self.graph.edges
                if e.relation == EdgeRelation.LOADING
            }
            sink_ids: List[str] = []
            for node in self.graph.nodes:
                if node.node_type != NodeType.INTERCEPT or not self._nv(node):
                    continue
                tgt_nm = (node.metadata or {}).get("target")
                if not tgt_nm:
                    continue
                tgt = self.node_lookup.get(tgt_nm)
                if tgt is None or not self._nv(tgt):
                    continue
                nid, tid = self._nid(node), self._nid(tgt)
                # Is the target an indicator (observed variable loaded by a factor)?
                if tgt_nm in indicator_names:
                    # Indicator-level intercept → push to bottom rank (sink)
                    sink_ids.append(nid)
                else:
                    # Factor-level intercept → co-rank just above the factor
                    self.lines.append(f"  {{ rank=same; {nid}; {tid}; }}")
            if sink_ids:
                self.lines.append("  { rank=sink; " + "; ".join(sink_ids) + "; }")

        # Error nodes co-ranked with their target
        if self.options.try_group_errors_near_targets:
            for node in self.graph.nodes:
                if node.node_type != NodeType.ERROR or not self._nv(node): continue
                tgt_nm = (node.metadata or {}).get("target")
                if not tgt_nm: continue
                tgt = self.node_lookup.get(tgt_nm)
                if tgt and self._nv(tgt):
                    self.lines.append(
                        f"  {{ rank=same; {self._nid(node)}; {self._nid(tgt)}; }}")

    # ── Edges ─────────────────────────────────────────────────────────────

    def _emit_factor_clusters(self) -> None:
        """
        Draw a labelled subgraph box around each factor and its indicators.
        Makes it visually clear which indicators belong to which latent factor.
        """
        o = self.options
        fi: Dict[str, List[str]] = {}
        for e in self.graph.edges:
            if e.relation == EdgeRelation.LOADING:
                lst = fi.setdefault(e.source, [])
                if e.target not in lst:
                    lst.append(e.target)

        for factor_name, inds in fi.items():
            factor_node = self.node_lookup.get(factor_name)
            if factor_node is None or not self._nv(factor_node):
                continue
            ind_ids = [self._nid(n) for nm in inds
                       if (n := self.node_lookup.get(nm)) and self._nv(n)]
            if not ind_ids:
                continue
            cluster_id = f"cluster_{self._nid(factor_node)}"
            self.lines.append(f'  subgraph {cluster_id} {{')
            self.lines.append(f'    style="rounded,filled";')
            self.lines.append(f'    fillcolor="{_esc(o.cluster_fillcolor)}";')
            self.lines.append(f'    color="{_esc(o.cluster_color)}";')
            self.lines.append(f'    penwidth={o.cluster_penwidth};')
            self.lines.append(f'    label="";')
            for nid in ind_ids:
                self.lines.append(f'    {nid};')
            self.lines.append('  }')

    def _emit_edges(self) -> None:
        order = {EdgeRelation.LOADING: 0, EdgeRelation.REGRESSION: 1,
                 EdgeRelation.COVARIANCE: 2, EdgeRelation.VARIANCE: 3,
                 EdgeRelation.INTERCEPT: 4, EdgeRelation.RESIDUAL: 5}
        visible = [e for e in self.graph.edges if self._ev(e)]

        def key(e: Edge):
            ln = (e.metadata or {}).get("line_no") or 10**9
            return (order.get(e.relation, 99), int(ln), _natsort(e.source), _natsort(e.target))

        for edge in sorted(visible, key=key):
            line = self._format_edge(edge)
            if line: self.lines.append(line)

        # Emit variance self-loops on error/residual nodes.
        # VARIANCE statements for observed nodes are consumed by the residual-node
        # machinery (ERR__x → x dashed arrow) and no VARIANCE edge is stored in the
        # graph.  We regenerate the loop here directly from the node list so that
        # error circles always display the canonical double-headed curved arc.
        self._emit_error_node_variance_loops()

    def _emit_error_node_variance_loops(self) -> None:
        """
        Emit a variance self-loop on every visible ERROR node.

        In textbook SEM diagrams the residual error circle (ε / ERR__x) always
        has a curved double-headed arrow arcing over it to indicate its variance
        is freely estimated.  Graphviz does not produce this automatically from
        the ERR__x → x residual edge, so we emit it explicitly.

        The loop uses the same headport/tailport logic as latent variance loops
        so it arcs on the correct side for the current rankdir.
        """
        if not self.options.show_error_nodes:
            return

        o = self.options
        rd = self._rankdir()
        # Loop arcs on the OUTER side of the error circle — away from the
        # dashed residual edge connecting it to the observed variable.
        # TB/LR/RL: error circles sit to the side of indicators → arc SOUTH.
        # BT: same logic inverted → arc NORTH.
        hp = tp = "n" if rd == "BT" else "s"

        loop_attrs = _fmt(dict(
            color=o.variance_color,
            penwidth=o.variance_penwidth,
            arrowsize=0.5,
            dir="both",
            arrowhead="normal",
            arrowtail="normal",
            constraint="false",
            weight=0,
            headport=hp,
            tailport=tp,
        ))

        for node in self.graph.nodes:
            if node.node_type != NodeType.ERROR:
                continue
            if not self._nv(node):
                continue
            # Loop arcs on the OBSERVED VARIABLE (target), not the ERR circle.
            # The ERR circle represents the residual term; the variance arc
            # belongs on the indicator box itself, arcing below it (south for
            # TB/LR/RL) so it sits clear of the incoming loading arrows.
            tgt_nm = (node.metadata or {}).get("target")
            if not tgt_nm:
                continue
            tgt_node = self.node_lookup.get(tgt_nm)
            if tgt_node is None or not self._nv(tgt_node):
                continue
            tid = self._nid(tgt_node)
            self.lines.append(f"  {tid} -> {tid} [{loop_attrs}];")

    def _format_edge(self, edge: Edge) -> Optional[str]:
        s = self.node_lookup.get(edge.source)
        t = self.node_lookup.get(edge.target)
        if s is None or t is None: return None
        attrs: Dict[str, object] = {}
        lbl = self._edge_label(edge)
        if lbl is not None:
            if edge.relation == EdgeRelation.INTERCEPT:
                attrs.update(taillabel=lbl, labeldistance=1.0, labelangle=0)
            else:
                attrs["label"] = lbl
        if self.options.add_tooltips:
            attrs["tooltip"] = self._edge_tooltip(edge)
        attrs.update(self._relation_attrs(edge))
        attrs.update({v: edge.metadata[k] for k, v in
                      {"dot_color": "color", "dot_style": "style",
                       "dot_penwidth": "penwidth", "dot_arrowhead": "arrowhead",
                       "dot_arrowtail": "arrowtail"}.items()
                      if (edge.metadata or {}).get(k) is not None})
        return f"  {self._nid(s)} -> {self._nid(t)} [{_fmt(attrs)}];"

    def _relation_attrs(self, edge: Edge) -> Dict[str, object]:
        o = self.options
        rd = self._rankdir()

        if edge.relation == EdgeRelation.LOADING:
            return dict(color=o.loading_color, penwidth=o.loading_penwidth,
                        minlen=o.minlen_loading, arrowhead=o.arrowhead_loading)

        if edge.relation == EdgeRelation.REGRESSION:
            return dict(color=o.regression_color, penwidth=o.regression_penwidth,
                        minlen=o.minlen_regression, arrowhead=o.arrowhead_regression)

        if edge.relation == EdgeRelation.COVARIANCE:
            return dict(dir="both",
                        arrowtail=o.arrowtail_covariance,
                        arrowhead=o.arrowhead_covariance,
                        color=o.covariance_color, penwidth=o.covariance_penwidth,
                        constraint="false")

        if edge.relation == EdgeRelation.VARIANCE:
            # Self-loop: arc on the side AWAY from the main loading-edge flow.
            #
            # TB  → loading edges go DOWN   → loop arcs at NORTH (up, clear)
            # BT  → loading edges go UP     → loop arcs at SOUTH (down, clear)
            # LR  → loading edges go RIGHT  → loop arcs at NORTH (up, clear of horizontal flow)
            # RL  → loading edges go LEFT   → loop arcs at NORTH (up, clear)
            #
            # headport + tailport pin the attachment point on the node.
            # dir=both gives arrowheads at both ends (textbook SEM convention).
            # constraint=false and weight=0 prevent the loop from distorting layout.
            # Arc on the QUIET side of the node — away from incoming edges.
            # TB: loading arrows arrive from north → loop arcs south (below).
            # BT: loading arrows arrive from south → loop arcs north (above).
            # LR: loading arrows arrive from west  → loop arcs south (below).
            # RL: loading arrows arrive from east  → loop arcs south (below).
            hp = tp = "n" if rd == "BT" else "s"
            return dict(
                color=o.variance_color,
                penwidth=o.variance_penwidth,
                arrowsize=0.6,
                dir="both",
                arrowhead="normal",
                arrowtail="normal",
                constraint="false",
                weight=0,
                headport=hp,
                tailport=tp,
            )

        if edge.relation == EdgeRelation.INTERCEPT:
            head = {"TB": "n", "BT": "s", "LR": "w", "RL": "e"}.get(rd, "n")
            return dict(color=o.intercept_edge_color, style="dashed",
                        penwidth=o.intercept_edge_penwidth, arrowsize=0.65,
                        constraint="true", weight=20, minlen=1, headport=head)

        if edge.relation == EdgeRelation.RESIDUAL:
            return dict(color=o.residual_edge_color, style="dashed",
                        penwidth=o.residual_edge_penwidth, arrowhead=o.arrowhead_residual,
                        minlen=o.minlen_residual, constraint="false", weight=0)

        return {"color": o.default_edge_color}

    def _edge_label(self, edge: Edge) -> Optional[str]:
        if not self.options.show_edge_labels: return None
        pieces: List[str] = []
        if self.options.show_parameter_labels and edge.parameter.label:
            pieces.append(edge.parameter.label)
        if self.options.show_fixed_values and edge.parameter.fixed is not None:
            # Suppress fixed=0 labels everywhere — a zero fixed value (e.g.
            # 0*y1 for the slope factor baseline, or 0*1 intercept constraints)
            # adds visual noise without meaningful information.  Non-zero fixed
            # values (1, 2, 3 slope loadings etc.) are still shown.
            if edge.parameter.fixed != 0.0:
                pieces.append(_nicenum(edge.parameter.fixed))
        if not pieces: return None
        txt = ", ".join(pieces)
        return f"<{html.escape(txt)}>" if self.options.use_html_labels else f'"{_esc(txt)}"'

    def _edge_tooltip(self, edge: Edge) -> str:
        parts = [f"relation: {edge.relation.value}",
                 f"source: {edge.source}", f"target: {edge.target}"]
        if edge.parameter.label: parts.append(f"label: {edge.parameter.label}")
        if edge.parameter.fixed is not None: parts.append(f"fixed: {edge.parameter.fixed}")
        if self.options.show_start_values_in_tooltip and edge.parameter.start is not None:
            parts.append(f"start: {edge.parameter.start}")
        if (edge.metadata or {}).get("line_no") is not None:
            parts.append(f"line: {edge.metadata['line_no']}")
        return "\\n".join(parts)

    def _nid(self, node: Node) -> str:
        return node.graph_id or Node.make_graph_id(node.name)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _esc(v: object) -> str:
    return str(v).replace("\\", "\\\\").replace('"', '\\"')

def _nicenum(v: float) -> str:
    return str(int(v)) if int(v) == v else f"{v:g}"

def _natsort(v: str) -> List[object]:
    import re
    out: List[object] = []
    for p in re.split(r"(\d+)", v):
        if not p: continue
        out.append(int(p) if p.isdigit() else p.lower())
    return out

def _fmt(attrs: Dict[str, object]) -> str:
    parts: List[str] = []
    for k, v in attrs.items():
        if v is None: continue
        if isinstance(v, str):
            if (v.startswith('"') and v.endswith('"')) or (v.startswith('<') and v.endswith('>')):
                parts.append(f"{k}={v}")
            else:
                parts.append(f'{k}="{_esc(v)}"')
        else:
            parts.append(f"{k}={v}")
    return ", ".join(parts)
