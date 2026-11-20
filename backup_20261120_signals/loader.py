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

    return world


def spawn_train(world, train_id, route_id):
    t = Train(train_id, route_id, world)
    block_id = world.segment_to_block(t.current_segment.id)
    if not world.occupy_block(
            block_id, train_id, t.travel_direction, t.current_segment.id):
        raise ValueError(
            f"Initial block {block_id} is occupied; cannot spawn {train_id}")
    world.add_train(t)
    return t
