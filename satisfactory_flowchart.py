"""
Satisfactory Flowchart Generator — Factory Blueprint Style
Each recipe node shows building type and count.
Item nodes act as routing hubs between buildings.
Orthogonal (rectangular) edges for clean factory-style routing.
"""

import re
import os
import graphviz
from collections import defaultdict


def _sid(s):
    """Make a string safe for Graphviz IDs."""
    return re.sub(r'[^a-zA-Z0-9]', '_', s)


def _fmt(n):
    """Format a number compactly."""
    if abs(n) >= 1_000_000:
        return f"{n/1e6:.1f}M"
    if abs(n) >= 10_000:
        return f"{n/1e3:.1f}K"
    if abs(n) >= 100:
        return f"{n:,.0f}"
    if abs(n) >= 1:
        return f"{n:.1f}"
    return f"{n:.2f}"


# Building colors (fill, border)
BCOLORS = {
    "Smelter":              ("#5C4033", "#A0522D"),
    "Constructor":          ("#1E3A5F", "#4A90D9"),
    "Assembler":            ("#1B4332", "#52B788"),
    "Foundry":              ("#4A2800", "#CD7F32"),
    "Manufacturer":         ("#2D1B4E", "#9B72CF"),
    "Refinery":             ("#3D2B1F", "#D4A76A"),
    "Packager":             ("#0D3B3B", "#20B2AA"),
    "Blender":              ("#3D1111", "#E05555"),
    "Particle Accelerator": ("#3D0A2E", "#E040A0"),
    "Converter":            ("#3D3000", "#E0C040"),
    "Quantum Encoder":      ("#0A3D3D", "#40C0C0"),
}


