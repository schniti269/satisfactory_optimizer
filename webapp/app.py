"""
Satisfactory Factory Janitor — Web Dashboard
Upload a .sav file and get a full factory analysis with issue detection.
"""

import os
import tempfile
from flask import Flask, render_template, request, jsonify, redirect, url_for
from save_parser import parse_save
from graph_analyzer import analyze_supply_chain, load_recipe_db, build_flow_graph, propagate_flow
from feedback_db import (add_feedback, get_feedback, get_feedback_stats,
                         get_feedback_by_id, get_all_tags, get_linked_feedback,
                         create_tickets_from_issues, auto_resolve_tickets,
                         get_tickets, update_ticket, get_ticket_stats)
from district_analyzer import detect_districts, compute_manifold_blocks, compute_ledger

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 200 * 1024 * 1024  # 200MB max upload

# Store parsed data in memory (single user app)
_current_factory = None
_current_issues = None
_graph_stats = None
_flow_nodes = None  # FlowNode graph for traceback
_flow_edges = None  # FlowEdge graph for traceback
_districts = None
_node_to_district = None
_manifold_blocks = None
_node_to_block = None
_custom_lassos = []  # user-defined polygon groups [{id, name, node_ids, polygon}]
_next_lasso_id = 1


@app.route("/")
def index():
    if _current_factory is None:
        return render_template("upload.html")
    return redirect(url_for("dashboard"))


@app.route("/upload", methods=["GET", "POST"])
def upload():
    global _current_factory, _current_issues, _graph_stats, _flow_nodes, _flow_edges
    global _districts, _node_to_district, _manifold_blocks, _node_to_block
    if request.method == "GET":
        return render_template("upload.html")

    file = request.files.get("savefile")
    if not file or not file.filename.endswith(".sav"):
        return render_template("upload.html", error="Please upload a .sav file")

    # Save to temp file and parse
    with tempfile.NamedTemporaryFile(suffix=".sav", delete=False) as tmp:
        file.save(tmp.name)
        tmp_path = tmp.name

    try:
        factory = parse_save(tmp_path)
        issues, graph_stats = analyze_supply_chain(factory)
        _current_factory = factory
        _current_issues = issues
        _graph_stats = graph_stats
        # Build flow graph for traceback queries
        recipe_db, by_norm = load_recipe_db()
        _flow_nodes, _flow_edges, _ = build_flow_graph(factory, recipe_db, by_norm)
        propagate_flow(_flow_nodes, _flow_edges)
        # District detection + manifold compression
        _districts, _node_to_district = detect_districts(
            _flow_nodes, _flow_edges, factory, issues)
        _manifold_blocks, _node_to_block = compute_manifold_blocks(
            _flow_nodes, _flow_edges)
        # Ticket workflow: auto-resolve old, create new
        session_name = factory.session_name if hasattr(factory, 'session_name') else None
        auto_resolve_tickets(issues, session_name)
        create_tickets_from_issues(issues, session_name)
    except Exception as e:
        return render_template("upload.html", error=f"Parse error: {e}")
    finally:
        os.unlink(tmp_path)

    return redirect(url_for("dashboard"))


@app.route("/dashboard")
def dashboard():
    if _current_factory is None:
        return redirect(url_for("upload"))
    return render_template("dashboard.html",
                           factory=_current_factory,
                           issues=_current_issues,
                           graph_stats=_graph_stats)


@app.route("/api/issues")
def api_issues():
    if _current_issues is None:
        return jsonify([])
    category = request.args.get("category")
    severity = request.args.get("severity")
    filtered = _current_issues
    if category:
        filtered = [i for i in filtered if i["category"] == category]
    if severity:
        filtered = [i for i in filtered if i["severity"] == severity]
    # Serialize positions
    for i in filtered:
        if i.get("position"):
            i["position"] = list(i["position"])
    return jsonify(filtered)


@app.route("/api/stats")
def api_stats():
    if _current_factory is None:
        return jsonify({})
    stats = dict(_current_factory.stats)
    if _graph_stats:
        stats["graph"] = _graph_stats
    return jsonify(stats)


