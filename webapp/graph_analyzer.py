"""
Satisfactory Factory — Supply Chain Graph Analyzer

Builds a directed production graph from parsed save data, loads recipe rates from
data_raw.json, propagates flow rates through the graph, and detects real supply chain
issues: belt bottlenecks, input starvation, clock mismatches, dead-end production, etc.
"""

import json
import os
import re
from collections import defaultdict
from dataclasses import dataclass, field


# ── Recipe Rate Database ─────────────────────────────────────────────────────

# Manual overrides for save-file recipe slugs that can't be auto-matched
# Format: save_slug (without Recipe_ prefix) -> data_raw.json recipe name
RECIPE_SLUG_OVERRIDES = {
    "Alternate_CircuitBoard_2": "Alternate: Electrode Circuit Board",
    "Alternate_IngotSteel_1": "Alternate: Compacted Steel Ingot",
    "Alternate_Wire_1": "Alternate: Iron Wire",
    "Alternate_Computer_2": "Alternate: Crystal Computer",
    "Alternate_CrystalOscillator": "Alternate: Insulated Crystal Oscillator",
    "Alternate_EnrichedCoal": "Alternate: Compacted Coal",
    "Alternate_ElectroAluminumScrap": "Alternate: Electrode Aluminum Scrap",
    "Alternate_Turbofuel": "Turbofuel",
    "Alternate_IronIngot_Leached": "Alternate: Leached Iron ingot",
    "Alternate_Quartz_Purified": "Alternate: Pure Quartz Crystal",
    "Alternate_Silica_Distilled": "Alternate: Distilled Silica",
    "AluminumSheet": "Alclad Aluminum Sheet",
    "Biofuel": "Solid Biofuel",
    "FluidCanister": "Empty Canister",
    "IronPlateReinforced": "Reinforced Iron Plate",
    "IngotSAM": "Reanimated SAM",
    "SpaceElevatorPart_4": "Assembly Director System",
    "PowerCrystalShard_1": "Power Shard (1)",
    "PowerCrystalShard_2": "Power Shard (2)",
    "PowerCrystalShard_3": "Power Shard (5)",
    "PackagedBiofuel": "Packaged Liquid Biofuel",
    "PackagedNitrogen": "Packaged Nitrogen Gas",
    "UnpackageBioFuel": "Unpackage Liquid Biofuel",
    "UnpackageNitrogen": "Unpackage Nitrogen Gas",
    "Alternate_PureCateriumIngot": "Alternate: Pure Caterium Ingot",
    "Alternate_PureCopperIngot": "Alternate: Pure Copper Ingot",
    "Alternate_HeavyOilResidue": "Alternate: Heavy Oil Residue",
    "Alternate_TurboHeavyFuel": "Alternate: Turbo Heavy Fuel",
    "Alternate_SloppyAlumina": "Alternate: Sloppy Alumina",
}

# Miner output rates at 100% clock (items/min per miner based on tier)
# These are for Normal purity nodes. Impure = half, Pure = double.
MINER_BASE_RATES = {
    "Miner Mk.1": 60,
    "Miner Mk.2": 120,
    "Miner Mk.3": 240,
    "Oil Extractor": 120,
    "Water Extractor": 120,
    "Resource Well Extractor": 60,
    "Resource Well Pressurizer": 0,  # enables extractors, no direct output
}


@dataclass
class RecipeRate:
    """Recipe input/output rates at 100% clock speed."""

    name: str
    building: str
    inputs: list  # [(item_name, rate_per_min), ...]
    outputs: list  # [(item_name, rate_per_min), ...]
    duration: float  # seconds per cycle


def load_recipe_db(data_raw_path=None):
    """Load recipe rate database from data_raw.json."""
    if data_raw_path is None:
        data_raw_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data_raw.json"
        )

    with open(data_raw_path) as f:
        data = json.load(f)

    db = {}  # recipe_name -> RecipeRate
    by_norm = {}  # normalized_name -> recipe_name (for fuzzy matching)

    excluded = {"Crafting Bench", "Equipment Workshop"}
    for r in data["recipes"]:
        machines = [m for m in r["machine"] if m not in excluded]
        if not machines:
            continue

        duration = r["duration"]
        cycles_per_min = 60.0 / duration

        rate = RecipeRate(
            name=r["name"],
            building=machines[0],
            inputs=[(item, qty * cycles_per_min) for item, qty in r["input"]],
            outputs=[(item, qty * cycles_per_min) for item, qty in r["output"]],
            duration=duration,
        )
        db[r["name"]] = rate
        norm = re.sub(r"[^a-z0-9]", "", r["name"].lower())
        by_norm[norm] = r["name"]

    return db, by_norm


