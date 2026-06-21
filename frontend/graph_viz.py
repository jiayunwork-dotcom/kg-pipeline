from typing import Dict, Any, List, Set, Optional
from pyvis.network import Network


ENTITY_TYPE_COLORS = {
    "PER": "#FF6B6B",
    "ORG": "#4ECDC4",
    "LOC": "#45B7D1",
    "TIME": "#96CEB4",
    "EVENT": "#FFEAA7",
    "WORK": "#DDA0DD",
    "TECH": "#98D8C8",
    "UNKNOWN": "#B0B0B0",
}


def _get_entity_color(entity_type: str) -> str:
    return ENTITY_TYPE_COLORS.get(entity_type, ENTITY_TYPE_COLORS["UNKNOWN"])


def build_graph_visualization(
    nodes_data: List[Dict[str, Any]],
    edges_data: List[Dict[str, Any]],
    highlight_node: Optional[str] = None,
    height: str = "600px",
    width: str = "100%",
    physics_enabled: bool = True,
) -> Network:
    net = Network(
        height=height,
        width=width,
        bgcolor="#ffffff",
        font_color="#222222",
        directed=True,
        notebook=False,
    )

    node_degree: Dict[str, int] = {}
    for edge in edges_data:
        src = edge.get("source", "")
        tgt = edge.get("target", "")
        node_degree[src] = node_degree.get(src, 0) + 1
        node_degree[tgt] = node_degree.get(tgt, 0) + 1

    node_ids = set()
    for node in nodes_data:
        nid = node.get("id", node.get("name", ""))
        if not nid or nid in node_ids:
            continue
        node_ids.add(nid)

        degree = node_degree.get(nid, 1)
        size = max(15, min(60, 15 + degree * 3))
        etype = node.get("type", "UNKNOWN")
        color = _get_entity_color(etype)

        is_highlighted = (highlight_node is not None and nid == highlight_node)

        title_parts = [
            f"<b>{node.get('name', nid)}</b>",
            f"类型: {etype}",
            f"出现频次: {node.get('frequency', 1)}",
        ]
        aliases = node.get("aliases", [])
        if aliases:
            title_parts.append(f"别名: {', '.join(aliases[:5])}")

        net.add_node(
            nid,
            label=node.get("name", nid),
            title="<br>".join(title_parts),
            color={
                "background": color,
                "border": "#FFD700" if is_highlighted else "#333333",
                "highlight": {
                    "background": color,
                    "border": "#FF0000",
                },
            },
            size=size if not is_highlighted else size + 10,
            shape="dot",
            borderWidth=4 if is_highlighted else 1,
            font={"size": 14, "color": "#222222"},
        )

    edge_ids: Set[str] = set()
    for edge in edges_data:
        src = edge.get("source", "")
        tgt = edge.get("target", "")
        rel_type = edge.get("relation", "")
        edge_key = f"{src}->{tgt}:{rel_type}"

        if not src or not tgt or edge_key in edge_ids:
            continue
        if src not in node_ids or tgt not in node_ids:
            continue

        edge_ids.add(edge_key)
        confidence = float(edge.get("confidence", 0.5))
        width = max(1, min(8, 1 + confidence * 7))

        net.add_edge(
            src,
            tgt,
            label=rel_type,
            title=f"{rel_type}<br>置信度: {confidence:.4f}",
            width=width,
            arrows="to",
            color={
                "color": "#666666",
                "highlight": "#FF4444",
            },
            font={"size": 12, "align": "middle"},
        )

    if physics_enabled:
        net.set_options("""
        {
          "physics": {
            "forceAtlas2Based": {
              "gravitationalConstant": -50,
              "springLength": 100,
              "springConstant": 0.08
            },
            "maxVelocity": 50,
            "solver": "forceAtlas2Based",
            "timestep": 0.35,
            "stabilization": {
              "enabled": true,
              "iterations": 150,
              "updateInterval": 25
            }
          },
          "interaction": {
            "zoomView": true,
            "dragView": true,
            "dragNodes": true,
            "hover": true
          }
        }
        """)

    return net


def get_entity_legend() -> Dict[str, str]:
    return ENTITY_TYPE_COLORS