@app.route("/api/buildings")
def api_buildings():
    if _current_factory is None:
        return jsonify([])
    category = request.args.get("category")
    recipe = request.args.get("recipe")
    buildings = list(_current_factory.buildings.values())
    if category:
        buildings = [b for b in buildings if b.category == category]
    if recipe:
        buildings = [b for b in buildings if b.recipe_name == recipe]
    return jsonify([{
        "id": b.id,
        "name": b.friendly_name,
        "category": b.category,
        "recipe": b.recipe_name,
        "clock_speed": round(b.clock_speed * 100, 1),
        "is_producing": b.is_producing,
        "productivity": round(b.productivity * 100, 1),
        "position": list(b.position),
        "connections": len(b.connections),
    } for b in buildings[:500]])  # limit for performance


@app.route("/api/bottlenecks")
def api_bottlenecks():
    """Return belt/pipe bottleneck issues with flow data."""
    if _current_issues is None:
        return jsonify([])
    bottlenecks = [i for i in _current_issues
                   if i["category"] in ("Belt Bottleneck", "Splitter Overload",
                                        "Merger Overload", "Output Backup")]
    for b in bottlenecks:
        if b.get("position"):
            b["position"] = list(b["position"])
    return jsonify(bottlenecks)


@app.route("/api/map_data")
def api_map_data():
    """Return all buildings + directed belt edges for map rendering."""
    if _current_factory is None:
        return jsonify({})

    # Build issue lookup: building_id -> worst severity
    issue_map = {}  # building_id -> {severity, category}
    if _current_issues:
        sev_rank = {"error": 0, "warning": 1, "info": 2}
        for issue in _current_issues:
            bid = issue.get("building_id")
            if not bid:
                continue
            existing = issue_map.get(bid)
            if not existing or sev_rank.get(issue["severity"], 3) < sev_rank.get(existing["severity"], 3):
                issue_map[bid] = {"severity": issue["severity"], "category": issue["category"]}

    # Buildings — include ID for traceback lookups
    blds = []
    for b in _current_factory.buildings.values():
        issue_info = issue_map.get(b.id)
        blds.append({
            "id": b.id,
            "x": b.position[0],
            "y": b.position[1],
            "cat": b.category,
            "name": b.friendly_name,
            "recipe": b.recipe_name,
            "clock": round(b.clock_speed * 100),
            "prod": b.is_producing,
            "sev": issue_info["severity"] if issue_info else None,
            "issue": issue_info["category"] if issue_info else None,
            "district": _node_to_district.get(b.id) if _node_to_district else None,
        })

    # Directed belt edges with src/dst IDs for traceback highlighting
    edges = []
    for belt_id, belt in _current_factory.belts.items():
        src = _current_factory.buildings.get(belt.src_building)
        dst = _current_factory.buildings.get(belt.dst_building)
        if src and dst:
            edges.append({
                "src": belt.src_building,
                "dst": belt.dst_building,
                "x1": src.position[0], "y1": src.position[1],
                "x2": dst.position[0], "y2": dst.position[1],
                "pipe": belt.is_pipe,
            })

    return jsonify({"buildings": blds, "edges": edges})