def match_recipe_slug(slug, by_norm):
    """Match a save-file recipe slug to a data_raw recipe name.

    Args:
        slug: e.g. "Recipe_IngotIron" or "Recipe_Alternate_Wire_1"
        by_norm: dict of normalized_name -> recipe_name

    Returns:
        recipe name string or None
    """
    clean = slug.replace("Recipe_", "")

    # Check manual overrides first
    if clean in RECIPE_SLUG_OVERRIDES:
        return RECIPE_SLUG_OVERRIDES[clean]

    # Strategy 1: Direct normalize
    norm = re.sub(r"[^a-z0-9]", "", clean.lower())
    if norm in by_norm:
        return by_norm[norm]

    # Strategy 2: Handle Alternate_ prefix
    clean2 = clean.replace("Alternate_", "Alternate: ")
    norm2 = re.sub(r"[^a-z0-9]", "", clean2.lower())
    if norm2 in by_norm:
        return by_norm[norm2]

    # Strategy 3: Insert spaces in CamelCase
    spaced = re.sub(r"([a-z])([A-Z])", r"\1 \2", clean).replace("_", " ")
    norm3 = re.sub(r"[^a-z0-9]", "", spaced.lower())
    if norm3 in by_norm:
        return by_norm[norm3]

    # Strategy 4: Reverse CamelCase words (IngotIron -> IronIngot)
    base = clean.replace("Alternate_", "")
    parts = re.findall(r"[A-Z][a-z]*|[0-9]+", base)
    if len(parts) >= 2:
        reversed_name = "".join(reversed(parts))
        norm4 = re.sub(r"[^a-z0-9]", "", reversed_name.lower())
        if norm4 in by_norm:
            return by_norm[norm4]
        if clean.startswith("Alternate_"):
            norm4b = re.sub(r"[^a-z0-9]", "", ("alternate" + reversed_name).lower())
            if norm4b in by_norm:
                return by_norm[norm4b]

    return None


# ── Flow Graph ───────────────────────────────────────────────────────────────


@dataclass
class FlowEdge:
    """Directed edge in the production graph (a belt or pipe)."""

    belt_id: str
    src: str  # source building ID
    dst: str  # destination building ID
    max_rate: float  # belt/pipe capacity (items or m³ per min)
    is_pipe: bool
    flow_rate: float = 0.0  # calculated flow rate through this edge


@dataclass
class FlowNode:
    """Node in the production graph (a building)."""

    building_id: str
    building_name: str
    category: str
    recipe_name: str = None
    recipe_data: RecipeRate = None  # matched recipe rate info
    clock_speed: float = 1.0
    is_producing: bool = False
    productivity: float = 0.0
    position: tuple = (0, 0, 0)

    # Expected rates at this building's clock speed
    expected_inputs: dict = field(default_factory=dict)  # {item: rate/min}
    expected_outputs: dict = field(default_factory=dict)  # {item: rate/min}

    # Actual available/demanded rates (computed by flow propagation)
    available_input: float = 0.0  # total input rate actually available
    available_output: float = 0.0  # total output rate actually consumed

    in_edges: list = field(default_factory=list)  # FlowEdge IDs feeding in
    out_edges: list = field(default_factory=list)  # FlowEdge IDs going out


def build_flow_graph(factory, recipe_db, by_norm):
    """Build a directed flow graph from factory data.

    Returns:
        nodes: {building_id: FlowNode}
        edges: {belt_id: FlowEdge}
        unmatched_recipes: set of recipe slugs we couldn't match
    """
    nodes = {}
    edges = {}
    unmatched_recipes = set()

    # Create flow nodes for all buildings
    for bld_id, bld in factory.buildings.items():
        recipe_slug = None
        recipe_data = None

        if bld.recipe:
            recipe_slug = bld.recipe.split("/")[-1].split(".")[0]
            recipe_name = match_recipe_slug(recipe_slug, by_norm)
            if recipe_name and recipe_name in recipe_db:
                recipe_data = recipe_db[recipe_name]
            elif recipe_slug:
                unmatched_recipes.add(recipe_slug)

        node = FlowNode(
            building_id=bld_id,
            building_name=bld.friendly_name,
            category=bld.category,
            recipe_name=recipe_data.name if recipe_data else bld.recipe_name,
            recipe_data=recipe_data,
            clock_speed=bld.clock_speed,
            is_producing=bld.is_producing,
            productivity=bld.productivity,
            position=bld.position,
        )

        # Calculate expected rates at this clock speed
        if recipe_data:
            for item, rate in recipe_data.inputs:
                node.expected_inputs[item] = rate * bld.clock_speed
            for item, rate in recipe_data.outputs:
                node.expected_outputs[item] = rate * bld.clock_speed
        elif bld.category == "miner":
            # Miners: output based on tier and clock
            base_rate = MINER_BASE_RATES.get(bld.friendly_name, 0)
            if base_rate > 0:
                node.expected_outputs["(mined item)"] = base_rate * bld.clock_speed

        nodes[bld_id] = node

    # Create flow edges from directed belts
    for belt_id, belt in factory.belts.items():
        if belt.src_building and belt.dst_building:
            edge = FlowEdge(
                belt_id=belt_id,
                src=belt.src_building,
                dst=belt.dst_building,
                max_rate=belt.max_rate,
                is_pipe=belt.is_pipe,
            )
            edges[belt_id] = edge

            if belt.src_building in nodes:
                nodes[belt.src_building].out_edges.append(belt_id)
            if belt.dst_building in nodes:
                nodes[belt.dst_building].in_edges.append(belt_id)

    return nodes, edges, unmatched_recipes


