"""
Satisfactory Save File Parser
Extracts buildings, recipes, connections, and production chain data.
Uses the satisfactory-save PyPI package (pip install satisfactory-save).
"""

import satisfactory_save as ss
from collections import defaultdict
from dataclasses import dataclass, field
import time
import os
import json


# ── Class name mappings ──────────────────────────────────────────────────
PRODUCTION_BUILDINGS = {
    "Build_SmelterMk1_C": "Smelter",
    "Build_ConstructorMk1_C": "Constructor",
    "Build_AssemblerMk1_C": "Assembler",
    "Build_FoundryMk1_C": "Foundry",
    "Build_ManufacturerMk1_C": "Manufacturer",
    "Build_OilRefinery_C": "Refinery",
    "Build_Packager_C": "Packager",
    "Build_Blender_C": "Blender",
    "Build_HadronCollider_C": "Particle Accelerator",
    "Build_Converter_C": "Converter",
    "Build_QuantumEncoder_C": "Quantum Encoder",
}

GENERATOR_BUILDINGS = {
    "Build_GeneratorCoal_C": "Coal Generator",
    "Build_GeneratorFuel_C": "Fuel Generator",
    "Build_GeneratorNuclear_C": "Nuclear Power Plant",
    "Build_GeneratorGeoThermal_C": "Geothermal Generator",
    "Build_GeneratorBiomass_Automated_C": "Biomass Burner",
    "Build_GeneratorBiomass_C": "Biomass Burner",
}

MINER_BUILDINGS = {
    "Build_MinerMk1_C": "Miner Mk.1",
    "Build_MinerMk2_C": "Miner Mk.2",
    "Build_MinerMk3_C": "Miner Mk.3",
    "Build_OilPump_C": "Oil Extractor",
    "Build_WaterPump_C": "Water Extractor",
    "Build_FrackingExtractor_C": "Resource Well Extractor",
    "Build_FrackingSmasher_C": "Resource Well Pressurizer",
}

LOGISTICS_BUILDINGS = {
    "Build_ConveyorAttachmentSplitter_C": "Splitter",
    "Build_ConveyorAttachmentSplitterSmart_C": "Smart Splitter",
    "Build_ConveyorAttachmentSplitterProgrammable_C": "Programmable Splitter",
    "Build_ConveyorAttachmentMerger_C": "Merger",
    "Build_PipelineJunction_Cross_C": "Pipe Junction",
    "Build_PipelinePumpMk2_C": "Pipeline Pump Mk.2",
    "Build_PipelinePump_C": "Pipeline Pump",
}

TRANSPORT_BUILDINGS = {
    "Build_TruckStation_C": "Truck Station",
    "Build_DroneStation_C": "Drone Port",
    "Build_TrainStation_C": "Train Station",
    "Build_TrainDockingStation_C": "Freight Platform",
    "Build_TrainDockingStationLiquid_C": "Fluid Freight Platform",
}

STORAGE_BUILDINGS = {
    "Build_StorageContainerMk1_C": "Storage Container",
    "Build_StorageContainerMk2_C": "Industrial Storage",
    "Build_CentralStorage_C": "Dimensional Depot",
    "Build_IndustrialTank_C": "Industrial Fluid Buffer",
    "Build_PipeStorageTank_C": "Fluid Buffer",
    "Build_StorageBlueprint_C": "Blueprint Storage",
}

BELT_CLASSES = {
    "Build_ConveyorBeltMk1_C": ("Belt Mk.1", 60),
    "Build_ConveyorBeltMk2_C": ("Belt Mk.2", 120),
    "Build_ConveyorBeltMk3_C": ("Belt Mk.3", 270),
    "Build_ConveyorBeltMk4_C": ("Belt Mk.4", 480),
    "Build_ConveyorBeltMk5_C": ("Belt Mk.5", 780),
    "Build_ConveyorBeltMk6_C": ("Belt Mk.6", 1200),
    "Build_ConveyorLiftMk1_C": ("Lift Mk.1", 60),
    "Build_ConveyorLiftMk2_C": ("Lift Mk.2", 120),
    "Build_ConveyorLiftMk3_C": ("Lift Mk.3", 270),
    "Build_ConveyorLiftMk4_C": ("Lift Mk.4", 480),
    "Build_ConveyorLiftMk5_C": ("Lift Mk.5", 780),
    "Build_ConveyorLiftMk6_C": ("Lift Mk.6", 1200),
}

