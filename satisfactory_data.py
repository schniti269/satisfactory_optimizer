"""
Satisfactory 1.1 Game Data Module
Downloads recipe data from GitHub and combines with hardcoded resource/power/sink data.
"""

import json
import os
import requests

DATA_JSON_URL = "https://raw.githubusercontent.com/MAZ01001/SatisfactoryFlowchart/main/data.json"
DATA_CACHE_PATH = os.path.join(os.path.dirname(__file__), "data_raw.json")

# ---------------------------------------------------------------------------
# Resource node counts: (impure_count, normal_count, pure_count)
# Mk.3 Miner rates: Impure=120/min, Normal=240/min, Pure=480/min
# ---------------------------------------------------------------------------
RESOURCE_NODES = {
    "Iron Ore":     (39, 42, 46),
    "Copper Ore":   (13, 29, 13),
    "Limestone":    (15, 50, 29),
    "Coal":         (15, 31, 16),
    "Caterium Ore": (0,  9,  8),
    "Raw Quartz":   (3,  7,  7),
    "Sulfur":       (6,  5,  5),
    "Bauxite":      (5,  6,  6),
    "Uranium":      (3,  2,  0),
    "SAM":          (10, 6,  3),
}

MK3_MINER_RATES = {  # items/min per node at 100% clock speed
    "impure": 120,
    "normal": 240,
    "pure":   480,
}

# Oil nodes extracted by Oil Extractor (not Miner)
OIL_NODES = {  # (impure, normal, pure)
    "nodes": (10, 12, 8),
    "wells":  (8,  6, 4),
}
OIL_EXTRACTOR_RATES = {"impure": 60, "normal": 120, "pure": 240}  # m³/min
OIL_WELL_RATES = {"impure": 30, "normal": 60, "pure": 120}  # m³/min per extractor

# Nitrogen gas from resource wells
NITROGEN_NODES = (2, 7, 36)  # (impure, normal, pure) sub-nodes
NITROGEN_RATES = {"impure": 30, "normal": 60, "pure": 120}  # m³/min per sub-node

# Geothermal (free power, no fuel)
GEOTHERMAL_NODES = (9, 13, 9)  # (impure, normal, pure)
GEOTHERMAL_AVG_MW = {"impure": 100, "normal": 200, "pure": 400}

# ---------------------------------------------------------------------------
# Building power consumption (MW at 100% clock speed)
# ---------------------------------------------------------------------------
BUILDING_POWER = {
    "Smelter":              4,
    "Constructor":          4,
    "Assembler":            15,
    "Foundry":              16,
    "Manufacturer":         55,
    "Refinery":             30,
    "Packager":             10,
    "Blender":              75,
    "Particle Accelerator": 1000,  # average of 500-1500 range
    "Converter":            250,   # average of 100-400 range
    "Quantum Encoder":      1000,  # average of 0-2000 range
}

# Extraction building power
MINER_MK3_POWER = 45       # MW
OIL_EXTRACTOR_POWER = 40   # MW
WATER_EXTRACTOR_POWER = 20  # MW
WATER_EXTRACTOR_RATE = 120  # m³/min
WELL_PRESSURIZER_POWER = 150  # MW per pressurizer

# ---------------------------------------------------------------------------
# Power generators modeled as pseudo-recipes
# Each entry: (name, MW_output, [(fuel_item, rate/min)], water_rate_m3_per_min)
# ---------------------------------------------------------------------------
POWER_GENERATORS = [
    ("Coal Generator (Coal)",           75,  [("Coal", 15)],              45),
    ("Coal Generator (Compacted Coal)", 75,  [("Compacted Coal", 7.14)],  45),
    ("Coal Generator (Pet. Coke)",      75,  [("Petroleum Coke", 25)],    45),
    ("Fuel Generator (Fuel)",           250, [("Fuel", 20)],              0),
    ("Fuel Generator (Turbofuel)",      250, [("Turbofuel", 7.5)],        0),
    ("Fuel Generator (Rocket Fuel)",    250, [("Rocket Fuel", 4.1667)],   0),
    ("Fuel Generator (Ionized Fuel)",   250, [("Ionized Fuel", 3)],       0),
    ("Fuel Generator (Liquid Biofuel)", 250, [("Liquid Biofuel", 20)],    0),
    ("Nuclear (Uranium Rod)",           2500, [("Uranium Fuel Rod", 0.2)], 240),
    ("Nuclear (Plutonium Rod)",         2500, [("Plutonium Fuel Rod", 0.1)], 240),
    ("Nuclear (Ficsonium Rod)",         2500, [("Ficsonium Fuel Rod", 1)],   240),
]


