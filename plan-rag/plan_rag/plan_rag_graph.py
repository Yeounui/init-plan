from __future__ import annotations

import html
import json
import sqlite3
from pathlib import Path
from typing import Any


def write_graph_html(db_path: Path, output_path: Path) -> dict[str, Any]:
    graph = build_graph(db_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(render_html(graph), encoding="utf-8")
    return graph


def build_graph(db_path: Path) -> dict[str, Any]:
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    rows = connection.execute(
        """
        SELECT
            chunk_id, source_file, document_type, content, heading_path,
            category, start_line, end_line, vector_synced
        FROM chunks
        ORDER BY source_file, start_line
        """
    ).fetchall()

    nodes: dict[str, dict[str, Any]] = {}
    links: list[dict[str, str]] = []

    def add_node(node_id: str, label: str, kind: str, **extra: Any) -> None:
        nodes.setdefault(
            node_id,
            {
                "id": node_id,
                "label": label,
                "kind": kind,
                **extra,
            },
        )

    def add_link(source: str, target: str, label: str, **extra: Any) -> None:
        links.append({"source": source, "target": target, "label": label, **extra})

    add_node("root", "Plan RAG", "root")

    for row in rows:
        source_file = row["source_file"]
        doc_id = f"doc:{source_file}"
        add_node(
            doc_id,
            source_file,
            "document",
            document_type=row["document_type"],
            category=row["category"],
        )
        add_link("root", doc_id, "document")

        parent_id = doc_id
        heading_path = json.loads(row["heading_path"])
        heading_parts: list[str] = []
        for heading in heading_path:
            heading_parts.append(heading)
            heading_id = f"heading:{source_file}:{'/'.join(heading_parts)}"
            add_node(
                heading_id,
                heading,
                "heading",
                source_file=source_file,
                path=" > ".join(heading_parts),
            )
            add_link(parent_id, heading_id, "contains")
            parent_id = heading_id

        chunk_id = f"chunk:{row['chunk_id']}"
        add_node(
            chunk_id,
            f"{source_file}:{row['start_line']}-{row['end_line']}",
            "chunk",
            source_file=source_file,
            heading_path=" > ".join(heading_path),
            start_line=row["start_line"],
            end_line=row["end_line"],
            content=shorten(row["content"]),
            vector_synced=bool(row["vector_synced"]),
        )
        add_link(parent_id, chunk_id, "chunk")

        category = row["category"]
        if category:
            tag_id = f"category:{category}"
            add_node(tag_id, f"category: {category}", "tag", tag_type="category")
            add_link(chunk_id, tag_id, "category")

    if table_exists(connection, "chunk_relations"):
        relation_rows = connection.execute(
            """
            SELECT
                source_chunk_id, target_id, target_kind, relation_type,
                score, evidence, source
            FROM chunk_relations
            ORDER BY source_chunk_id, relation_type, target_kind, target_id
            """
        ).fetchall()
        for row in relation_rows:
            source_id = f"chunk:{row['source_chunk_id']}"
            target_id = graph_target_id(row["target_kind"], row["target_id"])
            if source_id not in nodes or target_id not in nodes:
                continue
            add_link(
                source_id,
                target_id,
                row["relation_type"],
                relation_type=row["relation_type"],
                score=row["score"],
                evidence=row["evidence"],
                source_kind=row["source"],
            )

    return {"nodes": list(nodes.values()), "links": dedupe_links(links)}


def table_exists(connection: sqlite3.Connection, name: str) -> bool:
    row = connection.execute(
        """
        SELECT 1
        FROM sqlite_master
        WHERE type = 'table' AND name = ?
        """,
        (name,),
    ).fetchone()
    return row is not None


def graph_target_id(target_kind: str, target_id: str) -> str:
    if target_kind == "chunk":
        return f"chunk:{target_id}"
    if target_kind == "document":
        return f"doc:{target_id}"
    return f"{target_kind}:{target_id}"


def dedupe_links(links: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str, str]] = set()
    result: list[dict[str, Any]] = []
    for link in links:
        key = (link["source"], link["target"], link["label"])
        if key in seen:
            continue
        seen.add(key)
        result.append(link)
    return result


def shorten(value: str, limit: int = 360) -> str:
    compact = " ".join(value.split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 3] + "..."