# ── Flow Propagation ─────────────────────────────────────────────────────────


def propagate_flow(nodes, edges):
    """Propagate flow rates using SCC decomposition + fixed-point iteration.

    Phase 1: Tarjan's SCC to find cycles
    Phase 2: Topological order on condensation DAG
    Phase 3: For each SCC in topo order:
        - Singleton (no cycle): single forward calculation
        - Multi-node (cycle): iterate until convergence with damping
    """
    from graph_algorithms import tarjan_scc, condensation_topo_order

    # Build adjacency for SCC detection
    adj = defaultdict(list)
    for eid, edge in edges.items():
        if edge.src in nodes and edge.dst in nodes:
            adj[edge.src].append(edge.dst)

    # Initialize miner outputs before SCC processing
    for nid, node in nodes.items():
        if node.category == "miner":
            base_rate = MINER_BASE_RATES.get(node.building_name, 0)
            node.available_output = base_rate * node.clock_speed
            if node.out_edges:
                per_belt = node.available_output / len(node.out_edges)
                for eid in node.out_edges:
                    edges[eid].flow_rate = min(per_belt, edges[eid].max_rate)

    # Phase 1: Find SCCs
    sccs = tarjan_scc(dict(adj))

    # Phase 2: Topological order on condensation DAG
    topo_order, scc_index = condensation_topo_order(sccs, dict(adj))

    # Phase 3: Process SCCs in topological order
    for scc_idx in topo_order:
        scc = sccs[scc_idx]

        if len(scc) == 1:
            nid = next(iter(scc))
            _calculate_node_flow(nid, nodes, edges)
        else:
            _fixed_point_scc(scc, nodes, edges, max_iter=100, epsilon=0.01)


def _calculate_node_flow(nid, nodes, edges):
    """Calculate flow for a single node based on its incoming edges."""
    node = nodes[nid]

    # Calculate total incoming flow
    total_in = sum(edges[eid].flow_rate for eid in node.in_edges)
    node.available_input = total_in

    if node.category == "miner":
        # Already initialized
        pass
    elif node.category == "logistics":
        node.available_output = total_in
        if node.out_edges:
            if (
                "Splitter" in node.building_name
                or "Smart Splitter" in node.building_name
                or "Programmable Splitter" in node.building_name
            ):
                per_branch = total_in / len(node.out_edges)
                for eid in node.out_edges:
                    edges[eid].flow_rate = min(per_branch, edges[eid].max_rate)
            elif "Merger" in node.building_name:
                for eid in node.out_edges:
                    edges[eid].flow_rate = min(total_in, edges[eid].max_rate)
            elif "Pipe Junction" in node.building_name:
                per_branch = total_in / max(len(node.out_edges), 1)
                for eid in node.out_edges:
                    edges[eid].flow_rate = min(per_branch, edges[eid].max_rate)
            elif "Pipeline Pump" in node.building_name:
                for eid in node.out_edges:
                    edges[eid].flow_rate = min(total_in, edges[eid].max_rate)
            else:
                for eid in node.out_edges:
                    edges[eid].flow_rate = min(
                        total_in / max(len(node.out_edges), 1), edges[eid].max_rate
                    )
    elif node.category in ("production", "generator") and node.recipe_data:
        total_expected_input = sum(node.expected_inputs.values())
        if total_expected_input > 0:
            input_sufficiency = min(total_in / total_expected_input, 1.0)
        else:
            input_sufficiency = 1.0

        total_expected_output = sum(node.expected_outputs.values())
        actual_output = total_expected_output * input_sufficiency
        node.available_output = actual_output

        if node.out_edges:
            per_belt = actual_output / len(node.out_edges)
            for eid in node.out_edges:
                edges[eid].flow_rate = min(per_belt, edges[eid].max_rate)
    elif node.category in ("storage", "transport"):
        # Storage and transport nodes pass through flow
        node.available_output = total_in
        if node.out_edges:
            per_belt = total_in / max(len(node.out_edges), 1)
            for eid in node.out_edges:
                edges[eid].flow_rate = min(per_belt, edges[eid].max_rate)