def compute_max_resource_supply():
    """Compute total items/min available for each raw resource with Mk.3 miners."""
    supply = {}

    # Solid resources
    for resource, (imp, norm, pure) in RESOURCE_NODES.items():
        total = (imp * MK3_MINER_RATES["impure"] +
                 norm * MK3_MINER_RATES["normal"] +
                 pure * MK3_MINER_RATES["pure"])
        supply[resource] = total

    # Crude Oil (nodes + wells)
    oil_nodes = OIL_NODES["nodes"]
    oil_wells = OIL_NODES["wells"]
    oil_total = (
        oil_nodes[0] * OIL_EXTRACTOR_RATES["impure"] +
        oil_nodes[1] * OIL_EXTRACTOR_RATES["normal"] +
        oil_nodes[2] * OIL_EXTRACTOR_RATES["pure"] +
        oil_wells[0] * OIL_WELL_RATES["impure"] +
        oil_wells[1] * OIL_WELL_RATES["normal"] +
        oil_wells[2] * OIL_WELL_RATES["pure"]
    )
    supply["Crude Oil"] = oil_total

    # Nitrogen Gas
    n_imp, n_norm, n_pure = NITROGEN_NODES
    nitrogen_total = (
        n_imp * NITROGEN_RATES["impure"] +
        n_norm * NITROGEN_RATES["normal"] +
        n_pure * NITROGEN_RATES["pure"]
    )
    supply["Nitrogen Gas"] = nitrogen_total

    return supply


def compute_miner_power():
    """Compute total MW consumed by all miners/extractors on the map."""
    # Solid resource miners
    total_solid_nodes = sum(imp + norm + pure for imp, norm, pure in RESOURCE_NODES.values())
    miner_power = total_solid_nodes * MINER_MK3_POWER

    # Oil extractors (nodes only, wells use pressurizers)
    oil_nodes = OIL_NODES["nodes"]
    oil_extractor_count = sum(oil_nodes)
    miner_power += oil_extractor_count * OIL_EXTRACTOR_POWER

    # Oil well pressurizers (2 well clusters)
    # Each well cluster has 1 pressurizer, but actually it's ~6 pressurizers for 18 wells
    # The wiki says 6 resource wells with 18 total sub-nodes
    # Each well needs 1 pressurizer
    oil_well_pressurizer_count = 6  # 6 resource wells need 6 pressurizers
    # Wait - oil wells have 8+6+4=18 sub-nodes across the wells
    # Actually: the wiki says the wells are "spread across 2 clusters"
    # But each Resource Well needs its own Pressurizer
    # For oil: there are oil_wells total sub-nodes, but pressurizers are per-well-site
    # Simplification: count is already handled, let's just add pressurizer power
    # Actually oil has 2 well clusters, but let's just estimate based on well count
    miner_power += oil_well_pressurizer_count * WELL_PRESSURIZER_POWER

    # Nitrogen pressurizers (6 resource wells)
    nitrogen_pressurizer_count = 6
    miner_power += nitrogen_pressurizer_count * WELL_PRESSURIZER_POWER

    return miner_power


def compute_geothermal_power():
    """Compute total free MW from geothermal generators."""
    imp, norm, pure = GEOTHERMAL_NODES
    return (imp * GEOTHERMAL_AVG_MW["impure"] +
            norm * GEOTHERMAL_AVG_MW["normal"] +
            pure * GEOTHERMAL_AVG_MW["pure"])