def render_html(graph: dict[str, Any]) -> str:
    data = json.dumps(graph, ensure_ascii=False)
    escaped_data = html.escape(data, quote=False)
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Plan RAG Graph</title>
<style>
:root {{
  color-scheme: light;
  --bg: #f7f7f4;
  --panel: #ffffff;
  --ink: #202124;
  --muted: #626a73;
  --line: #d8d6cf;
  --accent: #2f6f73;
}}
* {{ box-sizing: border-box; }}
body {{
  margin: 0;
  font-family: ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  color: var(--ink);
  background: var(--bg);
}}
header {{
  height: 56px;
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 0 16px;
  border-bottom: 1px solid var(--line);
  background: var(--panel);
}}
h1 {{
  margin: 0;
  font-size: 16px;
  font-weight: 650;
  white-space: nowrap;
}}
input {{
  width: min(520px, 45vw);
  height: 34px;
  border: 1px solid var(--line);
  border-radius: 6px;
  padding: 0 10px;
  font: inherit;
}}
select,
input[type="number"] {{
  height: 34px;
  border: 1px solid var(--line);
  border-radius: 6px;
  padding: 0 8px;
  font: inherit;
  background: var(--panel);
}}
input[type="number"] {{
  width: 96px;
}}
main {{
  display: grid;
  grid-template-columns: minmax(0, 1fr) 340px;
  height: calc(100vh - 56px);
}}
svg {{
  width: 100%;
  height: 100%;
  display: block;
  background: #fbfbf8;
}}
aside {{
  border-left: 1px solid var(--line);
  background: var(--panel);
  padding: 14px;
  overflow: auto;
}}
.stat {{
  color: var(--muted);
  font-size: 13px;
}}
.node circle {{
  stroke: #fff;
  stroke-width: 1.6px;
}}
.node text {{
  font-size: 11px;
  paint-order: stroke;
  stroke: #fbfbf8;
  stroke-width: 3px;
  stroke-linejoin: round;
}}
.link {{
  stroke: #b8b5ad;
  stroke-opacity: .72;
}}
.dim {{
  opacity: .12;
}}
.selected circle {{
  stroke: #111;
  stroke-width: 2.2px;
}}
.kind {{
  display: inline-block;
  margin: 10px 6px 0 0;
  padding: 3px 7px;
  border: 1px solid var(--line);
  border-radius: 999px;
  font-size: 12px;
  color: var(--muted);
}}
pre {{
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  padding: 10px;
  border: 1px solid var(--line);
  border-radius: 6px;
  background: #fafafa;
  font-size: 12px;
  line-height: 1.45;
}}
@media (max-width: 860px) {{
  header {{ flex-wrap: wrap; height: auto; min-height: 56px; padding: 10px; }}
  input {{ width: 100%; }}
  main {{ grid-template-columns: 1fr; grid-template-rows: 65vh auto; height: auto; }}
  aside {{ border-left: 0; border-top: 1px solid var(--line); }}
}}
</style>
</head>
<body>
<header>
  <h1>Plan RAG Graph</h1>
  <input id="search" type="search" placeholder="Filter by file, heading, or content">
  <select id="relation-filter" aria-label="Filter relation type">
    <option value="">All relations</option>
  </select>
  <input id="score-filter" type="number" min="0" max="1" step="0.05" value="0" aria-label="Minimum semantic score">
  <div class="stat" id="stats"></div>
</header>
<main>
  <svg id="graph" role="img" aria-label="Plan RAG knowledge graph"></svg>
  <aside>
    <div id="details">Select a node.</div>
  </aside>
</main>
<script type="application/json" id="graph-data">{escaped_data}</script>
<script>
const data = JSON.parse(document.getElementById("graph-data").textContent);
const svg = document.getElementById("graph");
const details = document.getElementById("details");
const search = document.getElementById("search");
const relationFilter = document.getElementById("relation-filter");
const scoreFilter = document.getElementById("score-filter");
const stats = document.getElementById("stats");

const colors = {{
  root: "#202124",
  document: "#2f6f73",
  heading: "#725c9b",
  chunk: "#b35f3b",
  tag: "#6e7f39"
}};
const radii = {{ root: 12, document: 9, heading: 6, chunk: 4.5, tag: 5 }};
const nodeById = new Map(data.nodes.map(node => [node.id, node]));
const links = data.links.map(link => ({{
  ...link,
  sourceNode: nodeById.get(link.source),
  targetNode: nodeById.get(link.target)
}}));

let width = 0;
let height = 0;
let selected = null;
let pointer = null;
let transform = {{ x: 0, y: 0, k: 1 }};

for (const node of data.nodes) {{
  node.x = Math.random() * 800;
  node.y = Math.random() * 600;
  node.vx = 0;
  node.vy = 0;
}}