def _fixed_point_scc(scc, nodes, edges, max_iter=100, epsilon=0.01):
    """Fixed-point iteration for cyclic subgraph with damping.

    Production buildings are monotone contractive (output <= recipe cap),
    so convergence is guaranteed. Damping factor prevents oscillation in
    splitter cycles.
    """
    scc_set = set(scc)
    damping = 0.7

    for iteration in range(max_iter):
        max_delta = 0.0

        for nid in scc:
            old_output = nodes[nid].available_output
            _calculate_node_flow(nid, nodes, edges)
            new_output = nodes[nid].available_output

            # Apply damping to prevent oscillation
            damped = damping * new_output + (1.0 - damping) * old_output
            nodes[nid].available_output = damped

            # Re-distribute damped output to outgoing edges
            if nodes[nid].out_edges:
                per_belt = damped / len(nodes[nid].out_edges)
                for eid in nodes[nid].out_edges:
                    edges[eid].flow_rate = min(per_belt, edges[eid].max_rate)

            delta = abs(damped - old_output)
            max_delta = max(max_delta, delta)

        if max_delta < epsilon:
            break


# ── Root Cause Analysis ──────────────────────────────────────────────────────


def perform_root_cause_analysis(issues, nodes, edges):
    """Augment issues with dominator-tree-based root cause analysis.

    Uses Lengauer-Tarjan dominator trees to mathematically identify the
    unique chokepoint (dominator) for each starved or backed-up machine.
    """
    from graph_algorithms import build_dominator_tree, build_reverse_dominator_tree

    # Build forward dominator tree (for starvation tracing)
    idom = build_dominator_tree(nodes, edges)
    # Build reverse dominator tree (for output backup tracing)
    rev_idom = build_reverse_dominator_tree(nodes, edges)

    for issue in issues:
        if issue["category"] == "Input Starvation":
            trace = _dominator_trace_starvation(
                issue["building_id"], nodes, edges, idom
            )
            if trace:
                issue.update(trace)
        elif issue["category"] == "Output Backup":
            trace = _dominator_trace_backup(
                issue["building_id"], nodes, edges, rev_idom
            )
            if trace:
                issue.update(trace)


def _find_edge_between(from_nid, to_nid, nodes, edges):
    """Find a direct edge from from_nid to to_nid, or None."""
    from_node = nodes.get(from_nid)
    if not from_node:
        return None
    for eid in from_node.out_edges:
        if edges[eid].dst == to_nid:
            return edges[eid]
    return None