@app.route("/api/traceback/<path:building_id>")
def api_traceback(building_id):
    """Walk upstream + downstream from a building, return all involved node/edge IDs."""
    if _flow_nodes is None or _flow_edges is None:
        return jsonify({"error": "No graph loaded"}), 400
    if building_id not in _flow_nodes:
        return jsonify({"error": "Building not found in graph"}), 404

    direction = request.args.get("dir", "both")  # "up", "down", "both"
    max_depth = int(request.args.get("depth", 50))

    upstream_nodes = set()
    downstream_nodes = set()
    trace_edges = set()

    # BFS upstream (follow in_edges backward)
    if direction in ("up", "both"):
        queue = [(building_id, 0)]
        visited = {building_id}
        while queue:
            nid, depth = queue.pop(0)
            if depth > max_depth:
                break
            upstream_nodes.add(nid)
            node = _flow_nodes.get(nid)
            if not node:
                continue
            for eid in node.in_edges:
                edge = _flow_edges.get(eid)
                if not edge:
                    continue
                trace_edges.add(eid)
                if edge.src not in visited:
                    visited.add(edge.src)
                    queue.append((edge.src, depth + 1))

    # BFS downstream (follow out_edges forward)
    if direction in ("down", "both"):
        queue = [(building_id, 0)]
        visited = {building_id}
        while queue:
            nid, depth = queue.pop(0)
            if depth > max_depth:
                break
            downstream_nodes.add(nid)
            node = _flow_nodes.get(nid)
            if not node:
                continue
            for eid in node.out_edges:
                edge = _flow_edges.get(eid)
                if not edge:
                    continue
                trace_edges.add(eid)
                if edge.dst not in visited:
                    visited.add(edge.dst)
                    queue.append((edge.dst, depth + 1))

    all_nodes = upstream_nodes | downstream_nodes
    # Build ordered trace: upstream (reversed) -> origin -> downstream
    # For step-through, compute layers by BFS depth
    layers_up = []
    if direction in ("up", "both"):
        queue = [(building_id, 0)]
        visited_l = {building_id}
        depth_map = {building_id: 0}
        while queue:
            nid, d = queue.pop(0)
            node = _flow_nodes.get(nid)
            if not node:
                continue
            for eid in node.in_edges:
                edge = _flow_edges.get(eid)
                if edge and edge.src not in visited_l:
                    visited_l.add(edge.src)
                    depth_map[edge.src] = d + 1
                    queue.append((edge.src, d + 1))
        max_d = max(depth_map.values()) if depth_map else 0
        for layer in range(max_d, -1, -1):
            layer_nodes = [nid for nid, dep in depth_map.items() if dep == layer]
            if layer_nodes:
                layers_up.append(layer_nodes)

    layers_down = []
    if direction in ("down", "both"):
        queue = [(building_id, 0)]
        visited_l = {building_id}
        depth_map = {building_id: 0}
        while queue:
            nid, d = queue.pop(0)
            node = _flow_nodes.get(nid)
            if not node:
                continue
            for eid in node.out_edges:
                edge = _flow_edges.get(eid)
                if edge and edge.dst not in visited_l:
                    visited_l.add(edge.dst)
                    depth_map[edge.dst] = d + 1
                    queue.append((edge.dst, d + 1))
        max_d = max(depth_map.values()) if depth_map else 0
        for layer in range(0, max_d + 1):
            layer_nodes = [nid for nid, dep in depth_map.items() if dep == layer]
            if layer_nodes:
                layers_down.append(layer_nodes)

    # Build edge pairs with flow performance data for client-side coloring
    edge_pairs = []
    for eid in trace_edges:
        edge = _flow_edges.get(eid)
        if edge:
            edge_pairs.append({
                "src": edge.src,
                "dst": edge.dst,
                "flow_rate": round(edge.flow_rate, 2),
                "max_rate": round(edge.max_rate, 2),
                "is_pipe": edge.is_pipe,
            })

    # Node details for info panel
    node_info = {}
    for nid in all_nodes:
        node = _flow_nodes.get(nid)
        if node:
            node_info[nid] = {
                "name": node.building_name,
                "cat": node.category,
                "recipe": node.recipe_name,
                "clock": round(node.clock_speed * 100),
                "producing": node.is_producing,
                "avail_in": round(node.available_input, 1),
                "avail_out": round(node.available_output, 1),
                "expected_in": round(sum(node.expected_inputs.values()), 1),
                "expected_out": round(sum(node.expected_outputs.values()), 1),
            }

    return jsonify({
        "origin": building_id,
        "node_ids": list(all_nodes),
        "upstream_ids": list(upstream_nodes),
        "downstream_ids": list(downstream_nodes),
        "edges": edge_pairs,
        "layers_up": layers_up,
        "layers_down": layers_down,
        "node_info": node_info,
    })


@app.route("/api/supply_chain")
def api_supply_chain():
    """Return supply chain issues (starvation, clock mismatch, etc)."""
    if _current_issues is None:
        return jsonify([])
    chain_issues = [i for i in _current_issues
                    if i["category"] in ("Input Starvation", "Clock Too High",
                                         "Dead End", "No Input")]
    for i in chain_issues:
        if i.get("position"):
            i["position"] = list(i["position"])
    return jsonify(chain_issues)