def generate_flowchart(solution, resource_supply, output_path="satisfactory_flowchart"):
    """Generate a factory-blueprint-style flowchart."""
    from satisfactory_data import BUILDING_POWER

    rc = solution["recipe_counts"]
    sink_rates = solution["sink_rates"]
    power = solution["power"]

    # Split generators vs production
    generators = {n: i for n, i in rc.items() if i["is_generator"]}
    production = {n: i for n, i in rc.items()
                  if not i["is_generator"] and i["count"] >= 0.1}

    # ── Build item flow tracking ──────────────────────────────────────────
    item_prod = defaultdict(list)   # item -> [(recipe, rate)]
    item_cons = defaultdict(list)   # item -> [(recipe, rate)]
    for name, info in rc.items():
        if info["count"] < 0.01:
            continue
        for it, r in info["outputs"]:
            if it != "__MW__":
                item_prod[it].append((name, r))
        for it, r in info["inputs"]:
            item_cons[it].append((name, r))

    # All intermediate items (produced AND consumed by recipes)
    intermediate_items = set(item_prod.keys()) & set(item_cons.keys())
    # Items only produced (go to sink or surplus)
    sink_items = set(sink_rates.keys())
    raw_set = set(resource_supply.keys()) | {"Water"}

    # ── Create graph ──────────────────────────────────────────────────────
    dot = graphviz.Digraph("Factory", format="pdf", engine="dot")
    dot.attr(
        rankdir="LR",
        fontname="Consolas",
        fontsize="10",
        bgcolor="#0d1117",
        pad="0.8",
        nodesep="0.25",
        ranksep="0.8",
        dpi="200",
        splines="ortho",
        # No size constraint — let it be as big as needed
    )
    dot.attr("node", fontname="Consolas", fontsize="9",
             style="filled", penwidth="1.5")
    dot.attr("edge", fontname="Consolas", fontsize="7",
             penwidth="1.0", arrowsize="0.6")

    # ── SUMMARY BOX (top-left) ────────────────────────────────────────────
    total_bld = sum(i["count"] for i in production.values())
    total_gen = sum(i["count"] for i in generators.values())
    summary_rows = [
        ("SATISFACTORY 1.1 — MAX AWESOME SINK", "#FFD700", "14"),
        (f"{solution['total_points_per_min']:,.0f} pts/min", "#ff6b6b", "12"),
        (f"Production: {total_bld:,.0f} buildings | "
         f"Generators: {total_gen:,.0f} | "
         f"Water Ext: {solution['water_extractors']:,.0f}", "#8b949e", "9"),
        (f"Power: {_fmt(power['generated_mw'])} MW generated, "
         f"{_fmt(power['consumed_mw'])} MW consumed", "#8b949e", "9"),
    ]
    html = "<TABLE BORDER='0' CELLBORDER='0' CELLSPACING='3' CELLPADDING='4'>"
    for text, color, size in summary_rows:
        html += (f"<TR><TD ALIGN='LEFT'>"
                 f"<FONT COLOR='{color}' POINT-SIZE='{size}'>"
                 f"{text}</FONT></TD></TR>")
    html += "</TABLE>"
    dot.node("summary", f"<{html}>", shape="none", fillcolor="#0d1117")

    # ── RAW RESOURCE NODES ────────────────────────────────────────────────
    with dot.subgraph(name="cluster_raw") as g:
        g.attr(label="RAW RESOURCES", style="filled,rounded",
               color="#238636", fillcolor="#0d1f0d",
               fontcolor="#3fb950", fontsize="12", margin="16")
        for res in sorted(resource_supply.keys()):
            supply = resource_supply[res]
            nid = f"RAW_{_sid(res)}"
            g.node(nid,
                   f"{res}\\n{_fmt(supply)}/min",
                   shape="box3d", fillcolor="#162416",
                   fontcolor="#3fb950", color="#238636", penwidth="2")

    # Water node
    if solution["water_extractors"] > 0.1:
        wr = solution["water_extractors"] * 120
        dot.node("RAW_Water",
                 f"Water\\n{_fmt(wr)} m³/min\\n({solution['water_extractors']:.0f} ext.)",
                 shape="box3d", fillcolor="#0d1a2e",
                 fontcolor="#58a6ff", color="#1f6feb", penwidth="2")

    # ── ITEM NODES (routing hubs) ─────────────────────────────────────────
    # Create a small diamond/ellipse node for each intermediate item
    # This prevents spaghetti edges between recipe nodes
    item_nodes_created = set()

    def ensure_item_node(item):
        if item in item_nodes_created or item in raw_set:
            return
        item_nodes_created.add(item)
        nid = f"ITEM_{_sid(item)}"
        total_flow = sum(r for _, r in item_prod.get(item, []))
        dot.node(nid,
                 f"{item}\\n{_fmt(total_flow)}/min",
                 shape="ellipse", fillcolor="#21262d",
                 fontcolor="#c9d1d9", color="#30363d",
                 fontsize="8", width="0.1", height="0.1")

    # Create item nodes for everything that flows between recipes
    for item in intermediate_items:
        if item not in raw_set:
            ensure_item_node(item)

    # Also create item nodes for sink-only items
    for item in sink_items:
        if item not in raw_set:
            ensure_item_node(item)

    # ── RECIPE NODES (the buildings) ──────────────────────────────────────
    for name, info in sorted(production.items(),
                              key=lambda x: x[1]["count"], reverse=True):
        nid = f"RCP_{_sid(name)}"
        bld = info["building"]
        cnt = info["count"]
        mw = BUILDING_POWER.get(bld, 0) * cnt
        fill, border = BCOLORS.get(bld, ("#333", "#666"))

        # Build a table: inputs | BUILDING | outputs
        in_items = [(it, r) for it, r in info["inputs"]]
        out_items = [(it, r) for it, r in info["outputs"] if it != "__MW__"]

        short_name = name.replace("Alternate: ", "Alt: ")

        # Build HTML-label table
        rows = []
        # Title row
        rows.append(
            f"<TR><TD COLSPAN='3'><B><FONT COLOR='white' POINT-SIZE='9'>"
            f"{short_name}</FONT></B></TD></TR>"
        )

        # Input | Building | Output row
        in_cell = ""
        if in_items:
            in_lines = "".join(
                f"<TR><TD ALIGN='RIGHT'><FONT COLOR='#8b949e' POINT-SIZE='7'>"
                f"{_fmt(r)}/m {it}</FONT></TD></TR>"
                for it, r in in_items
            )
            in_cell = f"<TABLE BORDER='0' CELLBORDER='0'>{in_lines}</TABLE>"
        else:
            in_cell = "<FONT COLOR='#555555' POINT-SIZE='7'>(free)</FONT>"

        out_cell = ""
        if out_items:
            out_lines = "".join(
                f"<TR><TD ALIGN='LEFT'><FONT COLOR='#8b949e' POINT-SIZE='7'>"
                f"{it} {_fmt(r)}/m</FONT></TD></TR>"
                for it, r in out_items
            )
            out_cell = f"<TABLE BORDER='0' CELLBORDER='0'>{out_lines}</TABLE>"
        else:
            out_cell = "<FONT COLOR='#555555' POINT-SIZE='7'>-</FONT>"

        rows.append(
            f"<TR>"
            f"<TD>{in_cell}</TD>"
            f"<TD BGCOLOR='{border}' CELLPADDING='6'>"
            f"<FONT COLOR='white' POINT-SIZE='8'>"
            f"{cnt:.0f}x {bld}\\n{_fmt(mw)} MW</FONT></TD>"
            f"<TD>{out_cell}</TD>"
            f"</TR>"
        )

        label = (
            f"<TABLE BORDER='0' CELLBORDER='0' CELLSPACING='1' CELLPADDING='2'>"
            + "".join(rows)
            + "</TABLE>"
        )

        dot.node(nid, f"<{label}>", shape="box", style="filled,rounded",
                 fillcolor=fill, color=border, penwidth="1.5")

    # ── POWER GENERATION NODES ────────────────────────────────────────────
    with dot.subgraph(name="cluster_power") as g:
        g.attr(label=f"POWER — {_fmt(power['generated_mw'])} MW",
               style="filled,rounded", color="#da3633",
               fillcolor="#1a0505", fontcolor="#f85149",
               fontsize="12", margin="16")

        g.node("GEN_geothermal",
               f"Geothermal\\n31 units | {_fmt(power['geothermal_mw'])} MW",
               shape="box", fillcolor="#3d0000",
               fontcolor="#f0883e", color="#da3633", penwidth="2")

        for gname, info in generators.items():
            gnid = f"GEN_{_sid(gname)}"
            mw = sum(r for it, r in info["outputs"] if it == "__MW__")
            fuel_str = ", ".join(f"{_fmt(r)}/m {it}" for it, r in info["inputs"])
            g.node(gnid,
                   f"{gname}\\n{info['count']:.0f}x | {_fmt(mw)} MW\\n{fuel_str}",
                   shape="box", fillcolor="#3d0000",
                   fontcolor="#f0883e", color="#da3633", penwidth="2")

    # ── SINK NODES ────────────────────────────────────────────────────────
    with dot.subgraph(name="cluster_sink") as g:
        g.attr(label=f"AWESOME SINK — {solution['total_points_per_min']:,.0f} pts/min",
               style="filled,rounded", color="#d29922",
               fillcolor="#1a1500", fontcolor="#e3b341",
               fontsize="14", margin="16")

        sorted_sink = sorted(sink_rates.items(),
                             key=lambda x: x[1]["points_per_min"], reverse=True)
        for item, info in sorted_sink[:10]:
            snid = f"SINK_{_sid(item)}"
            pct = info["points_per_min"] / solution["total_points_per_min"] * 100
            g.node(snid,
                   f"{item}\\n{_fmt(info['rate'])}/min\\n"
                   f"{_fmt(info['points_per_min'])} pts/min ({pct:.1f}%)",
                   shape="octagon", fillcolor="#332b00",
                   fontcolor="#FFD700", color="#d29922", penwidth="2")

    # ── EDGES ─────────────────────────────────────────────────────────────
    # Strategy: RAW -> RECIPE (direct), RECIPE -> ITEM -> RECIPE (via hubs),
    # RECIPE/ITEM -> SINK, RECIPE/ITEM -> GENERATOR

    edges_added = set()

    def add_edge(src, dst, color="#30363d", **kw):
        key = (src, dst)
        if key in edges_added:
            return
        edges_added.add(key)
        dot.edge(src, dst, color=color, **kw)

    # 1) RAW RESOURCE -> consuming recipes (direct)
    for res in resource_supply:
        rnid = f"RAW_{_sid(res)}"
        consumers = item_cons.get(res, [])
        for recipe_name, rate in consumers:
            if rate < 0.5:
                continue
            if recipe_name not in production and recipe_name not in generators:
                continue
            if recipe_name in generators:
                target = f"GEN_{_sid(recipe_name)}"
            else:
                target = f"RCP_{_sid(recipe_name)}"
            add_edge(rnid, target, color="#238636")

    # Water -> consuming recipes
    if solution["water_extractors"] > 0.1:
        for recipe_name, rate in item_cons.get("Water", []):
            if rate < 1:
                continue
            if recipe_name in generators:
                target = f"GEN_{_sid(recipe_name)}"
            elif recipe_name in production:
                target = f"RCP_{_sid(recipe_name)}"
            else:
                continue
            add_edge("RAW_Water", target, color="#1f6feb")

    # 2) RECIPE -> ITEM hub (for each output that is intermediate)
    for name, info in production.items():
        rnid = f"RCP_{_sid(name)}"
        for item, rate in info["outputs"]:
            if item == "__MW__" or rate < 0.1:
                continue
            if item in raw_set:
                # Recipe produces a raw resource (e.g. Water byproduct)
                # Route to its item node if it exists
                if item in item_nodes_created:
                    add_edge(rnid, f"ITEM_{_sid(item)}", color="#30363d")
                continue
            inid = f"ITEM_{_sid(item)}"
            if item in item_nodes_created:
                add_edge(rnid, inid, color="#30363d")

    # 3) ITEM hub -> consuming recipe
    for name, info in production.items():
        rnid = f"RCP_{_sid(name)}"
        for item, rate in info["inputs"]:
            if item in raw_set or rate < 0.1:
                continue  # raw handled above
            inid = f"ITEM_{_sid(item)}"
            if item in item_nodes_created:
                add_edge(inid, rnid, color="#30363d")

    # 4) ITEM/RECIPE -> SINK
    for item, info in sink_rates.items():
        if info["rate"] < 0.1:
            continue
        snid = f"SINK_{_sid(item)}"
        # From item hub or directly from recipe
        if item in item_nodes_created:
            add_edge(f"ITEM_{_sid(item)}", snid, color="#d29922", penwidth="2")
        else:
            # Direct from producer recipe
            prods = item_prod.get(item, [])
            if prods:
                top = max(prods, key=lambda x: x[1])
                if top[0] in production:
                    add_edge(f"RCP_{_sid(top[0])}", snid,
                             color="#d29922", penwidth="2")

    # 5) ITEM -> GENERATOR (fuel)
    for gname, info in generators.items():
        gnid = f"GEN_{_sid(gname)}"
        for item, rate in info["inputs"]:
            if item in raw_set:
                continue  # already connected from RAW
            if item in item_nodes_created:
                add_edge(f"ITEM_{_sid(item)}", gnid, color="#da3633")

    # ── RENDER ────────────────────────────────────────────────────────────
    dot_path = output_path + ".dot"
    with open(dot_path, "w", encoding="utf-8") as f:
        f.write(dot.source)
    print(f"DOT source: {dot_path}")

    for fmt in ["pdf", "svg", "png"]:
        try:
            dot.format = fmt
            tmp = output_path + f"_{fmt}"
            dot.render(tmp, cleanup=True)
            rendered = f"{tmp}.{fmt}"
            target = f"{output_path}.{fmt}"
            if os.path.exists(rendered):
                os.replace(rendered, target)
                print(f"{fmt.upper()} rendered: {target}")
        except Exception as e:
            if fmt == "pdf":
                print(f"Could not render {fmt}: {e}")
                print(f"  Render manually: dot -T{fmt} {dot_path} -o {output_path}.{fmt}")

    return dot_path


if __name__ == "__main__":
    from satisfactory_data import load_all_data
    from satisfactory_optimizer import build_and_solve

    data = load_all_data()
    solution = build_and_solve(data, verbose=False)
    if solution:
        generate_flowchart(solution, data["resource_supply"])