PIPE_CLASSES = {
    "Build_Pipeline_C": ("Pipe Mk.1", 300),
    "Build_Pipeline_NoIndicator_C": ("Pipe Mk.1", 300),
    "Build_PipelineMK2_C": ("Pipe Mk.2", 600),
    "Build_PipelineMK2_NoIndicator_C": ("Pipe Mk.2", 600),
}

ALL_BUILDING_CLASSES = {}
ALL_BUILDING_CLASSES.update(PRODUCTION_BUILDINGS)
ALL_BUILDING_CLASSES.update(GENERATOR_BUILDINGS)
ALL_BUILDING_CLASSES.update(MINER_BUILDINGS)
ALL_BUILDING_CLASSES.update(LOGISTICS_BUILDINGS)
ALL_BUILDING_CLASSES.update(STORAGE_BUILDINGS)
ALL_BUILDING_CLASSES.update(TRANSPORT_BUILDINGS)


def _short_class(full_class):
    """Extract short class name from full Unreal path."""
    return full_class.split(".")[-1] if "." in full_class else full_class


def _recipe_name(full_path):
    """Extract human-readable recipe name from full Unreal path."""
    if not full_path:
        return None
    # /Game/FactoryGame/Recipes/Constructor/Recipe_Concrete.Recipe_Concrete_C
    name = full_path.split("/")[-1]       # Recipe_Concrete.Recipe_Concrete_C
    name = name.split(".")[0]              # Recipe_Concrete
    name = name.replace("Recipe_", "")
    name = name.replace("Alternate_", "Alt: ")
    name = name.replace("_", " ")
    return name


def _get_prop(props, name):
    """Get a property by name from PropertyList, returns None if not found."""
    try:
        return props.get(name)
    except Exception:
        return None


def _component_direction(comp_name):
    """
    Classify a component as 'input', 'output', or None based on its name.

    Building connectors:
      Input0/1/2, PipeInputFactory, PipeInputFactory1 → "input"
      Output0/1/2, PipeOutputFactory                  → "output"

    Belt/pipe connectors:
      ConveyorAny0 = belt's receiving end   → "belt_in"   (items flow INTO belt here)
      ConveyorAny1 = belt's delivering end  → "belt_out"  (items flow OUT of belt here)
      PipelineConnection0/1                 → None (direction inferred from building port)

    Non-connection components (inventories, power, legs): None
    """
    name = comp_name.split(".")[-1]  # get last segment
    low = name.lower()

    # Belt endpoints
    if name == "ConveyorAny0":
        return "belt_in"     # items enter belt here
    if name == "ConveyorAny1":
        return "belt_out"    # items leave belt here

    # Pipe endpoints — cannot determine direction from name alone
    if low.startswith("pipelineconnection"):
        return "pipe_end"

    # Building input ports (item)
    if low.startswith("input") and len(low) > 5 and low[5:].isdigit():
        return "input"
    # Building input ports (fluid)
    if low.startswith("pipeinputfactory"):
        return "input"

    # Building output ports (item)
    if low.startswith("output") and len(low) > 6 and low[6:].isdigit():
        return "output"
    # Building output ports (fluid)
    if low.startswith("pipeoutputfactory"):
        return "output"

    # Pipeline Pump/Junction: Connection0-3 = pipe connection points
    if low.startswith("connection") and len(low) > 10 and low[10:].isdigit():
        return "pipe_end"

    return None


@dataclass
class Building:
    """Represents a building placed on the map."""
    id: str              # unique path name
    class_name: str      # short class name
    friendly_name: str   # human-readable name
    category: str        # production/generator/miner/logistics/storage/other
    recipe: str = None   # recipe path (for production buildings)
    recipe_name: str = None  # human-readable recipe name
    clock_speed: float = 1.0
    is_producing: bool = False
    productivity: float = 0.0
    position: tuple = (0, 0, 0)
    connections: list = field(default_factory=list)  # connected building IDs (undirected)
    input_belts: list = field(default_factory=list)   # belt IDs feeding INTO this building
    output_belts: list = field(default_factory=list)  # belt IDs fed FROM this building


@dataclass
class Belt:
    """Represents a conveyor belt or pipe."""
    id: str
    class_name: str
    friendly_name: str
    max_rate: float       # items/min or m³/min
    is_pipe: bool = False
    connection_0: str = None  # component at one end
    connection_1: str = None  # component at other end
    src_building: str = None  # building ID that SENDS items into this belt
    dst_building: str = None  # building ID that RECEIVES items from this belt


