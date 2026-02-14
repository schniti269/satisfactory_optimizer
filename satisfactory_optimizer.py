"""
Satisfactory 1.1 Linear Programming Optimizer
Maximizes AWESOME Sink points/min using all map resources with Mk.3 miners.
Power generation is modeled as pseudo-recipes to keep the LP fully linear.
"""

import re
import pulp
from collections import defaultdict


def _safe_name(s):
    """Make a string safe for use as a PuLP variable name."""
    return re.sub(r'[^a-zA-Z0-9_]', '_', s)


def build_and_solve(data, verbose=True):
    """
    Build and solve the LP model.

    Args:
        data: dict from satisfactory_data.load_all_data()
        verbose: print progress and results

    Returns:
        solution dict with recipe_counts, sink_rates, item_flows, power_summary
    """
    recipes = data["recipes"]
    gen_recipes = data["generator_recipes"]
    sink_points = data["sink_points"]
    resource_supply = data["resource_supply"]
    miner_power = data["miner_power_mw"]
    geothermal = data["geothermal_mw"]
    building_power = data["building_power"]

    all_recipes = recipes + gen_recipes

    # -----------------------------------------------------------------------
    # Collect all items that appear in any recipe
    # -----------------------------------------------------------------------
    all_items = set()
    for r in all_recipes:
        for item, _ in r["inputs"]:
            all_items.add(item)
        for item, _ in r["outputs"]:
            all_items.add(item)
    all_items = sorted(all_items)

    raw_resources = set(resource_supply.keys())

    # Items that can be sunk (have positive sink value and are not waste)
    sinkable_items = {item for item in all_items if item in sink_points}

    if verbose:
        print(f"Building LP with {len(all_recipes)} recipes, {len(all_items)} items...")
        print(f"  Raw resources: {len(raw_resources)}")
        print(f"  Sinkable items: {len(sinkable_items)}")

    # -----------------------------------------------------------------------
    # Create LP problem
    # -----------------------------------------------------------------------
    prob = pulp.LpProblem("Satisfactory_Max_Sink_Points", pulp.LpMaximize)

    # Decision variables: how many instances of each recipe are running
    recipe_vars = {}
    for i, r in enumerate(all_recipes):
        var_name = f"r_{i}_{_safe_name(r['name'][:30])}"
        recipe_vars[i] = pulp.LpVariable(var_name, lowBound=0)

    # Decision variables: rate of each item sent to sink
    sink_vars = {}
    for item in sinkable_items:
        var_name = f"sink_{_safe_name(item[:40])}"
        sink_vars[item] = pulp.LpVariable(var_name, lowBound=0)

    # Decision variable: number of water extractors
    water_extractors = pulp.LpVariable("water_extractors", lowBound=0)

    # -----------------------------------------------------------------------
    # Objective: maximize total AWESOME Sink points per minute
    # -----------------------------------------------------------------------
    prob += pulp.lpSum(
        sink_vars[item] * sink_points[item]
        for item in sinkable_items
    ), "Total_Sink_Points_Per_Min"

    # -----------------------------------------------------------------------
    # Constraints
    # -----------------------------------------------------------------------

    # 1. Flow conservation for each item
    #    production - consumption - sink_rate = 0  (for non-raw items)
    #    supply + production - consumption - sink_rate >= 0  (for raw items)
    #    For __MW__: net production >= power demand
    for item in all_items:
        if item == "__MW__":
            continue  # handled separately

        production = []
        consumption = []

        for i, r in enumerate(all_recipes):
            for out_item, out_rate in r["outputs"]:
                if out_item == item:
                    production.append(out_rate * recipe_vars[i])
            for in_item, in_rate in r["inputs"]:
                if in_item == item:
                    consumption.append(in_rate * recipe_vars[i])

        sink_term = sink_vars.get(item, 0)

        if item == "Water":
            # Water: unlimited via extractors + recipe byproduct
            water_from_extractors = water_extractors * 120.0  # m³/min
            prob += (
                pulp.lpSum(production) + water_from_extractors
                - pulp.lpSum(consumption) - sink_term >= 0
            ), f"flow_{_safe_name(item[:40])}"
        elif item in raw_resources:
            # Raw resource: bounded supply from map
            prob += (
                resource_supply[item] + pulp.lpSum(production)
                - pulp.lpSum(consumption) - sink_term >= 0
            ), f"flow_{_safe_name(item[:40])}"
        else:
            # Produced item: must be balanced
            prob += (
                pulp.lpSum(production)
                - pulp.lpSum(consumption) - sink_term >= 0
            ), f"flow_{_safe_name(item[:40])}"

    # 2. Power balance constraint
    #    MW produced by generators + geothermal >= MW consumed by buildings + miners + water extractors
    mw_production = []
    for i, r in enumerate(all_recipes):
        for out_item, out_rate in r["outputs"]:
            if out_item == "__MW__":
                mw_production.append(out_rate * recipe_vars[i])

    # MW consumed by production buildings
    mw_consumption = []
    for i, r in enumerate(all_recipes):
        if r.get("is_generator"):
            continue  # generators don't consume power in this model
        building = r["building"]
        if building in building_power:
            mw_consumption.append(building_power[building] * recipe_vars[i])

    prob += (
        pulp.lpSum(mw_production) + geothermal
        - pulp.lpSum(mw_consumption)
        - miner_power
        - water_extractors * 20.0  # water extractor power
        >= 0
    ), "power_balance"

    # 3. Prevent sinking unsinkable waste (Uranium Waste, Plutonium Waste have 0 points)
    #    These items must still have balanced flow (production >= consumption)
    #    Already handled by flow conservation since they're not in sink_vars

    # -----------------------------------------------------------------------
    # Solve
    # -----------------------------------------------------------------------
    if verbose:
        print("Solving LP...")

    # Use CBC solver (bundled with PuLP)
    solver = pulp.PULP_CBC_CMD(msg=0, timeLimit=120)
    status = prob.solve(solver)

    if verbose:
        print(f"Status: {pulp.LpStatus[status]}")

    if status != pulp.constants.LpStatusOptimal:
        print(f"ERROR: LP did not find optimal solution. Status: {pulp.LpStatus[status]}")
        return None

    # -----------------------------------------------------------------------
    # Extract solution
    # -----------------------------------------------------------------------
    total_points = pulp.value(prob.objective)

    # Recipe counts (number of building instances)
    recipe_counts = {}
    for i, r in enumerate(all_recipes):
        val = recipe_vars[i].varValue
        if val and val > 0.001:
            recipe_counts[r["name"]] = {
                "count": val,
                "building": r["building"],
                "inputs": [(item, rate * val) for item, rate in r["inputs"]],
                "outputs": [(item, rate * val) for item, rate in r["outputs"]],
                "is_generator": r.get("is_generator", False),
            }

    # Sink rates
    sink_rates = {}
    for item in sinkable_items:
        val = sink_vars[item].varValue
        if val and val > 0.001:
            sink_rates[item] = {
                "rate": val,
                "points_per_min": val * sink_points[item],
            }

    # Water extractors
    water_ext_count = water_extractors.varValue or 0

    # Compute item flows
    item_production = defaultdict(float)
    item_consumption = defaultdict(float)
    for name, info in recipe_counts.items():
        for item, rate in info["outputs"]:
            if item != "__MW__":
                item_production[item] += rate
        for item, rate in info["inputs"]:
            item_consumption[item] += rate

    # Add raw resource supply as "production"
    for res, supply in resource_supply.items():
        # Only count what's actually consumed
        consumed = item_consumption.get(res, 0)
        produced_by_recipes = item_production.get(res, 0)
        # The actual amount extracted from the map
        map_extraction = max(0, consumed - produced_by_recipes)
        if map_extraction > 0:
            item_production[res] += map_extraction

    # Add water extraction
    if water_ext_count > 0:
        item_production["Water"] += water_ext_count * 120.0

    # Power summary
    total_mw_generated = sum(
        rate for name, info in recipe_counts.items()
        for item, rate in info["outputs"] if item == "__MW__"
    ) + geothermal

    building_counts = defaultdict(float)
    building_mw = defaultdict(float)
    for name, info in recipe_counts.items():
        if not info["is_generator"]:
            b = info["building"]
            building_counts[b] += info["count"]
            if b in building_power:
                building_mw[b] += info["count"] * building_power[b]

    total_mw_consumed = sum(building_mw.values()) + miner_power + water_ext_count * 20.0

    solution = {
        "status": pulp.LpStatus[status],
        "total_points_per_min": total_points,
        "recipe_counts": recipe_counts,
        "sink_rates": sink_rates,
        "water_extractors": water_ext_count,
        "item_production": dict(item_production),
        "item_consumption": dict(item_consumption),
        "power": {
            "generated_mw": total_mw_generated,
            "consumed_mw": total_mw_consumed,
            "geothermal_mw": geothermal,
            "miner_mw": miner_power,
            "water_extractor_mw": water_ext_count * 20.0,
            "building_mw": dict(building_mw),
            "building_counts": dict(building_counts),
        },
    }

    if verbose:
        print_solution(solution, sink_points)

    return solution


