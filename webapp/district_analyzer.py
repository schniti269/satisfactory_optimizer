"""
district_analyzer.py - Leiden community detection and structural equivalence.

Contains:
- Leiden-based topological district detection
- Structural equivalence hashing for manifold compression
"""

import hashlib
from collections import Counter, defaultdict
from dataclasses import dataclass, field


# ═══════════════════════════════════════════════════════════════════════════════
# District Detection (Leiden Community Detection)
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass
class District:
    """A topological district (community) of machines."""

    id: int
    name: str
    node_ids: list = field(default_factory=list)
    dominant_recipe: str = None
    dominant_building: str = None
    total_machines: int = 0
    producing_count: int = 0
    efficiency: float = 0.0
    center_x: float = 0.0
    center_y: float = 0.0
    categories: dict = field(default_factory=dict)
    issue_count: int = 0


def detect_districts(nodes, edges, factory, issues=None, resolution=1.0):
    """
    Run Leiden community detection on the factory graph.

    Uses flow connectivity (not spatial proximity) to group machines
    into logical production districts.

    Args:
        nodes: {building_id: FlowNode}
        edges: {belt_id: FlowEdge}
        factory: FactoryData
        issues: list of issue dicts (optional, for issue_count per district)
        resolution: Leiden resolution parameter (higher = more communities)

    Returns:
        districts: list of District
        node_to_district: {building_id: district_id}
    """
    try:
        import igraph as ig
        import leidenalg
        return _leiden_communities(nodes, edges, factory, issues, resolution)
    except ImportError:
        return _fallback_communities(nodes, edges, factory, issues)


def _leiden_communities(nodes, edges, factory, issues, resolution):
    """Leiden algorithm on undirected graph weighted by flow rate."""
    import igraph as ig
    import leidenalg

    node_list = list(nodes.keys())
    node_idx = {nid: i for i, nid in enumerate(node_list)}

    # Build undirected edge list (deduplicated)
    edge_list = []
    edge_weights = []
    seen_edges = set()

    for eid, edge in edges.items():
        si = node_idx.get(edge.src)
        sj = node_idx.get(edge.dst)
        if si is None or sj is None:
            continue
        pair = (min(si, sj), max(si, sj))
        if pair not in seen_edges:
            seen_edges.add(pair)
            edge_list.append(pair)
            edge_weights.append(max(edge.flow_rate, 1.0))

    g = ig.Graph(n=len(node_list), edges=edge_list, directed=False)
    g.es["weight"] = edge_weights

    # Run Leiden
    partition = leidenalg.find_partition(
        g,
        leidenalg.RBConfigurationVertexPartition,
        weights="weight",
        resolution_parameter=resolution,
    )

    # Build districts
    node_to_district = {}
    district_nodes = defaultdict(list)

    for i, community_id in enumerate(partition.membership):
        nid = node_list[i]
        node_to_district[nid] = community_id
        district_nodes[community_id].append(nid)

    # Build issue lookup
    issue_by_building = defaultdict(int)
    if issues:
        for issue in issues:
            bid = issue.get("building_id")
            if bid:
                issue_by_building[bid] += 1

    districts = []
    for did, nids in district_nodes.items():
        d = _build_district(did, nids, nodes, factory, issue_by_building)
        districts.append(d)

    districts.sort(key=lambda d: d.total_machines, reverse=True)
    return districts, node_to_district


def _fallback_communities(nodes, edges, factory, issues):
    """Fallback using NetworkX greedy modularity if leidenalg unavailable."""
    import networkx as nx

    G = nx.Graph()
    for nid in nodes:
        G.add_node(nid)
    for eid, edge in edges.items():
        if edge.src in nodes and edge.dst in nodes:
            G.add_edge(edge.src, edge.dst, weight=max(edge.flow_rate, 1.0))

    communities = nx.community.greedy_modularity_communities(G, weight="weight")

    issue_by_building = defaultdict(int)
    if issues:
        for issue in issues:
            bid = issue.get("building_id")
            if bid:
                issue_by_building[bid] += 1

    node_to_district = {}
    districts = []
    for did, comm in enumerate(communities):
        nids = list(comm)
        for nid in nids:
            node_to_district[nid] = did
        d = _build_district(did, nids, nodes, factory, issue_by_building)
        districts.append(d)

    districts.sort(key=lambda d: d.total_machines, reverse=True)
    return districts, node_to_district