for (const relationType of relationTypes(data.links)) {{
  const option = document.createElement("option");
  option.value = relationType;
  option.textContent = relationType;
  relationFilter.appendChild(option);
}}

const linkLayer = svg.appendChild(ns("g"));
const nodeLayer = svg.appendChild(ns("g"));
const linkEls = links.map(link => {{
  const line = ns("line");
  line.setAttribute("class", `link relation-${{link.relation_type || link.label}}`);
  line.setAttribute("stroke-width", relationWidth(link));
  line.setAttribute("stroke", relationColor(link));
  linkLayer.appendChild(line);
  return line;
}});
const nodeEls = data.nodes.map(node => {{
  const group = ns("g");
  group.setAttribute("class", "node");
  group.tabIndex = 0;
  const circle = ns("circle");
  circle.setAttribute("r", String(radii[node.kind] || 5));
  circle.setAttribute("fill", colors[node.kind] || "#888");
  const text = ns("text");
  text.setAttribute("x", "8");
  text.setAttribute("y", "4");
  text.textContent = node.label.length > 34 ? node.label.slice(0, 31) + "..." : node.label;
  group.appendChild(circle);
  group.appendChild(text);
  group.addEventListener("pointerdown", event => startDrag(event, node));
  group.addEventListener("click", () => selectNode(node));
  group.addEventListener("keydown", event => {{
    if (event.key === "Enter") selectNode(node);
  }});
  nodeLayer.appendChild(group);
  return group;
}});

svg.addEventListener("wheel", event => {{
  event.preventDefault();
  const delta = event.deltaY > 0 ? 0.92 : 1.08;
  transform.k = clamp(transform.k * delta, 0.25, 3);
  applyTransform();
}}, {{ passive: false }});

svg.addEventListener("pointerdown", event => {{
  if (event.target !== svg) return;
  pointer = {{ mode: "pan", x: event.clientX, y: event.clientY, tx: transform.x, ty: transform.y }};
  svg.setPointerCapture(event.pointerId);
}});
svg.addEventListener("pointermove", event => {{
  if (!pointer) return;
  if (pointer.mode === "pan") {{
    transform.x = pointer.tx + event.clientX - pointer.x;
    transform.y = pointer.ty + event.clientY - pointer.y;
    applyTransform();
  }} else if (pointer.mode === "drag") {{
    pointer.node.fx = (event.clientX - transform.x) / transform.k;
    pointer.node.fy = (event.clientY - transform.y) / transform.k;
  }}
}});
svg.addEventListener("pointerup", event => {{
  if (pointer?.mode === "drag") {{
    pointer.node.fx = null;
    pointer.node.fy = null;
  }}
  pointer = null;
  if (svg.hasPointerCapture(event.pointerId)) svg.releasePointerCapture(event.pointerId);
}});

search.addEventListener("input", updateFilter);
relationFilter.addEventListener("change", updateFilter);
scoreFilter.addEventListener("input", updateFilter);
window.addEventListener("resize", resize);

resize();
selectNode(data.nodes[0]);
requestAnimationFrame(tick);

function tick() {{
  simulate();
  draw();
  requestAnimationFrame(tick);
}}

function simulate() {{
  const cx = width / 2;
  const cy = height / 2;
  for (const link of links) {{
    const a = link.sourceNode;
    const b = link.targetNode;
    const dx = b.x - a.x;
    const dy = b.y - a.y;
    const distance = Math.max(1, Math.hypot(dx, dy));
    const target = link.relation_type ? 118 : (link.label === "chunk" ? 34 : 72);
    const force = (distance - target) * 0.006;
    const fx = (dx / distance) * force;
    const fy = (dy / distance) * force;
    a.vx += fx;
    a.vy += fy;
    b.vx -= fx;
    b.vy -= fy;
  }}
  for (let i = 0; i < data.nodes.length; i++) {{
    const a = data.nodes[i];
    for (let j = i + 1; j < data.nodes.length; j++) {{
      const b = data.nodes[j];
      const dx = b.x - a.x || 0.1;
      const dy = b.y - a.y || 0.1;
      const d2 = Math.max(36, dx * dx + dy * dy);
      const force = 38 / d2;
      a.vx -= dx * force;
      a.vy -= dy * force;
      b.vx += dx * force;
      b.vy += dy * force;
    }}
  }}
  for (const node of data.nodes) {{
    node.vx += (cx - node.x) * 0.0008;
    node.vy += (cy - node.y) * 0.0008;
    if (node.fx != null) {{
      node.x = node.fx;
      node.y = node.fy;
      node.vx = 0;
      node.vy = 0;
    }} else {{
      node.x += node.vx;
      node.y += node.vy;
      node.vx *= 0.82;
      node.vy *= 0.82;
    }}
  }}
}}

