"""
svg_postprocess.py
==================
Post-processes the SVG string produced by Graphviz to add:

  1. data-sem-node="<name>" attributes on each node <g> element, so JS
     can identify nodes by their SEM name rather than Graphviz's numeric IDs.

  2. An inline <script> block that makes nodes draggable and reports
     final node positions back to R Shiny (or any parent window).

Coordinate system
-----------------
Graphviz SVG uses a root <g> with transform="… translate(tx ty)" that
converts from Graphviz point space (origin bottom-left, y-up) into SVG
space (origin top-left, y-down).  Concretely:

    svg_x = gv_x + tx
    svg_y = -gv_y + ty          (y axis flipped)

Node shapes inside the group have coordinates in the translated space:
    ellipse cx = gv_x,  cy = -gv_y
    polygon points centroid = (gv_x, -gv_y)

The drag JS inverts this to recover gv coords, which are then sent back
to the API as  NodePositionOverride.x / .y  on the next request.

R Shiny integration
-------------------
On drag-end the script calls:

    Shiny.setInputValue("sem_node_positions", positions, {priority:"event"})

where  positions  is  { node_name: { x: gv_x, y: gv_y }, … }  for ALL
visible semantic nodes (not just the dragged one).  R Shiny can store this
and pass it back in the next POST body as  node_positions[].

If Shiny is not available (e.g. standalone testing) the script falls back
to  window.parent.postMessage({ type: "sem_positions_update", … }).
"""

from __future__ import annotations

import re
from typing import Optional


# ============================================================
# Public API
# ============================================================

def inject_drag_interactivity(
    svg: str,
    shiny_input_id: str = "sem_node_positions",
) -> str:
    """
    Inject drag interactivity into a Graphviz-generated SVG string.

    Parameters
    ----------
    svg:
        The raw SVG string produced by  dot_to_svg().
    shiny_input_id:
        The Shiny input ID that receives the position update.
        Defaults to "sem_node_positions".

    Returns
    -------
    Modified SVG string with  data-sem-node  attributes and inline <script>.
    """
    if not svg or "<svg" not in svg:
        return svg

    svg = _add_node_data_attributes(svg)
    svg = _inject_script(svg, shiny_input_id=shiny_input_id)
    return svg


# ============================================================
# Step 1 — add data-sem-node attributes
# ============================================================

# Graphviz node groups look like:
#   <g id="node7" class="node">
#   <title>visual</title>
#   <ellipse .../>
_NODE_GROUP_RE = re.compile(
    r'(<g\s[^>]*class="node"[^>]*>)\s*\n\s*<title>([^<]+)</title>',
    re.MULTILINE,
)


def _add_node_data_attributes(svg: str) -> str:
    """
    Insert  data-sem-node="<name>"  into each node <g> opening tag.

    Skips synthetic nodes (ERR__ and INT__ prefixes) since those are
    internal details the user never drags directly.
    """
    def _patch_g_tag(match: re.Match) -> str:
        g_tag = match.group(1)      # e.g. <g id="node7" class="node">
        node_name = match.group(2).strip()

        # Include synthetic nodes in the drag layer — users may want to
        # reposition error circles.  Filter in JS if desired.
        safe_name = node_name.replace('"', "&quot;")

        # Insert the attribute before the closing > of the <g> tag.
        patched_g = g_tag[:-1] + f' data-sem-node="{safe_name}">'
        return patched_g + f'\n<title>{node_name}</title>'

    return _NODE_GROUP_RE.sub(_patch_g_tag, svg)


# ============================================================
# Step 2 — build and inject JS drag script
# ============================================================

def _inject_script(svg: str, *, shiny_input_id: str) -> str:
    script = _build_drag_script(shiny_input_id=shiny_input_id)
    # Insert just before closing </svg> tag.
    return svg.replace("</svg>", script + "\n</svg>", 1)