def _dominator_trace_starvation(start_nid, nodes, edges, idom):
    """Walk up the dominator tree from a starved node to find the chokepoint.

    The immediate dominator is the unique node all flow must pass through.
    If it's at capacity, it's mathematically the bottleneck.
    """
    path = [{"type": "node", "id": start_nid}]
    visited = {start_nid}
    current = start_nid

    for _ in range(30):  # depth limit
        dom = idom.get(current)
        if not dom or dom == "__VIRTUAL_SOURCE__":
            break

        dom_node = nodes.get(dom)
        if not dom_node:
            break

        if dom in visited:
            return {
                "root_cause": "Feedback Loop (Dominator)",
                "suggestion": "Circular dependency in the dominator chain.",
                "trace": path,
                "dominator_id": dom,
            }
        visited.add(dom)

        # Find connecting edge (dominator → current path)
        connecting_edge = _find_edge_between(dom, current, nodes, edges)
        # If no direct edge, try to find any edge from dom that reaches current
        if not connecting_edge:
            for eid in dom_node.out_edges:
                connecting_edge = edges[eid]
                break  # take first outgoing edge as representative

        if connecting_edge:
            path.append({"type": "edge", "id": connecting_edge.belt_id})
        path.append({"type": "node", "id": dom})

        # Check: is the dominator's output edge the bottleneck?
        if connecting_edge and connecting_edge.flow_rate >= connecting_edge.max_rate * 0.99:
            return {
                "root_cause": "Belt Bottleneck (Dominator)",
                "suggestion": (
                    f"Belt from {dom_node.building_name} is at capacity "
                    f"({connecting_edge.max_rate:.0f}/min). This is the unique "
                    f"chokepoint — upgrading this belt fixes the starvation."
                ),
                "trace": path,
                "dominator_id": dom,
            }

        # Check dominator node itself
        if dom_node.category == "production" and dom_node.recipe_data:
            total_expected = sum(dom_node.expected_inputs.values())
            if total_expected > 0:
                suff = dom_node.available_input / total_expected
                if suff < 0.95:
                    # Dominator is starved too — continue up the chain
                    current = dom
                    continue

            # Dominator has enough input but may be underclocked
            if dom_node.clock_speed < 2.5:
                return {
                    "root_cause": "Underclocked Dominator",
                    "suggestion": (
                        f"{dom_node.building_name} is the unique chokepoint at "
                        f"{dom_node.clock_speed*100:.0f}% clock. Increase clock speed."
                    ),
                    "trace": path,
                    "dominator_id": dom,
                }
            else:
                return {
                    "root_cause": "Capacity-Limited Dominator",
                    "suggestion": (
                        f"{dom_node.building_name} is the unique chokepoint at max "
                        f"capacity. Build additional parallel machines."
                    ),
                    "trace": path,
                    "dominator_id": dom,
                }

        if dom_node.category == "miner":
            if dom_node.clock_speed < 2.5:
                return {
                    "root_cause": "Underclocked Miner (Dominator)",
                    "suggestion": (
                        f"{dom_node.building_name} at {dom_node.clock_speed*100:.0f}% "
                        f"is the source dominator. Increase clock or add another miner."
                    ),
                    "trace": path,
                    "dominator_id": dom,
                }
            else:
                return {
                    "root_cause": "Miner Rate Limit (Dominator)",
                    "suggestion": (
                        f"{dom_node.building_name} is at max extraction rate. "
                        f"Add another miner on a different node."
                    ),
                    "trace": path,
                    "dominator_id": dom,
                }

        # Logistics node — continue up
        current = dom

    return {
        "root_cause": "Complex Chain",
        "suggestion": "Dominator trace limit reached.",
        "trace": path,
    }


def _dominator_trace_backup(start_nid, nodes, edges, rev_idom):
    """Walk up the REVERSE dominator tree from a backed-up node.

    The reverse dominator identifies the downstream chokepoint — the
    unique node all output must pass through to reach sinks.
    """
    path = [{"type": "node", "id": start_nid}]
    visited = {start_nid}
    current = start_nid

    for _ in range(30):
        dom = rev_idom.get(current)
        if not dom or dom == "__VIRTUAL_SINK__":
            break

        dom_node = nodes.get(dom)
        if not dom_node:
            break

        if dom in visited:
            return {
                "root_cause": "Feedback Loop (Downstream)",
                "suggestion": "Circular dependency in downstream path.",
                "trace": path,
                "dominator_id": dom,
            }
        visited.add(dom)

        # Find connecting edge (current → dominator in original graph)
        connecting_edge = _find_edge_between(current, dom, nodes, edges)
        if connecting_edge:
            path.append({"type": "edge", "id": connecting_edge.belt_id})
        path.append({"type": "node", "id": dom})

        # Check belt capacity
        if connecting_edge and connecting_edge.flow_rate >= connecting_edge.max_rate * 0.99:
            return {
                "root_cause": "Belt Bottleneck (Downstream Dominator)",
                "suggestion": (
                    f"Belt to {dom_node.building_name} is at capacity "
                    f"({connecting_edge.max_rate:.0f}/min). Upgrade this belt."
                ),
                "trace": path,
                "dominator_id": dom,
            }

        if dom_node.category == "production" and dom_node.clock_speed < 2.5:
            return {
                "root_cause": "Downstream Underclocked (Dominator)",
                "suggestion": (
                    f"{dom_node.building_name} is the downstream chokepoint "
                    f"at {dom_node.clock_speed*100:.0f}%. Increase clock speed."
                ),
                "trace": path,
                "dominator_id": dom,
            }

        current = dom

    return {
        "root_cause": "Downstream Bottleneck",
        "suggestion": "Downstream machines are full.",
        "trace": path,
    }


# ── Issue Detection ──────────────────────────────────────────────────────────