@dataclass
class FactoryData:
    """Complete parsed factory data."""
    session_name: str
    play_hours: float
    buildings: dict = field(default_factory=dict)  # id -> Building
    belts: dict = field(default_factory=dict)       # id -> Belt
    connections: dict = field(default_factory=dict)  # component_path -> connected_component_path
    component_to_building: dict = field(default_factory=dict)  # component_path -> building_id
    component_direction: dict = field(default_factory=dict)    # component_path -> "input"/"output"/None
    stats: dict = field(default_factory=dict)


def parse_save(filepath: str) -> FactoryData:
    """Parse a Satisfactory .sav file and extract factory data."""
    t0 = time.time()
    print(f"Parsing save file: {os.path.basename(filepath)} ...")
    save = ss.SaveGame(filepath)
    t_parse = time.time() - t0
    print(f"  Binary parse: {t_parse:.1f}s")

    header = save.mSaveHeader
    factory = FactoryData(
        session_name=header.SessionName,
        play_hours=header.PlayDurationSeconds / 3600.0,
    )

    all_objs = save.allSaveObjects()
    print(f"  Total objects: {len(all_objs)}")

    # ── Pass 1: Collect all buildings, belts, and components ────────────
    t1 = time.time()
    actors = []
    components = []

    for obj in all_objs:
        if obj.isActor():
            actors.append(obj)
        else:
            components.append(obj)

    # Process actors (buildings, belts)
    for obj in actors:
        header = obj.Header
        oh = header.ObjectHeader
        class_full = oh.ClassName
        class_short = _short_class(class_full)
        obj_id = oh.Reference.PathName

        # Position
        t = header.Transform
        pos = (t.Translation.X, t.Translation.Y, t.Translation.Z)

        # Check what kind of building this is
        category = None
        friendly = class_short
        if class_short in PRODUCTION_BUILDINGS:
            category = "production"
            friendly = PRODUCTION_BUILDINGS[class_short]
        elif class_short in GENERATOR_BUILDINGS:
            category = "generator"
            friendly = GENERATOR_BUILDINGS[class_short]
        elif class_short in MINER_BUILDINGS:
            category = "miner"
            friendly = MINER_BUILDINGS[class_short]
        elif class_short in LOGISTICS_BUILDINGS:
            category = "logistics"
            friendly = LOGISTICS_BUILDINGS[class_short]
        elif class_short in STORAGE_BUILDINGS:
            category = "storage"
            friendly = STORAGE_BUILDINGS[class_short]
        elif class_short in TRANSPORT_BUILDINGS:
            category = "transport"
            friendly = TRANSPORT_BUILDINGS[class_short]
        elif class_short in BELT_CLASSES:
            name, rate = BELT_CLASSES[class_short]
            belt = Belt(
                id=obj_id, class_name=class_short,
                friendly_name=name, max_rate=rate, is_pipe=False,
            )
            factory.belts[obj_id] = belt
            for comp in obj.Object.Components:
                factory.component_to_building[comp.PathName] = obj_id
                d = _component_direction(comp.PathName)
                if d:
                    factory.component_direction[comp.PathName] = d
            continue
        elif class_short in PIPE_CLASSES:
            name, rate = PIPE_CLASSES[class_short]
            belt = Belt(
                id=obj_id, class_name=class_short,
                friendly_name=name, max_rate=rate, is_pipe=True,
            )
            factory.belts[obj_id] = belt
            for comp in obj.Object.Components:
                factory.component_to_building[comp.PathName] = obj_id
                d = _component_direction(comp.PathName)
                if d:
                    factory.component_direction[comp.PathName] = d
            continue
        else:
            continue  # skip non-factory objects (decorations, foundations, etc)

        # Extract properties for buildings
        props = obj.Object.Properties
        recipe_path = None
        recipe_friendly = None
        clock = 1.0
        producing = False
        productivity = 0.0

        recipe_prop = _get_prop(props, "mCurrentRecipe")
        if recipe_prop is not None and isinstance(recipe_prop, ss.ObjectProperty):
            recipe_path = recipe_prop.Value.PathName
            recipe_friendly = _recipe_name(recipe_path)

        pot_prop = _get_prop(props, "mCurrentPotential")
        if pot_prop is not None and isinstance(pot_prop, ss.FloatProperty):
            clock = pot_prop.Value

        prod_prop = _get_prop(props, "mIsProducing")
        if prod_prop is not None and isinstance(prod_prop, ss.BoolProperty):
            producing = prod_prop.Value

        # Productivity from measurement
        dur_prop = _get_prop(props, "mLastProductivityMeasurementDuration")
        prod_dur_prop = _get_prop(props, "mLastProductivityMeasurementProduceDuration")
        if (dur_prop is not None and isinstance(dur_prop, ss.FloatProperty) and
                prod_dur_prop is not None and isinstance(prod_dur_prop, ss.FloatProperty)):
            if dur_prop.Value > 0:
                productivity = prod_dur_prop.Value / dur_prop.Value

        building = Building(
            id=obj_id,
            class_name=class_short,
            friendly_name=friendly,
            category=category,
            recipe=recipe_path,
            recipe_name=recipe_friendly,
            clock_speed=clock,
            is_producing=producing,
            productivity=productivity,
            position=pos,
        )
        factory.buildings[obj_id] = building

        # Register building components with direction info
        for comp in obj.Object.Components:
            factory.component_to_building[comp.PathName] = obj_id
            d = _component_direction(comp.PathName)
            if d:
                factory.component_direction[comp.PathName] = d

    # ── Pass 2: Extract connections from components ─────────────────────
    for obj in components:
        oh = obj.Header.BaseHeader
        class_short = _short_class(oh.ClassName)
        comp_id = oh.Reference.PathName

        # Check for mConnectedComponent (belt/pipe endpoints)
        props = obj.Object.Properties
        conn_prop = _get_prop(props, "mConnectedComponent")
        if conn_prop is not None and isinstance(conn_prop, ss.ObjectProperty):
            connected_to = conn_prop.Value.PathName
            if connected_to:
                factory.connections[comp_id] = connected_to

    # ── Pass 3: Resolve DIRECTED connections ─────────────────────────────
    # For each connection between components, determine flow direction:
    #   Building output port → belt input end → ... → belt output end → Building input port
    #
    # Connection patterns:
    #   Building.Output0 ↔ Belt.ConveyorAny0   (building sends TO belt's input end)
    #   Belt.ConveyorAny1 ↔ Building.Input0    (belt's output end sends TO building)
    #   Building.PipeOutputFactory ↔ Pipe.PipelineConnection0/1
    #   Pipe.PipelineConnection0/1 ↔ Building.PipeInputFactory

    for comp_a, comp_b in factory.connections.items():
        bld_a = factory.component_to_building.get(comp_a)
        bld_b = factory.component_to_building.get(comp_b)
        if not bld_a or not bld_b or bld_a == bld_b:
            continue

        dir_a = factory.component_direction.get(comp_a)
        dir_b = factory.component_direction.get(comp_b)

        # Keep undirected adjacency list
        if bld_a in factory.buildings and bld_b not in factory.buildings[bld_a].connections:
            factory.buildings[bld_a].connections.append(bld_b)
        if bld_b in factory.buildings and bld_a not in factory.buildings[bld_b].connections:
            factory.buildings[bld_b].connections.append(bld_a)

        # ── Determine directed belt src/dst ──
        a_is_belt = bld_a in factory.belts
        b_is_belt = bld_b in factory.belts
        a_is_bldg = bld_a in factory.buildings
        b_is_bldg = bld_b in factory.buildings

        # Case 1: Building output → Belt input (building sends items into belt)
        if a_is_bldg and b_is_belt:
            if dir_a == "output" and dir_b in ("belt_in", "pipe_end"):
                factory.belts[bld_b].src_building = bld_a
                if bld_b not in factory.buildings[bld_a].output_belts:
                    factory.buildings[bld_a].output_belts.append(bld_b)
            elif dir_a == "input" and dir_b in ("belt_out", "pipe_end"):
                factory.belts[bld_b].dst_building = bld_a
                if bld_b not in factory.buildings[bld_a].input_belts:
                    factory.buildings[bld_a].input_belts.append(bld_b)
            # Pipe ambiguity: if both are pipe_end, use building port direction
            elif dir_b == "pipe_end" and dir_a == "output":
                factory.belts[bld_b].src_building = bld_a
                if bld_b not in factory.buildings[bld_a].output_belts:
                    factory.buildings[bld_a].output_belts.append(bld_b)
            elif dir_b == "pipe_end" and dir_a == "input":
                factory.belts[bld_b].dst_building = bld_a
                if bld_b not in factory.buildings[bld_a].input_belts:
                    factory.buildings[bld_a].input_belts.append(bld_b)

        # Case 2: Belt output → Building input (belt delivers items to building)
        elif a_is_belt and b_is_bldg:
            if dir_a in ("belt_out", "pipe_end") and dir_b == "input":
                factory.belts[bld_a].dst_building = bld_b
                if bld_a not in factory.buildings[bld_b].input_belts:
                    factory.buildings[bld_b].input_belts.append(bld_a)
            elif dir_a in ("belt_in", "pipe_end") and dir_b == "output":
                factory.belts[bld_a].src_building = bld_b
                if bld_a not in factory.buildings[bld_b].output_belts:
                    factory.buildings[bld_b].output_belts.append(bld_a)
            elif dir_a == "pipe_end" and dir_b == "output":
                factory.belts[bld_a].src_building = bld_b
                if bld_a not in factory.buildings[bld_b].output_belts:
                    factory.buildings[bld_b].output_belts.append(bld_a)
            elif dir_a == "pipe_end" and dir_b == "input":
                factory.belts[bld_a].dst_building = bld_b
                if bld_a not in factory.buildings[bld_b].input_belts:
                    factory.buildings[bld_b].input_belts.append(bld_a)

        # Case 3: Building (junction/pump) pipe_end ↔ Pipe pipe_end
        # When both sides are pipe_end, we can't infer direction from names.
        # But we CAN infer if the pipe already has partial direction:
        # If pipe has src_building set (knows where flow comes FROM), then
        # the other building must be the destination, and vice versa.
        if a_is_bldg and b_is_belt and dir_a == "pipe_end" and dir_b == "pipe_end":
            pipe = factory.belts[bld_b]
            if pipe.is_pipe:
                if pipe.src_building and not pipe.dst_building:
                    # Pipe knows its source, so this building is destination
                    pipe.dst_building = bld_a
                    if bld_b not in factory.buildings[bld_a].input_belts:
                        factory.buildings[bld_a].input_belts.append(bld_b)
                elif pipe.dst_building and not pipe.src_building:
                    # Pipe knows its destination, so this building is source
                    pipe.src_building = bld_a
                    if bld_b not in factory.buildings[bld_a].output_belts:
                        factory.buildings[bld_a].output_belts.append(bld_b)

        elif a_is_belt and b_is_bldg and dir_a == "pipe_end" and dir_b == "pipe_end":
            pipe = factory.belts[bld_a]
            if pipe.is_pipe:
                if pipe.src_building and not pipe.dst_building:
                    pipe.dst_building = bld_b
                    if bld_a not in factory.buildings[bld_b].input_belts:
                        factory.buildings[bld_b].input_belts.append(bld_a)
                elif pipe.dst_building and not pipe.src_building:
                    pipe.src_building = bld_b
                    if bld_a not in factory.buildings[bld_b].output_belts:
                        factory.buildings[bld_b].output_belts.append(bld_a)

        # Case 4: Belt ↔ Belt (belt chain, e.g. lift connecting two belts)
        # Just skip — these are intermediaries, direction flows through

    # ── Pass 3.5: Propagate pipe direction through pipe/junction chains ─
    # Pipes connect through PipelineJunctions and Pumps via pipe_end↔pipe_end.
    # After Pass 3, pipes touching a building's input/output ports have one
    # end resolved (src or dst). We now propagate through junctions:
    #   1. Collect all pipe_end↔pipe_end connections (pipe↔building and pipe↔pipe)
    #   2. Iteratively: if a pipe has src but no dst and connects to a building
    #      via pipe_end↔pipe_end, that building is the dst (and vice versa).
    #   3. Then propagate through junctions: if junction has a known-direction
    #      pipe on one port, other pipes on the junction can infer direction.

    # Collect all pipe_end↔pipe_end connections for iterative resolution
    pipe_end_connections = []  # [(pipe_id, other_id, is_other_building)]
    for comp_a, comp_b in factory.connections.items():
        bld_a = factory.component_to_building.get(comp_a)
        bld_b = factory.component_to_building.get(comp_b)
        if not bld_a or not bld_b or bld_a == bld_b:
            continue
        dir_a = factory.component_direction.get(comp_a)
        dir_b = factory.component_direction.get(comp_b)
        if dir_a != "pipe_end" or dir_b != "pipe_end":
            continue

        a_is_pipe = bld_a in factory.belts and factory.belts[bld_a].is_pipe
        b_is_pipe = bld_b in factory.belts and factory.belts[bld_b].is_pipe
        a_is_bldg = bld_a in factory.buildings
        b_is_bldg = bld_b in factory.buildings

        if a_is_pipe and b_is_bldg:
            pipe_end_connections.append((bld_a, bld_b, True))
        elif b_is_pipe and a_is_bldg:
            pipe_end_connections.append((bld_b, bld_a, True))
        elif a_is_pipe and b_is_pipe:
            pipe_end_connections.append((bld_a, bld_b, False))
            pipe_end_connections.append((bld_b, bld_a, False))

    # Iteratively resolve pipe directions
    changed = True
    iterations = 0
    while changed and iterations < 100:
        changed = False
        iterations += 1
        for pipe_id, other_id, other_is_building in pipe_end_connections:
            pipe = factory.belts[pipe_id]

            if other_is_building:
                bldg = factory.buildings[other_id]
                # Pipe has src → other building must be dst
                if pipe.src_building and not pipe.dst_building:
                    pipe.dst_building = other_id
                    if pipe_id not in bldg.input_belts:
                        bldg.input_belts.append(pipe_id)
                    changed = True
                # Pipe has dst → other building must be src
                elif pipe.dst_building and not pipe.src_building:
                    pipe.src_building = other_id
                    if pipe_id not in bldg.output_belts:
                        bldg.output_belts.append(pipe_id)
                    changed = True
                # Neither end known yet — check if building has known flow
                # from other pipes that already resolved
                elif not pipe.src_building and not pipe.dst_building:
                    # Check if any OTHER pipe already identified this building
                    # as a source or destination. For junctions this helps propagate.
                    bldg_has_input = len(bldg.input_belts) > 0
                    bldg_has_output = len(bldg.output_belts) > 0
                    # If junction has inputs, this pipe might be an output
                    # But we can't be sure for junctions. Skip for now —
                    # the iteration will resolve once one end gets known.
                    pass

            else:
                # Pipe-to-pipe connection (rare, but happens with inline pumps etc.)
                other_pipe = factory.belts.get(other_id)
                if not other_pipe:
                    continue
                # If this pipe has src and other pipe has dst (both partial),
                # they form a chain: this_pipe.src → [this_pipe] → [other_pipe] → other_pipe.dst
                # Not directly useful unless we collapse chains. Skip for now.

    # Count resolved pipes
    pipe_directed = sum(1 for b in factory.belts.values()
                        if b.is_pipe and b.src_building and b.dst_building
                        and b.src_building in factory.buildings
                        and b.dst_building in factory.buildings)
    belt_directed = sum(1 for b in factory.belts.values()
                        if not b.is_pipe and b.src_building and b.dst_building)
    print(f"  Pipe propagation: {iterations} iters, {pipe_directed} pipes directed, {belt_directed} belts directed")

    # ── Pass 4: Propagate direction through belt-to-belt chains ───────
    # Belts connect to other belts via conveyor lifts and end-to-end chains.
    # Pass 3 skipped Case 4 (belt↔belt). Now we propagate direction info
    # through these chains: if Belt A's output connects to Belt B's input,
    # items flow A→B. If A has src_building, B inherits it. If B has
    # dst_building, A inherits it. Iterate until stable.

    # Step 1: Collect all belt-to-belt connections with direction info
    belt_chain_conns = []  # [(belt_a_id, belt_b_id, direction)]
    for comp_a, comp_b in factory.connections.items():
        bld_a = factory.component_to_building.get(comp_a)
        bld_b = factory.component_to_building.get(comp_b)
        if not bld_a or not bld_b or bld_a == bld_b:
            continue
        a_is_belt = bld_a in factory.belts and not factory.belts[bld_a].is_pipe
        b_is_belt = bld_b in factory.belts and not factory.belts[bld_b].is_pipe
        if not (a_is_belt and b_is_belt):
            continue
        dir_a = factory.component_direction.get(comp_a)
        dir_b = factory.component_direction.get(comp_b)
        # belt_out(ConveyorAny1) → belt_in(ConveyorAny0): items flow A→B
        if dir_a == "belt_out" and dir_b == "belt_in":
            belt_chain_conns.append((bld_a, bld_b, "forward"))
        elif dir_a == "belt_in" and dir_b == "belt_out":
            belt_chain_conns.append((bld_a, bld_b, "backward"))

    # Step 2: Build belt adjacency graph
    belt_adj = defaultdict(list)
    for belt_a, belt_b, direction in belt_chain_conns:
        belt_adj[belt_a].append((belt_b, direction))
        # Add reverse: if A→B is forward, then B→A is backward
        rev = "backward" if direction == "forward" else "forward"
        belt_adj[belt_b].append((belt_a, rev))

    # Step 3: Iterative propagation
    belt_changed = True
    belt_iters = 0
    while belt_changed and belt_iters < 200:
        belt_changed = False
        belt_iters += 1
        for belt_id, neighbors in belt_adj.items():
            belt = factory.belts[belt_id]
            for neighbor_id, direction in neighbors:
                neighbor = factory.belts[neighbor_id]
                if direction == "forward":
                    # Items flow: belt → neighbor
                    # If belt has src_building, neighbor inherits it
                    if belt.src_building and not neighbor.src_building:
                        neighbor.src_building = belt.src_building
                        belt_changed = True
                    # If neighbor has dst_building, belt inherits it
                    if neighbor.dst_building and not belt.dst_building:
                        belt.dst_building = neighbor.dst_building
                        belt_changed = True
                elif direction == "backward":
                    # Items flow: neighbor → belt
                    if neighbor.src_building and not belt.src_building:
                        belt.src_building = neighbor.src_building
                        belt_changed = True
                    if belt.dst_building and not neighbor.dst_building:
                        neighbor.dst_building = belt.dst_building
                        belt_changed = True

    # Step 4: Register newly directed belts with their buildings
    for belt_id, belt in factory.belts.items():
        if belt.is_pipe:
            continue
        if belt.src_building and belt.dst_building:
            src_bldg = factory.buildings.get(belt.src_building)
            dst_bldg = factory.buildings.get(belt.dst_building)
            if src_bldg and belt_id not in src_bldg.output_belts:
                src_bldg.output_belts.append(belt_id)
            if dst_bldg and belt_id not in dst_bldg.input_belts:
                dst_bldg.input_belts.append(belt_id)

    # Recount after Pass 4
    belt_directed_after = sum(1 for b in factory.belts.values()
                              if not b.is_pipe and b.src_building and b.dst_building)
    total_directed = pipe_directed + belt_directed_after
    print(f"  Belt chain propagation: {belt_iters} iters, {belt_directed_after} belts directed "
          f"(was {belt_directed}), total directed: {total_directed}")

    # ── Compute stats ───────────────────────────────────────────────────
    t_extract = time.time() - t1
    print(f"  Extract: {t_extract:.1f}s")

    # Count buildings by category
    cat_counts = defaultdict(int)
    for b in factory.buildings.values():
        cat_counts[b.category] += 1

    # Count buildings by type
    type_counts = defaultdict(int)
    for b in factory.buildings.values():
        type_counts[b.friendly_name] += 1

    # Count recipes
    recipe_counts = defaultdict(int)
    for b in factory.buildings.values():
        if b.recipe_name:
            recipe_counts[b.recipe_name] += 1

    # Count producing vs idle
    producing = sum(1 for b in factory.buildings.values()
                    if b.category == "production" and b.is_producing)
    idle = sum(1 for b in factory.buildings.values()
               if b.category == "production" and not b.is_producing)

    # Low productivity buildings
    low_prod = [
        b for b in factory.buildings.values()
        if b.category == "production" and b.productivity < 0.5
        and b.recipe_name is not None
    ]

    factory.stats = {
        "total_objects": len(all_objs),
        "buildings": len(factory.buildings),
        "belts": len(factory.belts),
        "connections": len(factory.connections),
        "by_category": dict(cat_counts),
        "by_type": dict(type_counts),
        "by_recipe": dict(recipe_counts),
        "production_producing": producing,
        "production_idle": idle,
        "low_productivity_count": len(low_prod),
        "parse_time": t_parse + t_extract,
    }

    print(f"  Buildings: {len(factory.buildings)}, Belts: {len(factory.belts)}")
    print(f"  Connections: {len(factory.connections)}")
    print(f"  Done in {t_parse + t_extract:.1f}s total")

    return factory