@app.route("/api/feedback", methods=["POST"])
def api_add_feedback():
    """Add user feedback on a traceback diagnosis."""
    data = request.get_json()
    if not data:
        return jsonify({"error": "No JSON body"}), 400
    if not data.get("building_id") or not data.get("rating"):
        return jsonify({"error": "building_id and rating required"}), 400

    session_name = _current_factory.session_name if _current_factory else None

    feedback_id = add_feedback(
        building_id=data["building_id"],
        rating=data["rating"],
        comment=data.get("comment"),
        tags=data.get("tags"),
        session_name=session_name,
        building_name=data.get("building_name"),
        recipe=data.get("recipe"),
        issue_category=data.get("issue_category"),
        issue_title=data.get("issue_title"),
        issue_severity=data.get("issue_severity"),
        trace_snapshot=data.get("trace_snapshot"),
        issue_snapshot=data.get("issue_snapshot"),
        flow_context=data.get("flow_context"),
        actual_cause=data.get("actual_cause"),
        suggested_fix=data.get("suggested_fix"),
        diagnosis_root_cause=data.get("diagnosis_root_cause"),
        diagnosis_suggestion=data.get("diagnosis_suggestion"),
    )
    return jsonify({"id": feedback_id, "ok": True})


@app.route("/api/feedback", methods=["GET"])
def api_get_feedback():
    """Query feedback entries."""
    entries = get_feedback(
        building_id=request.args.get("building_id"),
        category=request.args.get("category"),
        rating=request.args.get("rating"),
        session_name=request.args.get("session"),
        limit=int(request.args.get("limit", 100)),
        offset=int(request.args.get("offset", 0)),
    )
    return jsonify(entries)


@app.route("/api/feedback/stats")
def api_feedback_stats():
    """Get aggregate feedback statistics."""
    session = request.args.get("session")
    if not session and _current_factory:
        session = _current_factory.session_name
    return jsonify(get_feedback_stats(session))


@app.route("/api/feedback/tags")
def api_feedback_tags():
    """Get all available feedback tags."""
    return jsonify(get_all_tags())


@app.route("/api/feedback/<int:feedback_id>")
def api_feedback_detail(feedback_id):
    """Get a single feedback entry."""
    entry = get_feedback_by_id(feedback_id)
    if not entry:
        return jsonify({"error": "Not found"}), 404
    return jsonify(entry)


@app.route("/api/feedback/linked/<path:building_id>")
def api_feedback_linked(building_id):
    """Get all feedback involving a building (direct + in traces)."""
    return jsonify(get_linked_feedback(building_id))


@app.route("/api/districts")
def api_districts():
    """Return Leiden community districts."""
    if _districts is None:
        return jsonify([])
    return jsonify([{
        "id": d.id,
        "name": d.name,
        "total_machines": d.total_machines,
        "producing_count": d.producing_count,
        "efficiency": round(d.efficiency, 1),
        "center_x": round(d.center_x, 1),
        "center_y": round(d.center_y, 1),
        "dominant_recipe": d.dominant_recipe,
        "dominant_building": d.dominant_building,
        "categories": d.categories,
        "issue_count": d.issue_count,
        "node_ids": d.node_ids,
    } for d in _districts])


@app.route("/api/manifolds")
def api_manifolds():
    """Return structurally equivalent machine blocks."""
    if _manifold_blocks is None:
        return jsonify([])
    return jsonify([{
        "id": b.id,
        "recipe_name": b.recipe_name,
        "building_name": b.building_name,
        "count": b.count,
        "avg_clock": round(b.avg_clock * 100, 1),
        "producing_count": b.producing_count,
        "oee": round(b.oee, 1),
        "total_expected_output": round(b.total_expected_output, 1),
        "total_actual_output": round(b.total_actual_output, 1),
        "node_ids": b.node_ids,
    } for b in _manifold_blocks])


@app.route("/api/tickets")
def api_tickets():
    """Query tickets with optional status filter."""
    status = request.args.get("status")
    limit = int(request.args.get("limit", 100))
    offset = int(request.args.get("offset", 0))
    return jsonify(get_tickets(status=status, limit=limit, offset=offset))


@app.route("/api/tickets/<int:ticket_id>", methods=["PATCH"])
def api_update_ticket(ticket_id):
    """Update ticket status or assignment."""
    data = request.get_json()
    if not data:
        return jsonify({"error": "No JSON body"}), 400
    result = update_ticket(
        ticket_id,
        status=data.get("status"),
        assigned_to=data.get("assigned_to"),
        resolution_note=data.get("resolution_note"),
    )
    if result:
        return jsonify(dict(result))
    return jsonify({"error": "Ticket not found"}), 404


