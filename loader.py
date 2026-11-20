import json
from world import World
from nodes import Node
from segments import TrackSegment
from switches import Switch
from signals import LinesideSignal
from stations import Station
from routes import Route
from blocks import Block
from train import Train
from passengers import PassengerSystem


def load_world_from_json(path):
    with open(path) as f:
        data = json.load(f)

    # FIX: create the world object
    world = World()

    # Nodes
    for node_id, nd in data["nodes"].items():
        world.add_node(Node(node_id, nd["type"], nd["x"], nd["y"]))

    # Segments
    for seg_id, sg in data["segments"].items():
        world.add_segment(TrackSegment(
            seg_id,
            world.nodes[sg["from"]],   # FIX: attach Node object
            world.nodes[sg["to"]],     # FIX: attach Node object
            sg["length_m"],
            sg["speed_limit_kmh"],
            sg["gradient_pct"],
            sg["bidirectional"]
        ))

    # Switches
    for sw_id, sw in data["switches"].items():
        world.add_switch(Switch(
            sw_id,
            sw["node"],
            sw["legs"],
            sw["current_route"]
        ))

    # Signals
    for sig_id, sg in data["signals"].items():
        world.add_signal(LinesideSignal(
            sig_id,
            sg["segment"],
            sg["position_m"],
            sg["direction"],
            sg["block_id"],
            sg.get("next_segment")
        ))

    # Blocks
    for blk_id, blk in data["blocks"].items():
        world.add_block(Block(blk_id, blk["segments"]))

    # Stations
    for st_id, st in data["stations"].items():
        world.add_station(Station(
            st_id,
            st["name"],
            st["platforms"],
            st["dwell_default_s"]
        ))

    # Routes
    for rt_id, rt in data["routes"].items():
        world.add_route(Route(
            rt_id,
            rt["segments"],
            rt["stops"]
        ))

    # Passengers & scoring (optional "passengers" section overrides the defaults)
    world.passengers = PassengerSystem(world, data.get("passengers"))

    for warning in validate_world(world):
        print(f"[network] WARNING: {warning}")

    return world


def validate_world(world):
    """Sanity-check the network so expansions don't silently break signalling.

    Returns a list of human-readable warnings (empty = all good).
    """
    warnings = []
    segs, blocks = world.segments, world.blocks

    # Every segment should belong to exactly one block.
    for seg_id in segs:
        owners = [b for b, blk in blocks.items() if seg_id in blk.segments]
        if len(owners) != 1:
            warnings.append(f"segment {seg_id} is in {len(owners)} blocks {owners}")
    for blk_id, blk in blocks.items():
        for seg_id in blk.segments:
            if seg_id not in segs:
                warnings.append(f"block {blk_id} lists unknown segment {seg_id}")

    # Signals must point at real things and describe a physically possible move.
    for sig in world.signals.values():
        seg = segs.get(sig.segment)
        if seg is None:
            warnings.append(f"signal {sig.id} is on unknown segment {sig.segment}")
            continue
        if not 0 <= sig.position_m <= seg.length_m:
            warnings.append(f"signal {sig.id} position {sig.position_m}m is off "
                            f"{seg.id} (length {seg.length_m}m)")
        if sig.block_id not in blocks:
            warnings.append(f"signal {sig.id} protects unknown block {sig.block_id}")
        if sig.next_segment is not None:
            nxt = segs.get(sig.next_segment)
            if nxt is None:
                warnings.append(f"signal {sig.id} next_segment {sig.next_segment} unknown")
            elif nxt.from_node.id != seg.to_node.id:
                warnings.append(f"signal {sig.id}: {seg.id} ends at {seg.to_node.id} but "
                                f"{nxt.id} starts at {nxt.from_node.id}")
            elif world.segment_to_block(nxt.id) != sig.block_id:
                warnings.append(f"signal {sig.id} protects {sig.block_id} but "
                                f"{nxt.id} is in {world.segment_to_block(nxt.id)}")

    # Routes must be continuous, and every move between segments should have a signal.
    used_signals = set()
    for rt in world.routes.values():
        # Round trips only: a train must finish where it started so it is in
        # place to be dispatched again (see dispatcher.py).
        if rt.segments and all(s in segs for s in (rt.segments[0], rt.segments[-1])):
            start = segs[rt.segments[0]].from_node.id
            end = segs[rt.segments[-1]].to_node.id
            if start != end:
                warnings.append(f"route {rt.id} starts at {start} but ends at {end} "
                                f"(routes must return to where they started)")
        for a, b in zip(rt.segments, rt.segments[1:]):
            if a not in segs or b not in segs:
                warnings.append(f"route {rt.id} uses unknown segment {a if a not in segs else b}")
                continue
            if segs[a].to_node.id != segs[b].from_node.id:
                warnings.append(f"route {rt.id} is not continuous: {a} -> {b}")
            sigs = [s.id for s in world.signals.values()
                    if s.segment == a and s.next_segment in (None, b)]
            used_signals.update(sigs)
            if not sigs:
                warnings.append(f"route {rt.id}: no signal protects {a} -> {b}")
    for sig_id in sorted(set(world.signals) - used_signals):
        warnings.append(f"signal {sig_id} is not used by any route")

    return warnings


def spawn_train(world, train_id, route_id):
    t = Train(train_id, route_id, world)
    block_id = world.segment_to_block(t.current_segment.id)
    if not world.occupy_block(
            block_id, train_id, t.travel_direction, t.current_segment.id):
        raise ValueError(
            f"Initial block {block_id} is occupied; cannot spawn {train_id}")
    world.add_train(t)
    # The train enters service at its origin platform: board waiting passengers.
    origin = t.current_segment.from_node.id
    if world.passengers and origin in world.routes[route_id].stops:
        world.passengers.board(t, origin)
        t.at_station = origin
    return t