def analyze_issues(factory: FactoryData) -> list:
    """
    Analyze the factory and find issues.
    Returns a list of issue dicts with severity, category, description, building_id, position.
    """
    issues = []

    # ── 1. Idle production buildings (have recipe but not producing) ─────
    for b in factory.buildings.values():
        if b.category == "production" and b.recipe_name and not b.is_producing:
            issues.append({
                "severity": "warning",
                "category": "Idle Machine",
                "title": f"{b.friendly_name} is idle",
                "description": (
                    f"{b.friendly_name} set to '{b.recipe_name}' is not producing. "
                    f"Check inputs/outputs."),
                "building_id": b.id,
                "building_name": b.friendly_name,
                "recipe": b.recipe_name,
                "position": b.position,
            })

    # ── 2. No recipe set on production building ─────────────────────────
    for b in factory.buildings.values():
        if b.category == "production" and not b.recipe_name:
            issues.append({
                "severity": "error",
                "category": "No Recipe",
                "title": f"{b.friendly_name} has no recipe",
                "description": f"{b.friendly_name} is placed but has no recipe assigned.",
                "building_id": b.id,
                "building_name": b.friendly_name,
                "recipe": None,
                "position": b.position,
            })

    # ── 3. Low productivity (producing but below 50%) ───────────────────
    for b in factory.buildings.values():
        if (b.category == "production" and b.recipe_name
                and b.is_producing and b.productivity < 0.5
                and b.productivity > 0.01):
            pct = b.productivity * 100
            issues.append({
                "severity": "warning",
                "category": "Low Productivity",
                "title": f"{b.friendly_name} at {pct:.0f}% efficiency",
                "description": (
                    f"{b.friendly_name} ({b.recipe_name}) running at only {pct:.0f}%. "
                    f"Likely starved of inputs or output backed up."),
                "building_id": b.id,
                "building_name": b.friendly_name,
                "recipe": b.recipe_name,
                "position": b.position,
                "productivity": b.productivity,
            })

    # ── 4. Unconnected buildings (no connections at all) ────────────────
    for b in factory.buildings.values():
        if b.category in ("production", "generator") and not b.connections:
            issues.append({
                "severity": "error",
                "category": "Unconnected",
                "title": f"{b.friendly_name} has no connections",
                "description": (
                    f"{b.friendly_name} ({b.recipe_name or 'no recipe'}) "
                    f"is not connected to any belts or pipes."),
                "building_id": b.id,
                "building_name": b.friendly_name,
                "recipe": b.recipe_name,
                "position": b.position,
            })

    # ── 5. Generators not producing ─────────────────────────────────────
    for b in factory.buildings.values():
        if b.category == "generator" and not b.is_producing:
            issues.append({
                "severity": "info",
                "category": "Idle Generator",
                "title": f"{b.friendly_name} is idle",
                "description": f"{b.friendly_name} is not generating power. May need fuel.",
                "building_id": b.id,
                "building_name": b.friendly_name,
                "recipe": None,
                "position": b.position,
            })

    # ── 6. Underclock detection (below 100% without reason) ─────────────
    for b in factory.buildings.values():
        if b.category == "production" and b.clock_speed < 0.95 and b.recipe_name:
            pct = b.clock_speed * 100
            issues.append({
                "severity": "info",
                "category": "Underclocked",
                "title": f"{b.friendly_name} at {pct:.0f}% clock",
                "description": (
                    f"{b.friendly_name} ({b.recipe_name}) underclocked to {pct:.0f}%. "
                    f"This is fine if intentional, but reduces throughput."),
                "building_id": b.id,
                "building_name": b.friendly_name,
                "recipe": b.recipe_name,
                "position": b.position,
                "clock_speed": b.clock_speed,
            })

    # Sort: errors first, then warnings, then info
    severity_order = {"error": 0, "warning": 1, "info": 2}
    issues.sort(key=lambda x: severity_order.get(x["severity"], 3))

    return issues