@app.route("/api/tickets/stats")
def api_ticket_stats():
    """Get ticket statistics."""
    return jsonify(get_ticket_stats())


# ═══ Balance Sheet / Ledger ═══════════════════════════════════════════════

@app.route("/api/ledger/district/<int:district_id>")
def api_district_ledger(district_id):
    """Return the item balance sheet for an auto-detected district."""
    if _districts is None or _flow_nodes is None:
        return jsonify({"error": "No data loaded"}), 400
    district = None
    for d in _districts:
        if d.id == district_id:
            district = d
            break
    if not district:
        return jsonify({"error": "District not found"}), 404
    ledger = compute_ledger(district.node_ids, _flow_nodes, _flow_edges)
    ledger["district_name"] = district.name
    ledger["district_id"] = district.id
    return jsonify(ledger)


@app.route("/api/ledger/selection", methods=["POST"])
def api_selection_ledger():
    """Return the item balance sheet for an arbitrary set of building IDs."""
    if _flow_nodes is None:
        return jsonify({"error": "No data loaded"}), 400
    data = request.get_json()
    if not data or not data.get("node_ids"):
        return jsonify({"error": "node_ids required"}), 400
    node_ids = data["node_ids"]
    # Validate that at least some nodes exist
    valid = [nid for nid in node_ids if nid in _flow_nodes]
    if not valid:
        return jsonify({"error": "No valid nodes in selection"}), 404
    ledger = compute_ledger(valid, _flow_nodes, _flow_edges)
    ledger["selection_count"] = len(valid)
    return jsonify(ledger)


# ═══ Manual Lasso (Custom Groups) ═════════════════════════════════════════

@app.route("/api/lassos", methods=["GET"])
def api_get_lassos():
    """List all custom user-defined lassos."""
    return jsonify(_custom_lassos)


@app.route("/api/lassos", methods=["POST"])
def api_create_lasso():
    """Create a custom lasso from a polygon selection.

    Body: {name: str, polygon: [[x,y], ...], node_ids: [str, ...]}
    The client computes which buildings fall inside the polygon.
    """
    global _next_lasso_id
    if _flow_nodes is None:
        return jsonify({"error": "No data loaded"}), 400
    data = request.get_json()
    if not data:
        return jsonify({"error": "No JSON body"}), 400

    name = data.get("name", f"Custom Lasso {_next_lasso_id}")
    node_ids = data.get("node_ids", [])
    polygon = data.get("polygon", [])

    if not node_ids:
        return jsonify({"error": "node_ids required (buildings inside polygon)"}), 400

    lasso = {
        "id": _next_lasso_id,
        "name": name,
        "node_ids": node_ids,
        "polygon": polygon,
    }
    _custom_lassos.append(lasso)
    _next_lasso_id += 1
    return jsonify(lasso)


@app.route("/api/lassos/<int:lasso_id>", methods=["DELETE"])
def api_delete_lasso(lasso_id):
    """Delete a custom lasso."""
    global _custom_lassos
    _custom_lassos = [l for l in _custom_lassos if l["id"] != lasso_id]
    return jsonify({"ok": True})


@app.route("/api/lassos/<int:lasso_id>/ledger")
def api_lasso_ledger(lasso_id):
    """Return the item balance sheet for a custom lasso."""
    if _flow_nodes is None:
        return jsonify({"error": "No data loaded"}), 400
    lasso = None
    for l in _custom_lassos:
        if l["id"] == lasso_id:
            lasso = l
            break
    if not lasso:
        return jsonify({"error": "Lasso not found"}), 404
    ledger = compute_ledger(lasso["node_ids"], _flow_nodes, _flow_edges)
    ledger["lasso_name"] = lasso["name"]
    ledger["lasso_id"] = lasso["id"]
    return jsonify(ledger)


# ═══ Sub-Graph Export ═════════════════════════════════════════════════════