def _build_district(did, nids, nodes, factory, issue_by_building):
    """Assemble a District object from node IDs."""
    d = District(id=did, name="", node_ids=nids)
    d.total_machines = len(nids)

    recipe_counts = Counter()
    building_counts = Counter()
    total_prod = 0.0
    prod_count = 0
    sum_x = sum_y = 0.0

    for nid in nids:
        node = nodes.get(nid)
        if not node:
            continue

        bld = factory.buildings.get(nid)
        if bld:
            sum_x += bld.position[0]
            sum_y += bld.position[1]

        d.categories[node.category] = d.categories.get(node.category, 0) + 1
        building_counts[node.building_name] += 1

        if node.recipe_name:
            recipe_counts[node.recipe_name] += 1

        if node.is_producing:
            d.producing_count += 1

        if node.productivity > 0:
            total_prod += node.productivity
            prod_count += 1

        d.issue_count += issue_by_building.get(nid, 0)

    d.efficiency = (total_prod / prod_count * 100) if prod_count > 0 else 0.0
    d.center_x = sum_x / len(nids) if nids else 0
    d.center_y = sum_y / len(nids) if nids else 0

    if recipe_counts:
        d.dominant_recipe = recipe_counts.most_common(1)[0][0]
        d.name = f"{d.dominant_recipe} District"
    elif building_counts:
        d.dominant_building = building_counts.most_common(1)[0][0]
        d.name = f"{d.dominant_building} Area"
    else:
        d.name = f"District {did}"

    return d


# ═══════════════════════════════════════════════════════════════════════════════
# Structural Equivalence (Manifold Compression)
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass
class ManifoldBlock:
    """A group of structurally equivalent machines."""

    id: str
    recipe_name: str
    building_name: str
    node_ids: list = field(default_factory=list)
    count: int = 0
    avg_clock: float = 1.0
    producing_count: int = 0
    oee: float = 0.0
    total_expected_output: float = 0.0
    total_actual_output: float = 0.0
    input_sources: list = field(default_factory=list)
    output_targets: list = field(default_factory=list)


def compute_manifold_blocks(nodes, edges):
    """
    Group structurally equivalent machines.

    Two machines are equivalent IFF:
      1. Same recipe (recipe_name)
      2. Same set of input precursor node IDs
      3. Same set of output successor node IDs

    Hash = sha256(recipe + sorted(input_ids) + sorted(output_ids))[:16]

    Returns:
        blocks: list of ManifoldBlock
        node_to_block: {node_id: block_id}
    """
    # Build predecessor/successor maps
    predecessors = defaultdict(set)
    successors = defaultdict(set)

    for eid, edge in edges.items():
        if edge.src in nodes and edge.dst in nodes:
            predecessors[edge.dst].add(edge.src)
            successors[edge.src].add(edge.dst)

    # Compute structural hashes for production buildings with recipes
    hash_groups = defaultdict(list)

    for nid, node in nodes.items():
        if node.category != "production" or not node.recipe_name:
            continue

        preds = tuple(sorted(predecessors.get(nid, set())))
        succs = tuple(sorted(successors.get(nid, set())))

        key_str = f"{node.recipe_name}|{preds}|{succs}"
        h = hashlib.sha256(key_str.encode()).hexdigest()[:16]
        hash_groups[h].append(nid)

    # Build ManifoldBlocks (only groups of 2+)
    blocks = []
    node_to_block = {}

    for h, nids in hash_groups.items():
        if len(nids) < 2:
            continue

        first_node = nodes[nids[0]]
        block = ManifoldBlock(
            id=h,
            recipe_name=first_node.recipe_name,
            building_name=first_node.building_name,
            node_ids=nids,
            count=len(nids),
        )

        total_clock = 0.0
        total_expected = 0.0
        total_actual = 0.0

        for nid in nids:
            node = nodes[nid]
            node_to_block[nid] = h
            total_clock += node.clock_speed
            if node.is_producing:
                block.producing_count += 1
            total_expected += sum(node.expected_outputs.values())
            total_actual += node.available_output

        block.avg_clock = total_clock / len(nids)
        block.total_expected_output = total_expected
        block.total_actual_output = total_actual
        block.oee = (
            (total_actual / total_expected * 100) if total_expected > 0 else 0.0
        )

        block.input_sources = list(predecessors.get(nids[0], set()))
        block.output_targets = list(successors.get(nids[0], set()))

        blocks.append(block)

    blocks.sort(key=lambda b: b.count, reverse=True)
    return blocks, node_to_block


# ═══════════════════════════════════════════════════════════════════════════════
# Balance Sheet / Ledger
# ═══════════════════════════════════════════════════════════════════════════════