def analyze_supply_chain(factory, recipe_db=None, by_norm=None, data_raw_path=None):
    """Full supply chain analysis.

    Returns:
        issues: list of issue dicts
        graph_stats: dict with graph analysis metadata
    """
    if recipe_db is None or by_norm is None:
        recipe_db, by_norm = load_recipe_db(data_raw_path)

    nodes, edges, unmatched = build_flow_graph(factory, recipe_db, by_norm)
    propagate_flow(nodes, edges)

    issues = []

    # ── 1. Belt/Pipe Bottleneck ──────────────────────────────────────────
    for eid, edge in edges.items():
        if edge.flow_rate >= edge.max_rate * 0.95 and edge.flow_rate > 0:
            src_node = nodes.get(edge.src)
            dst_node = nodes.get(edge.dst)
            belt = factory.belts.get(eid)
            src_name = src_node.building_name if src_node else "?"
            dst_name = dst_node.building_name if dst_node else "?"
            src_recipe = src_node.recipe_name if src_node else ""
            dst_recipe = dst_node.recipe_name if dst_node else ""

            severity = "error" if edge.flow_rate > edge.max_rate else "warning"
            issues.append(
                {
                    "severity": severity,
                    "category": "Belt Bottleneck",
                    "title": f"{belt.friendly_name} at capacity ({edge.max_rate:.0f}/min)",
                    "description": (
                        f"{belt.friendly_name} between {src_name}"
                        f"{' (' + src_recipe + ')' if src_recipe else ''}"
                        f" and {dst_name}"
                        f"{' (' + dst_recipe + ')' if dst_recipe else ''}"
                        f" is at {edge.flow_rate:.1f}/{edge.max_rate:.0f} items/min "
                        f"({edge.flow_rate/edge.max_rate*100:.0f}% capacity). "
                        f"Consider upgrading to a higher tier belt."
                    ),
                    "building_id": edge.dst,
                    "building_name": dst_name,
                    "recipe": dst_recipe,
                    "position": dst_node.position if dst_node else (0, 0, 0),
                    "belt_id": eid,
                    "flow_rate": round(edge.flow_rate, 1),
                    "max_rate": edge.max_rate,
                }
            )

    # ── 2. Input Starvation (clock too high for available supply) ────────
    for nid, node in nodes.items():
        if node.category not in ("production", "generator") or not node.recipe_data:
            continue
        if not node.expected_inputs:
            continue

        total_expected = sum(node.expected_inputs.values())
        if total_expected <= 0:
            continue

        sufficiency = (
            node.available_input / total_expected if total_expected > 0 else 1.0
        )
        if sufficiency < 0.90 and node.available_input > 0:
            deficit = total_expected - node.available_input
            issues.append(
                {
                    "severity": "error" if sufficiency < 0.5 else "warning",
                    "category": "Input Starvation",
                    "title": f"{node.building_name} starved ({sufficiency*100:.0f}% fed)",
                    "description": (
                        f"{node.building_name} ({node.recipe_name}) at {node.clock_speed*100:.0f}% clock "
                        f"needs {total_expected:.1f}/min input but only receives "
                        f"{node.available_input:.1f}/min ({sufficiency*100:.0f}%). "
                        f"Deficit: {deficit:.1f}/min. "
                        f"{'Lower clock speed or add more input supply.' if sufficiency < 0.8 else 'Minor shortage — check upstream.'}"
                    ),
                    "building_id": nid,
                    "building_name": node.building_name,
                    "recipe": node.recipe_name,
                    "position": node.position,
                    "clock_speed": node.clock_speed,
                    "expected_input": round(total_expected, 1),
                    "actual_input": round(node.available_input, 1),
                    "sufficiency": round(sufficiency, 3),
                }
            )

    # ── 3. Clock Too High (building clocked beyond input capacity) ───────
    for nid, node in nodes.items():
        if node.category != "production" or not node.recipe_data:
            continue
        if not node.expected_inputs or not node.in_edges:
            continue

        total_expected = sum(node.expected_inputs.values())
        if total_expected <= 0:
            continue

        # What's the max input the upstream belts can deliver?
        max_input_capacity = sum(edges[eid].max_rate for eid in node.in_edges)

        if max_input_capacity > 0 and total_expected > max_input_capacity * 1.05:
            # Clock speed demands more than belts can physically carry
            max_useful_clock = node.clock_speed * (max_input_capacity / total_expected)
            issues.append(
                {
                    "severity": "warning",
                    "category": "Clock Too High",
                    "title": f"{node.building_name} overclocked vs belt capacity",
                    "description": (
                        f"{node.building_name} ({node.recipe_name}) at {node.clock_speed*100:.0f}% clock "
                        f"needs {total_expected:.1f}/min input, but input belts can only carry "
                        f"{max_input_capacity:.0f}/min total. "
                        f"Max useful clock: {max_useful_clock*100:.0f}%."
                    ),
                    "building_id": nid,
                    "building_name": node.building_name,
                    "recipe": node.recipe_name,
                    "position": node.position,
                    "clock_speed": node.clock_speed,
                    "max_useful_clock": round(max_useful_clock, 3),
                }
            )

    # ── 4. Output Backup (downstream can't consume) ─────────────────────
    for nid, node in nodes.items():
        if node.category != "production" or not node.recipe_data:
            continue
        if not node.out_edges:
            continue

        total_output = sum(node.expected_outputs.values())
        max_output_capacity = sum(edges[eid].max_rate for eid in node.out_edges)

        if max_output_capacity > 0 and total_output > max_output_capacity * 1.05:
            issues.append(
                {
                    "severity": "warning",
                    "category": "Output Backup",
                    "title": f"{node.building_name} output exceeds belt capacity",
                    "description": (
                        f"{node.building_name} ({node.recipe_name}) produces "
                        f"{total_output:.1f}/min but output belts can only carry "
                        f"{max_output_capacity:.0f}/min. Production will back up."
                    ),
                    "building_id": nid,
                    "building_name": node.building_name,
                    "recipe": node.recipe_name,
                    "position": node.position,
                    "output_rate": round(total_output, 1),
                    "belt_capacity": round(max_output_capacity, 1),
                }
            )

    # ── 5. Splitter/Merger Overload ──────────────────────────────────────
    for nid, node in nodes.items():
        if node.category != "logistics":
            continue
        if not node.out_edges:
            continue

        if (
            "Splitter" in node.building_name
            or "Programmable" in node.building_name
            or "Smart" in node.building_name
        ):
            # Splitter: check if output belt capacity < input flow
            total_out_capacity = sum(edges[eid].max_rate for eid in node.out_edges)
            if (
                node.available_input > total_out_capacity * 1.05
                and node.available_input > 0
            ):
                issues.append(
                    {
                        "severity": "warning",
                        "category": "Splitter Overload",
                        "title": f"{node.building_name} output belts too slow",
                        "description": (
                            f"{node.building_name} receives {node.available_input:.1f}/min "
                            f"but output belts can only carry {total_out_capacity:.0f}/min total. "
                            f"Items will back up."
                        ),
                        "building_id": nid,
                        "building_name": node.building_name,
                        "recipe": None,
                        "position": node.position,
                    }
                )

        if "Merger" in node.building_name:
            # Merger: check if output belt < sum of inputs
            if node.out_edges:
                out_capacity = (
                    edges[node.out_edges[0]].max_rate if node.out_edges else 0
                )
                if (
                    node.available_input > out_capacity * 1.05
                    and node.available_input > 0
                ):
                    issues.append(
                        {
                            "severity": "warning",
                            "category": "Merger Overload",
                            "title": f"Merger output belt too slow",
                            "description": (
                                f"Merger receives {node.available_input:.1f}/min from "
                                f"{len(node.in_edges)} inputs but output belt capacity is only "
                                f"{out_capacity:.0f}/min."
                            ),
                            "building_id": nid,
                            "building_name": node.building_name,
                            "recipe": None,
                            "position": node.position,
                        }
                    )

    # ── 6. Dead-End Production (outputs going nowhere) ───────────────────
    for nid, node in nodes.items():
        if node.category != "production" or not node.recipe_data:
            continue
        if not node.out_edges and node.expected_outputs and node.is_producing:
            issues.append(
                {
                    "severity": "warning",
                    "category": "Dead End",
                    "title": f"{node.building_name} output not connected",
                    "description": (
                        f"{node.building_name} ({node.recipe_name}) is producing "
                        f"but has no output belts. Items will fill up and stall."
                    ),
                    "building_id": nid,
                    "building_name": node.building_name,
                    "recipe": node.recipe_name,
                    "position": node.position,
                }
            )

    # ── 7. No Input Connected ────────────────────────────────────────────
    for nid, node in nodes.items():
        if node.category != "production" or not node.recipe_data:
            continue
        if node.expected_inputs and not node.in_edges and node.recipe_name:
            issues.append(
                {
                    "severity": "error",
                    "category": "No Input",
                    "title": f"{node.building_name} has no input belts",
                    "description": (
                        f"{node.building_name} ({node.recipe_name}) needs "
                        f"{', '.join(f'{r:.0f}/min {i}' for i, r in node.expected_inputs.items())} "
                        f"but has no input connections."
                    ),
                    "building_id": nid,
                    "building_name": node.building_name,
                    "recipe": node.recipe_name,
                    "position": node.position,
                }
            )

    # ── 8. Idle Machines (have recipe + connections but not producing) ───
    for nid, node in nodes.items():
        if node.category == "production" and node.recipe_name and not node.is_producing:
            if node.in_edges or node.out_edges:
                issues.append(
                    {
                        "severity": "warning",
                        "category": "Idle Machine",
                        "title": f"{node.building_name} is idle",
                        "description": (
                            f"{node.building_name} ({node.recipe_name}) at "
                            f"{node.clock_speed*100:.0f}% clock is not producing. "
                            f"Has {len(node.in_edges)} input and {len(node.out_edges)} output connections. "
                            f"{'Input starvation likely.' if node.available_input < 0.01 else 'Output may be full.'}"
                        ),
                        "building_id": nid,
                        "building_name": node.building_name,
                        "recipe": node.recipe_name,
                        "position": node.position,
                        "clock_speed": node.clock_speed,
                    }
                )

    # ── 9. No Recipe Set ────────────────────────────────────────────────
    for nid, node in nodes.items():
        if node.category == "production" and not node.recipe_name:
            issues.append(
                {
                    "severity": "error",
                    "category": "No Recipe",
                    "title": f"{node.building_name} has no recipe",
                    "description": f"{node.building_name} is placed but has no recipe assigned.",
                    "building_id": nid,
                    "building_name": node.building_name,
                    "recipe": None,
                    "position": node.position,
                }
            )

    # ── 10. Idle Generators ─────────────────────────────────────────────
    for nid, node in nodes.items():
        if node.category == "generator" and not node.is_producing:
            issues.append(
                {
                    "severity": "info",
                    "category": "Idle Generator",
                    "title": f"{node.building_name} is idle",
                    "description": f"{node.building_name} is not generating power.",
                    "building_id": nid,
                    "building_name": node.building_name,
                    "recipe": None,
                    "position": node.position,
                }
            )

    # ── 11. Underutilized Miners ─────────────────────────────────────────
    for nid, node in nodes.items():
        if node.category != "miner":
            continue
        if not node.out_edges:
            continue
        base_rate = MINER_BASE_RATES.get(node.building_name, 0)
        if base_rate == 0:
            continue
        max_output = base_rate * node.clock_speed
        actual_consumed = sum(edges[eid].flow_rate for eid in node.out_edges)
        if (
            max_output > 0
            and actual_consumed < max_output * 0.5
            and actual_consumed > 0
        ):
            issues.append(
                {
                    "severity": "info",
                    "category": "Underutilized Miner",
                    "title": f"{node.building_name} output underused ({actual_consumed/max_output*100:.0f}%)",
                    "description": (
                        f"{node.building_name} at {node.clock_speed*100:.0f}% clock produces "
                        f"{max_output:.0f}/min but downstream only consumes {actual_consumed:.0f}/min."
                    ),
                    "building_id": nid,
                    "building_name": node.building_name,
                    "recipe": None,
                    "position": node.position,
                }
            )

    # Sort by severity
    severity_order = {"error": 0, "warning": 1, "info": 2}
    issues.sort(key=lambda x: severity_order.get(x["severity"], 3))

    # Perform Root Cause Analysis
    perform_root_cause_analysis(issues, nodes, edges)

    # Graph stats
    graph_stats = {
        "total_nodes": len(nodes),
        "total_edges": len(edges),
        "unmatched_recipes": sorted(unmatched),
        "recipes_matched": sum(1 for n in nodes.values() if n.recipe_data),
        "miners": sum(1 for n in nodes.values() if n.category == "miner"),
        "production_with_recipe": sum(
            1 for n in nodes.values() if n.category == "production" and n.recipe_data
        ),
    }

    return issues, graph_stats


if __name__ == "__main__":
    # Quick test
    import sys

    sys.path.insert(0, os.path.dirname(__file__))
    from save_parser import parse_save

    save_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "BASFSimulator_autosave_2.sav",
    )
    factory = parse_save(save_path)
    issues, stats = analyze_supply_chain(factory)

    print(f"\n{'='*60}")
    print(f"  SUPPLY CHAIN ANALYSIS")
    print(f"{'='*60}")
    print(f"Graph: {stats['total_nodes']} nodes, {stats['total_edges']} edges")
    print(f"Recipes matched: {stats['recipes_matched']}")
    print(f"Miners: {stats['miners']}")
    if stats["unmatched_recipes"]:
        print(f"Unmatched recipes: {stats['unmatched_recipes']}")

    from collections import Counter

    cats = Counter(i["category"] for i in issues)
    print(f"\n--- ISSUES: {len(issues)} ---")
    for cat, count in cats.most_common():
        print(f"  {count:>5}x {cat}")

    print(f"\n--- SAMPLE ISSUES ---")
    for issue in issues[:20]:
        icon = {"error": "X", "warning": "!", "info": "i"}[issue["severity"]]
        print(f"  [{icon}] {issue['title']}")
        print(f"      {issue['description'][:120]}")