@app.route("/api/export/subgraph", methods=["POST"])
def api_export_subgraph():
    """Export a sub-graph as JSON for false-positive reporting.

    Body: {node_ids: [str, ...], ticket_id: int (optional), reason: str (optional)}
    Returns a self-contained JSON snapshot of the nodes, edges, and flow data.
    """
    if _flow_nodes is None or _flow_edges is None:
        return jsonify({"error": "No data loaded"}), 400
    data = request.get_json()
    if not data or not data.get("node_ids"):
        return jsonify({"error": "node_ids required"}), 400

    nid_set = set(data["node_ids"])
    export_nodes = {}
    for nid in nid_set:
        node = _flow_nodes.get(nid)
        if not node:
            continue
        export_nodes[nid] = {
            "building_name": node.building_name,
            "category": node.category,
            "recipe_name": node.recipe_name,
            "clock_speed": node.clock_speed,
            "is_producing": node.is_producing,
            "productivity": node.productivity,
            "expected_inputs": dict(node.expected_inputs),
            "expected_outputs": dict(node.expected_outputs),
            "available_input": round(node.available_input, 2),
            "available_output": round(node.available_output, 2),
            "position": list(node.position),
        }

    export_edges = []
    for eid, edge in _flow_edges.items():
        if edge.src in nid_set or edge.dst in nid_set:
            export_edges.append({
                "belt_id": eid,
                "src": edge.src,
                "dst": edge.dst,
                "max_rate": edge.max_rate,
                "flow_rate": round(edge.flow_rate, 2),
                "is_pipe": edge.is_pipe,
                "src_inside": edge.src in nid_set,
                "dst_inside": edge.dst in nid_set,
            })

    # Include related issues
    export_issues = []
    if _current_issues:
        for issue in _current_issues:
            if issue.get("building_id") in nid_set:
                export_issues.append({
                    "category": issue.get("category"),
                    "severity": issue.get("severity"),
                    "title": issue.get("title"),
                    "building_id": issue.get("building_id"),
                    "root_cause": issue.get("root_cause"),
                    "suggestion": issue.get("suggestion"),
                })

    return jsonify({
        "nodes": export_nodes,
        "edges": export_edges,
        "issues": export_issues,
        "meta": {
            "session_name": _current_factory.session_name if _current_factory else None,
            "ticket_id": data.get("ticket_id"),
            "reason": data.get("reason"),
            "node_count": len(export_nodes),
            "edge_count": len(export_edges),
            "issue_count": len(export_issues),
        },
    })


@app.route("/reset")
def reset():
    global _current_factory, _current_issues, _graph_stats, _flow_nodes, _flow_edges
    global _districts, _node_to_district, _manifold_blocks, _node_to_block
    global _custom_lassos, _next_lasso_id
    _current_factory = None
    _current_issues = None
    _graph_stats = None
    _flow_nodes = None
    _flow_edges = None
    _districts = None
    _node_to_district = None
    _manifold_blocks = None
    _node_to_block = None
    _custom_lassos = []
    _next_lasso_id = 1
    return redirect(url_for("upload"))


if __name__ == "__main__":
    # Auto-load save file if it exists nearby
    default_sav = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
        "BASFSimulator_autosave_2.sav"
    )
    if os.path.exists(default_sav) and _current_factory is None:
        print(f"Auto-loading: {default_sav}")
        _current_factory = parse_save(default_sav)
        _current_issues, _graph_stats = analyze_supply_chain(_current_factory)
        # Build flow graph for traceback queries
        recipe_db, by_norm = load_recipe_db()
        _flow_nodes, _flow_edges, _ = build_flow_graph(_current_factory, recipe_db, by_norm)
        propagate_flow(_flow_nodes, _flow_edges)
        # District detection + manifold compression
        _districts, _node_to_district = detect_districts(
            _flow_nodes, _flow_edges, _current_factory, _current_issues)
        _manifold_blocks, _node_to_block = compute_manifold_blocks(
            _flow_nodes, _flow_edges)
        # Ticket workflow
        session_name = _current_factory.session_name if hasattr(_current_factory, 'session_name') else None
        auto_resolve_tickets(_current_issues, session_name)
        ticket_result = create_tickets_from_issues(_current_issues, session_name)
        print(f"Loaded: {len(_current_issues)} issues found")
        if _graph_stats:
            print(f"Graph: {_graph_stats['total_nodes']} nodes, {_graph_stats['total_edges']} edges, "
                  f"{_graph_stats['recipes_matched']} recipes matched")
        print(f"Districts: {len(_districts)}, Manifold blocks: {len(_manifold_blocks)}")
        print(f"Tickets: {ticket_result['created']} created, {ticket_result['updated']} updated")

    app.run(debug=True, port=5000)