if __name__ == "__main__":
    save_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
                             "BASFSimulator_autosave_2.sav")
    if not os.path.exists(save_path):
        print(f"Save file not found: {save_path}")
        exit(1)

    factory = parse_save(save_path)
    issues = analyze_issues(factory)

    print(f"\n{'='*60}")
    print(f"  FACTORY ANALYSIS: {factory.session_name}")
    print(f"  Play time: {factory.play_hours:.1f} hours")
    print(f"{'='*60}")

    print(f"\n--- BUILDING COUNTS ---")
    for name, count in sorted(factory.stats["by_type"].items(),
                               key=lambda x: x[1], reverse=True)[:20]:
        print(f"  {count:>5}x {name}")

    print(f"\n--- RECIPE USAGE ---")
    for recipe, count in sorted(factory.stats["by_recipe"].items(),
                                 key=lambda x: x[1], reverse=True)[:20]:
        print(f"  {count:>5}x {recipe}")

    print(f"\n--- ISSUES FOUND: {len(issues)} ---")
    cat_counts = defaultdict(int)
    for issue in issues:
        cat_counts[issue["category"]] += 1
    for cat, count in sorted(cat_counts.items(), key=lambda x: x[1], reverse=True):
        print(f"  {count:>5}x {cat}")

    print(f"\n--- SAMPLE ISSUES ---")
    for issue in issues[:15]:
        icon = {"error": "X", "warning": "!", "info": "i"}[issue["severity"]]
        print(f"  [{icon}] {issue['title']}")
        print(f"      {issue['description'][:100]}")