def print_solution(solution, sink_points):
    """Print a detailed summary of the optimization results."""
    print("\n" + "=" * 80)
    print(f"  OPTIMAL AWESOME SINK PRODUCTION")
    print(f"  Total: {solution['total_points_per_min']:,.0f} points/min")
    print("=" * 80)

    # Top sunk items by points
    print("\n--- TOP SUNK ITEMS (by points/min) ---")
    sorted_sink = sorted(
        solution["sink_rates"].items(),
        key=lambda x: x[1]["points_per_min"],
        reverse=True,
    )
    for item, info in sorted_sink[:30]:
        print(f"  {item:40s} {info['rate']:>10.2f}/min  "
              f"x{sink_points[item]:>10,} pts = {info['points_per_min']:>15,.0f} pts/min")

    # Building counts
    print("\n--- BUILDING COUNTS ---")
    power = solution["power"]
    for building, count in sorted(power["building_counts"].items()):
        mw = power["building_mw"].get(building, 0)
        print(f"  {building:30s} {count:>10.1f} buildings  ({mw:>10,.0f} MW)")

    # Generator counts
    print("\n--- POWER GENERATORS ---")
    for name, info in solution["recipe_counts"].items():
        if info["is_generator"]:
            mw = sum(rate for item, rate in info["outputs"] if item == "__MW__")
            print(f"  {name:40s} {info['count']:>10.1f} units  ({mw:>10,.0f} MW)")

    # Water extractors
    if solution["water_extractors"] > 0:
        print(f"\n  Water Extractors: {solution['water_extractors']:.1f} "
              f"({solution['water_extractors'] * 20:.0f} MW)")

    # Power summary
    print("\n--- POWER BALANCE ---")
    print(f"  Generated:        {power['generated_mw']:>12,.0f} MW")
    print(f"    Geothermal:     {power['geothermal_mw']:>12,.0f} MW")
    gen_from_fuel = power['generated_mw'] - power['geothermal_mw']
    print(f"    From fuel:      {gen_from_fuel:>12,.0f} MW")
    print(f"  Consumed:         {power['consumed_mw']:>12,.0f} MW")
    print(f"    Miners/Extract: {power['miner_mw']:>12,.0f} MW")
    print(f"    Water Extract:  {power['water_extractor_mw']:>12,.0f} MW")
    bld_total = sum(power['building_mw'].values())
    print(f"    Buildings:      {bld_total:>12,.0f} MW")
    print(f"  Surplus:          {power['generated_mw'] - power['consumed_mw']:>12,.0f} MW")

    # Resource utilization
    print("\n--- RESOURCE UTILIZATION ---")
    from satisfactory_data import compute_max_resource_supply
    supply = compute_max_resource_supply()
    for res in sorted(supply.keys()):
        consumed = solution["item_consumption"].get(res, 0)
        produced = solution["item_production"].get(res, 0) - supply[res] if res in solution["item_production"] else 0
        net_from_map = max(0, consumed - max(0, produced))
        pct = min(100, (net_from_map / supply[res] * 100)) if supply[res] > 0 else 0
        print(f"  {res:20s} {net_from_map:>10,.0f} / {supply[res]:>10,.0f}  ({pct:>5.1f}%)")


if __name__ == "__main__":
    from satisfactory_data import load_all_data
    data = load_all_data()
    solution = build_and_solve(data)