def _build_drag_script(*, shiny_input_id: str) -> str:
    """
    Build the complete inline <script> block for drag interactivity.

    Design decisions:
    - No external dependencies — pure SVG/DOM APIs only.
    - Uses SVG coordinate transforms (getScreenCTM) for accurate hit-testing
      regardless of CSS scaling or zooming.
    - Accumulates SVG-space translations per node to support multiple
      consecutive drags of the same node.
    - On drag-end, reports ALL node positions (moved and unmoved) so the
      server can pin the full layout on re-render.
    - SVG cursor CSS injected as a <style> sibling to the script.
    """
    return f"""\
<style>
  [data-sem-node] {{ cursor: grab; }}
  [data-sem-node].sem-dragging {{ cursor: grabbing; user-select: none; }}
  [data-sem-node]:hover > ellipse,
  [data-sem-node]:hover > circle,
  [data-sem-node]:hover > polygon,
  [data-sem-node]:hover > path {{
    filter: brightness(0.92);
  }}
</style>
<script type="text/javascript"><![CDATA[
(function() {{
  'use strict';

  // ---- Locate SVG root and extract root-group translate ----
  var svgEl = document.currentScript
    ? document.currentScript.closest('svg')
    : document.querySelector('svg');
  if (!svgEl) return;

  var rootG = svgEl.querySelector('g.graph');
  if (!rootG) return;

  var tx = 0, ty = 0;
  var tfStr = rootG.getAttribute('transform') || '';
  var tMatch = tfStr.match(/translate\\(([0-9.-]+)[,\\s]+([0-9.-]+)\\)/);
  if (tMatch) {{
    tx = parseFloat(tMatch[1]);
    ty = parseFloat(tMatch[2]);
  }}

  // ---- Coordinate helpers ----
  function getSvgPoint(e) {{
    var pt = svgEl.createSVGPoint();
    pt.x = e.clientX;
    pt.y = e.clientY;
    try {{
      return pt.matrixTransform(svgEl.getScreenCTM().inverse());
    }} catch (err) {{
      return pt;
    }}
  }}

  // Get original Graphviz point coords from a node group's shapes.
  // The shapes have their coordinates in the root-group's translated space,
  // where gv_x = shape_cx and gv_y = -shape_cy (y axis flipped).
  function getOriginalGvPos(nodeG) {{
    var el;
    el = nodeG.querySelector('ellipse');
    if (el) return {{ x: +el.getAttribute('cx'), y: -(+el.getAttribute('cy')) }};
    el = nodeG.querySelector('circle');
    if (el) return {{ x: +el.getAttribute('cx'), y: -(+el.getAttribute('cy')) }};
    // For polygon (box-shaped observed nodes)
    el = nodeG.querySelector('polygon');
    if (el) {{
      var pts = el.getAttribute('points').trim().split(/\\s+/).map(function(p) {{
        var parts = p.split(','); return {{ x: +parts[0], y: +parts[1] }};
      }});
      // Filter degenerate closing point (same as first)
      if (pts.length > 1 &&
          pts[0].x === pts[pts.length-1].x &&
          pts[0].y === pts[pts.length-1].y) {{
        pts = pts.slice(0, pts.length - 1);
      }}
      var cx = pts.reduce(function(s,p){{return s+p.x;}},0) / pts.length;
      var cy = pts.reduce(function(s,p){{return s+p.y;}},0) / pts.length;
      return {{ x: cx, y: -cy }};
    }}
    // Fallback: text anchor position
    el = nodeG.querySelector('text[text-anchor="middle"], text');
    if (el) return {{ x: +(el.getAttribute('x')||0), y: -(+(el.getAttribute('y')||0)) }};
    return null;
  }}

  // ---- Per-node drag state ----
  // svgTranslation: accumulated translate(dx, dy) applied to the <g> element
  // gvPos: current position in Graphviz point coords
  var nodeState = {{}};  // nodeName -> {{ svgTx, svgTy, gvPos }}

  var nodeGroups = svgEl.querySelectorAll('[data-sem-node]');
  nodeGroups.forEach(function(g) {{
    var name = g.getAttribute('data-sem-node');
    var orig = getOriginalGvPos(g);
    nodeState[name] = {{
      g: g,
      origGv: orig,
      svgTx: 0,
      svgTy: 0,
      gvPos: orig ? {{ x: orig.x, y: orig.y }} : null,
    }};
  }});

  // ---- Drag machinery ----
  var dragging = null;  // {{ name, startMouse, startSvgT }}

  svgEl.addEventListener('mousedown', function(e) {{
    var target = e.target.closest('[data-sem-node]');
    if (!target) return;
    e.preventDefault();
    e.stopPropagation();

    var name = target.getAttribute('data-sem-node');
    var state = nodeState[name];
    if (!state) return;

    target.classList.add('sem-dragging');
    var pt = getSvgPoint(e);
    dragging = {{
      name: name,
      startMouse: {{ x: pt.x, y: pt.y }},
      startSvgT: {{ x: state.svgTx, y: state.svgTy }},
    }};
  }});

  document.addEventListener('mousemove', function(e) {{
    if (!dragging) return;
    e.preventDefault();

    var pt = getSvgPoint(e);
    var dxSvg = pt.x - dragging.startMouse.x;
    var dySvg = pt.y - dragging.startMouse.y;

    var newTx = dragging.startSvgT.x + dxSvg;
    var newTy = dragging.startSvgT.y + dySvg;

    var state = nodeState[dragging.name];
    state.svgTx = newTx;
    state.svgTy = newTy;
    state.g.setAttribute('transform', 'translate(' + newTx + ',' + newTy + ')');

    // Update gvPos: dx_gv = dx_svg, dy_gv = -dy_svg (y axis flip)
    if (state.origGv) {{
      state.gvPos = {{
        x: state.origGv.x + newTx,
        y: state.origGv.y - newTy,
      }};
    }}
  }});

  document.addEventListener('mouseup', function(e) {{
    if (!dragging) return;
    var state = nodeState[dragging.name];
    state.g.classList.remove('sem-dragging');
    dragging = null;
    reportPositions();
  }});

  // Touch support (tablets / touch-screen displays)
  svgEl.addEventListener('touchstart', function(e) {{
    if (e.touches.length !== 1) return;
    var touch = e.touches[0];
    var fakeE = {{ clientX: touch.clientX, clientY: touch.clientY,
                   target: e.target, preventDefault: function(){{e.preventDefault();}},
                   stopPropagation: function(){{e.stopPropagation();}} }};
    svgEl.dispatchEvent(new MouseEvent('mousedown', fakeE));
  }}, {{ passive: false }});

  document.addEventListener('touchmove', function(e) {{
    if (!dragging || e.touches.length !== 1) return;
    e.preventDefault();
    var touch = e.touches[0];
    document.dispatchEvent(new MouseEvent('mousemove',
      {{ clientX: touch.clientX, clientY: touch.clientY }}));
  }}, {{ passive: false }});

  document.addEventListener('touchend', function(e) {{
    if (dragging) document.dispatchEvent(new MouseEvent('mouseup', {{}}));
  }});

  // ---- Position reporting ----
  function reportPositions() {{
    var positions = {{}};
    Object.keys(nodeState).forEach(function(name) {{
      var state = nodeState[name];
      if (state.gvPos) {{
        positions[name] = {{
          x: Math.round(state.gvPos.x * 100) / 100,
          y: Math.round(state.gvPos.y * 100) / 100,
        }};
      }}
    }});

    if (typeof Shiny !== 'undefined' && Shiny.setInputValue) {{
      Shiny.setInputValue('{shiny_input_id}', positions, {{ priority: 'event' }});
    }} else {{
      window.parent.postMessage(
        {{ type: 'sem_positions_update', positions: positions }}, '*'
      );
    }}
  }}

  // Expose programmatic access for R htmlwidgets / custom JS
  svgEl._semGetPositions = function() {{
    var positions = {{}};
    Object.keys(nodeState).forEach(function(name) {{
      var s = nodeState[name];
      if (s.gvPos) positions[name] = {{ x: s.gvPos.x, y: s.gvPos.y }};
    }});
    return positions;
  }};

  svgEl._semResetPositions = function() {{
    Object.keys(nodeState).forEach(function(name) {{
      var s = nodeState[name];
      s.svgTx = 0; s.svgTy = 0;
      s.gvPos = s.origGv ? {{ x: s.origGv.x, y: s.origGv.y }} : null;
      s.g.removeAttribute('transform');
    }});
  }};

}})();
]]></script>"""