def compute_ledger(district_node_ids, nodes, edges):
    """Compute the item balance sheet for a set of nodes (a district or lasso).

    For each item, sums up:
      - produced: total expected output rate from production buildings
      - consumed: total expected input rate from production buildings
      - net: produced - consumed (positive = surplus, negative = deficit)
      - external_in: flow entering the district from outside via edges
      - external_out: flow leaving the district to outside via edges

    Also computes cross-boundary edge flows and identifies the top bottleneck.

    Args:
        district_node_ids: list/set of building IDs in the group
        nodes: {building_id: FlowNode}
        edges: {belt_id: FlowEdge}

    Returns:
        dict with keys: items (list), totals, boundary_edges
    """
    nid_set = set(district_node_ids)

    # Per-item aggregation
    item_produced = defaultdict(float)   # item_name -> rate/min produced
    item_consumed = defaultdict(float)   # item_name -> rate/min consumed
    item_ext_in = defaultdict(float)     # item_name -> rate entering from outside
    item_ext_out = defaultdict(float)    # item_name -> rate leaving to outside

    total_machines = 0
    total_producing = 0

    for nid in nid_set:
        node = nodes.get(nid)
        if not node:
            continue

        if node.category in ("production", "generator") and node.recipe_data:
            total_machines += 1
            if node.is_producing:
                total_producing += 1

            for item, rate in node.expected_outputs.items():
                item_produced[item] += rate
            for item, rate in node.expected_inputs.items():
                item_consumed[item] += rate

        elif node.category == "miner":
            total_machines += 1
            if node.is_producing or node.available_output > 0:
                total_producing += 1
            for item, rate in node.expected_outputs.items():
                item_produced[item] += rate

    # Boundary edge analysis: edges crossing the district boundary
    boundary_in = []   # edges entering from outside
    boundary_out = []  # edges leaving to outside

    for eid, edge in edges.items():
        src_inside = edge.src in nid_set
        dst_inside = edge.dst in nid_set
        if src_inside and not dst_inside:
            boundary_out.append(edge)
        elif not src_inside and dst_inside:
            boundary_in.append(edge)

    # For boundary edges we don't know item type directly from FlowEdge,
    # but we can infer from the source node's recipe outputs or dst node's recipe inputs
    for edge in boundary_in:
        src_node = nodes.get(edge.src)
        if src_node and src_node.expected_outputs:
            # Assume the edge carries the source's output item(s)
            for item in src_node.expected_outputs:
                item_ext_in[item] += edge.flow_rate / max(len(src_node.expected_outputs), 1)
        elif edge.flow_rate > 0:
            item_ext_in["(unknown)"] += edge.flow_rate

    for edge in boundary_out:
        dst_node = nodes.get(edge.dst)
        if dst_node and dst_node.expected_inputs:
            for item in dst_node.expected_inputs:
                item_ext_out[item] += edge.flow_rate / max(len(dst_node.expected_inputs), 1)
        elif edge.flow_rate > 0:
            item_ext_out["(unknown)"] += edge.flow_rate

    # Build sorted item list
    all_items = set(item_produced.keys()) | set(item_consumed.keys())
    items = []
    for item in sorted(all_items):
        produced = round(item_produced.get(item, 0), 1)
        consumed = round(item_consumed.get(item, 0), 1)
        net = round(produced - consumed, 1)
        ext_in = round(item_ext_in.get(item, 0), 1)
        ext_out = round(item_ext_out.get(item, 0), 1)

        if produced == 0 and consumed == 0:
            status = "unused"
        elif consumed == 0:
            status = "surplus"
        elif produced == 0:
            status = "imported"
        elif net > 0.5:
            status = "surplus"
        elif net < -0.5:
            status = "deficit"
        else:
            status = "balanced"

        items.append({
            "item": item,
            "produced": produced,
            "consumed": consumed,
            "net": net,
            "ext_in": ext_in,
            "ext_out": ext_out,
            "status": status,
        })

    # Sort: deficits first, then surplus, then balanced
    status_order = {"deficit": 0, "imported": 1, "surplus": 2, "balanced": 3, "unused": 4}
    items.sort(key=lambda x: (status_order.get(x["status"], 5), -abs(x["net"])))

    # Find the tightest bottleneck edge on boundary
    bottleneck = None
    for edge in boundary_in + boundary_out:
        util = edge.flow_rate / edge.max_rate if edge.max_rate > 0 else 0
        if bottleneck is None or util > bottleneck["util"]:
            bottleneck = {
                "src": edge.src,
                "dst": edge.dst,
                "flow_rate": round(edge.flow_rate, 1),
                "max_rate": round(edge.max_rate, 1),
                "util": round(util, 3),
                "is_pipe": edge.is_pipe,
            }

    return {
        "items": items,
        "totals": {
            "machines": total_machines,
            "producing": total_producing,
            "items_produced": len(item_produced),
            "items_consumed": len(item_consumed),
            "boundary_in_count": len(boundary_in),
            "boundary_out_count": len(boundary_out),
            "total_ext_in_rate": round(sum(e.flow_rate for e in boundary_in), 1),
            "total_ext_out_rate": round(sum(e.flow_rate for e in boundary_out), 1),
        },
        "bottleneck": bottleneck,
    }