function draw() {{
  links.forEach((link, index) => {{
    const line = linkEls[index];
    line.setAttribute("x1", link.sourceNode.x);
    line.setAttribute("y1", link.sourceNode.y);
    line.setAttribute("x2", link.targetNode.x);
    line.setAttribute("y2", link.targetNode.y);
  }});
  data.nodes.forEach((node, index) => {{
    nodeEls[index].setAttribute("transform", `translate(${{node.x}},${{node.y}})`);
  }});
}}

function selectNode(node) {{
  selected = node;
  nodeEls.forEach((element, index) => {{
    element.classList.toggle("selected", data.nodes[index] === node);
  }});
  const rows = Object.entries(node)
    .filter(([key]) => !["x", "y", "vx", "vy", "fx", "fy"].includes(key))
    .map(([key, value]) => `<div><span class="kind">${{escapeHtml(key)}}</span></div><pre>${{escapeHtml(String(value))}}</pre>`)
    .join("");
  const connected = links
    .filter(link => link.source === node.id || link.target === node.id)
    .map(link => {{
      const other = link.source === node.id ? link.targetNode : link.sourceNode;
      return `<div>${{escapeHtml(link.label)}} -> ${{escapeHtml(other.label)}}</div>`;
    }})
    .join("");
  details.innerHTML = `<h2 style="font-size:16px;margin:0 0 4px">${{escapeHtml(node.label)}}</h2>${{rows}}<h3 style="font-size:13px">Links</h3><pre>${{connected || "No links"}}</pre>`;
}}

function updateFilter() {{
  const needle = search.value.trim().toLowerCase();
  const wantedRelation = relationFilter.value;
  const minScore = Number(scoreFilter.value || 0);
  let visible = 0;
  data.nodes.forEach((node, index) => {{
    const haystack = JSON.stringify(node).toLowerCase();
    const match = !needle || haystack.includes(needle);
    nodeEls[index].classList.toggle("dim", !match);
    if (match) visible++;
  }});
  linkEls.forEach((line, index) => {{
    const link = links[index];
    const textMatch = !needle ||
      JSON.stringify(link.sourceNode).toLowerCase().includes(needle) ||
      JSON.stringify(link.targetNode).toLowerCase().includes(needle);
    const relationMatch = !wantedRelation ||
      !link.relation_type ||
      link.relation_type === wantedRelation;
    const scoreMatch = !link.relation_type ||
      link.score == null ||
      Number(link.score) >= minScore;
    const match = textMatch && relationMatch && scoreMatch;
    line.classList.toggle("dim", !match);
  }});
  stats.textContent = `${{visible}} / ${{data.nodes.length}} nodes, ${{data.links.length}} links`;
}}

function resize() {{
  const rect = svg.getBoundingClientRect();
  width = rect.width;
  height = rect.height;
  svg.setAttribute("viewBox", `0 0 ${{width}} ${{height}}`);
  updateFilter();
  applyTransform();
}}

function startDrag(event, node) {{
  event.stopPropagation();
  pointer = {{ mode: "drag", node }};
  node.fx = node.x;
  node.fy = node.y;
  svg.setPointerCapture(event.pointerId);
}}

function applyTransform() {{
  const value = `translate(${{transform.x}} ${{transform.y}}) scale(${{transform.k}})`;
  linkLayer.setAttribute("transform", value);
  nodeLayer.setAttribute("transform", value);
}}

function ns(name) {{
  return document.createElementNS("http://www.w3.org/2000/svg", name);
}}

function clamp(value, min, max) {{
  return Math.max(min, Math.min(max, value));
}}

function relationWidth(link) {{
  if (link.label === "document") return "1.5";
  if (link.relation_type) return "1.25";
  return "1";
}}

function relationColor(link) {{
  const palette = {{
    links_to_document: "#2f6f73",
    links_to_chunk: "#2f6f73",
    same_heading: "#725c9b"
  }};
  return palette[link.relation_type] || "#b8b5ad";
}}

function relationTypes(links) {{
  return Array.from(new Set(
    links
      .map(link => link.relation_type)
      .filter(value => value)
  )).sort();
}}

function escapeHtml(value) {{
  return value.replace(/[&<>"']/g, char => ({{
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;"
  }}[char]));
}}
</script>
</body>
</html>
"""