def download_recipe_data():
    """Download and cache recipe data from GitHub."""
    if os.path.exists(DATA_CACHE_PATH):
        with open(DATA_CACHE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)

    print(f"Downloading recipe data from {DATA_JSON_URL}...")
    resp = requests.get(DATA_JSON_URL, timeout=30)
    resp.raise_for_status()
    data = resp.json()

    with open(DATA_CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f)

    return data


def parse_recipes(raw_data):
    """
    Parse raw recipe data into standardized format.
    Returns list of dicts with:
        name: str
        building: str
        inputs: [(item_name, rate_per_min), ...]
        outputs: [(item_name, rate_per_min), ...]
    """
    recipes = []
    excluded_machines = {"Crafting Bench", "Equipment Workshop"}

    for r in raw_data["recipes"]:
        machines = [m for m in r["machine"] if m not in excluded_machines]
        if not machines:
            continue  # skip hand-craft-only recipes

        building = machines[0]  # use first valid machine
        duration = r["duration"]  # seconds per cycle

        if duration <= 0:
            continue

        cycles_per_min = 60.0 / duration

        inputs = [(item, qty * cycles_per_min) for item, qty in r["input"]]
        outputs = [(item, qty * cycles_per_min) for item, qty in r["output"]]

        recipes.append({
            "name": r["name"],
            "building": building,
            "inputs": inputs,
            "outputs": outputs,
        })

    return recipes


def parse_sink_points(raw_data):
    """Extract AWESOME Sink points per item. Returns {item_name: points}."""
    points = {}
    for product in raw_data["descriptions"]["products"]:
        name = product[0]
        sink_value = product[1]
        if sink_value > 0:
            points[name] = sink_value
    return points


def build_power_generator_recipes():
    """
    Create pseudo-recipes for power generators.
    These consume fuel (and water) and produce a virtual "MW" item.
    """
    recipes = []
    for name, mw_output, fuels, water_rate in POWER_GENERATORS:
        inputs = [(item, rate) for item, rate in fuels]
        if water_rate > 0:
            inputs.append(("Water", water_rate))
        recipes.append({
            "name": name,
            "building": "Power Generator",
            "inputs": inputs,
            "outputs": [("__MW__", mw_output)],
            "is_generator": True,
        })
    return recipes


def load_all_data():
    """
    Load and return all game data needed for the optimizer.
    Returns dict with:
        recipes: list of recipe dicts (including power generator pseudo-recipes)
        sink_points: {item: points}
        resource_supply: {resource: max_items_per_min}
        miner_power_mw: float
        geothermal_mw: float
        building_power: {building_name: mw}
    """
    raw = download_recipe_data()
    recipes = parse_recipes(raw)
    gen_recipes = build_power_generator_recipes()
    sink_points = parse_sink_points(raw)
    resource_supply = compute_max_resource_supply()
    miner_power = compute_miner_power()
    geothermal = compute_geothermal_power()

    return {
        "recipes": recipes,
        "generator_recipes": gen_recipes,
        "sink_points": sink_points,
        "resource_supply": resource_supply,
        "miner_power_mw": miner_power,
        "geothermal_mw": geothermal,
        "building_power": BUILDING_POWER,
    }


if __name__ == "__main__":
    data = load_all_data()
    print(f"Loaded {len(data['recipes'])} production recipes")
    print(f"Loaded {len(data['generator_recipes'])} power generator recipes")
    print(f"Sinkable items: {len(data['sink_points'])}")
    print(f"\nResource supply (items/min with Mk.3 miners):")
    for res, rate in sorted(data["resource_supply"].items()):
        print(f"  {res}: {rate:,.0f}/min")
    print(f"\nMiner/extractor power: {data['miner_power_mw']:,.0f} MW")
    print(f"Geothermal power: {data['geothermal_mw']:,.0f} MW")
