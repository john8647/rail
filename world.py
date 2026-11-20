import math


class World:
    def __init__(self):
        self.nodes = {}
        self.segments = {}
        self.switches = {}
        self.signals = {}
        self.blocks = {}
        self.stations = {}
        self.routes = {}
        self.trains = {}
        self.sim_time = 0.0
        self.block_occupancy = {block_id: None for block_id in self.blocks}
        self.passengers = None      # PassengerSystem, attached by the loader

    @property
    def complete(self):
        return self.passengers is not None and self.passengers.complete

    def segment_to_block(self, seg_id):
        for block_id, blk in self.blocks.items():
            # blk is a Block object, not a dict
            if seg_id in blk.segments:
                return block_id
        return None

    def add_node(self, node):
        self.nodes[node.id] = node

    def add_segment(self, seg):
        self.segments[seg.id] = seg

    def add_switch(self, sw):
        self.switches[sw.id] = sw

    def switch_at_node(self, node_id):
        return next(
            (sw for sw in self.switches.values() if sw.node == node_id),
            None,
        )

    def add_signal(self, sig):
        self.signals[sig.id] = sig

    def add_block(self, blk):
        self.blocks[blk.id] = blk
        self.block_occupancy.setdefault(blk.id, {})

    def add_station(self, st):
        self.stations[st.id] = st

    def add_route(self, rt):
        self.routes[rt.id] = rt

    def add_train(self, train):
        self.trains[train.id] = train

    def remove_train(self, train_id):
        """Take a train off the network, freeing its blocks and junction claims."""
        self.trains.pop(train_id, None)
        for occupants in self.block_occupancy.values():
            occupants.pop(train_id, None)
        for sw in self.switches.values():
            sw.release_route(train_id)
            sw.route_queue = [r for r in sw.route_queue if r[0] != train_id]

    def update(self, dt_s):
        if self.complete:           # goal reached: the clock and trains stop
            return
        self.sim_time += dt_s
        if self.passengers:
            self.passengers.update(dt_s)
        for train in self.trains.values():
            train.update(dt_s)

    def train_at_stop(self, train, station_id, final):
        """Called when a train stops at a station: everyone alights, then boarding."""
        if not self.passengers:
            return
        self.passengers.alight(train, station_id)
        if not final:
            self.passengers.board(train, station_id)

    def is_block_free(self, block_id):
        return not self.block_occupancy.get(block_id)

    def block_has_conflict(self, block_id, train_id, direction, segment_id=None):
        occupants = self.block_occupancy.get(block_id, {})
        opposite_direction = (direction[1], direction[0])
        for occupant_id, occupant_direction in occupants.items():
            if occupant_id == train_id:
                continue
            occupant_segment, occupant_path = occupant_direction
            segment = self.segments.get(segment_id)
            can_share = (
                segment_id is not None
                and occupant_segment == segment_id
                and segment is not None
                and segment.bidirectional
                and occupant_path == opposite_direction
            )
            if not can_share:
                return True
        return False

    def occupy_block(self, block_id, train_id, direction, segment_id=None):
        if block_id is None:
            return True
        if self.block_has_conflict(block_id, train_id, direction, segment_id):
            return False
        self.block_occupancy.setdefault(block_id, {})[train_id] = (
            segment_id, direction)
        return True

    def release_block(self, block_id, train_id):
        occupants = self.block_occupancy.get(block_id, {})
        occupants.pop(train_id, None)

    def next_stop(self, train):
        route = self.routes[train.route_id]
        for seg_id in route.segments[train.current_segment_index:]:
            node_id = self.segments[seg_id].to_node.id
            if node_id in route.stops:
                return node_id
        return None

    def export_state(self):
        trains_out = []

        for t in self.trains.values():
            seg = t.current_segment
            finished = t.finished or seg is None
            if finished:
                seg = self.segments.get(t.last_segment_id)
                pos_m = seg.length_m if seg else 0.0
            else:
                pos_m = t.pos_m

            x = y = 0
            if seg is not None:
                frac = min(max(pos_m / seg.length_m, 0.0), 1.0)
                x = seg.from_node.x + (seg.to_node.x - seg.from_node.x) * frac
                y = seg.from_node.y + (seg.to_node.y - seg.from_node.y) * frac
                t.last_x, t.last_y = x, y

            route = self.routes[t.route_id]
            trains_out.append({
                "id": t.id,
                "route": t.route_id,
                "segment": seg.id if seg else None,
                "pos_m": pos_m,
                "speed_mps": 0.0 if finished else t.v_mps,
                "x": x,
                "y": y,
                "finished": finished,
                "status": "FINISHED" if finished else t.status,
                "held_at": None if finished else t.held_at,
                "dwell_s": max(t.dwell_remaining_s, 0.0),
                "at_station": t.at_station,
                "next_stop": None if finished else self.next_stop(t),
                "leg": min(t.current_segment_index + 1, len(route.segments)),
                "legs": len(route.segments),
                "passengers": t.passengers,
                "delivered": t.delivered,
            })

        return {
            "type": "world_state",
            "time": self.sim_time,
            "passengers": self.passengers.export() if self.passengers else None,
            "trains": trains_out,
            "signals": self.export_signals(),
            "blocks": {
                blk_id: list(self.block_occupancy.get(blk_id, {}).keys())
                for blk_id in self.blocks
            },
            "switches": [
                {
                    "id": sw.id,
                    "node": sw.node,
                    "set_to": sw.current_route,
                    "owner": sw.route_owner,
                    "queue": [tid for tid, _ in sw.route_queue],
                }
                for sw in self.switches.values()
            ],
        }

    def export_signals(self):
        signals_out = []

        for signal in self.signals.values():
            segment = self.segments[signal.segment]
            progress = signal.position_m / segment.length_m
            x = segment.from_node.x +                 (segment.to_node.x - segment.from_node.x) * progress
            y = segment.from_node.y +                 (segment.to_node.y - segment.from_node.y) * progress
            signal.aspect = "GREEN" if self.is_block_free(
                signal.block_id) else "RED"

            signals_out.append({
                "id": signal.id,
                "segment": signal.segment,
                "position_m": signal.position_m,
                "next_segment": signal.next_segment,
                "block_id": signal.block_id,
                "occupied_by": list(
                    self.block_occupancy.get(signal.block_id, {}).keys()),
                "x": x,
                "y": y,
                "angle": math.atan2(
                    segment.to_node.y - segment.from_node.y,
                    segment.to_node.x - segment.from_node.x),
                "aspect": signal.aspect
            })

        return signals_out

    def export_stations(self):
        out = []

        for st in self.stations.values():
            node = self.nodes[st.id]

            out.append({
                "id": st.id,
                "name": st.name,
                "x": node.x,
                "y": node.y
            })

        return {
            "type": "stations",
            "stations": out
        }

    def export_track_layout(self):
        out = []

        for seg in self.segments.values():
            out.append({
                "id": seg.id,
                "from": seg.from_node.id,
                "to": seg.to_node.id,
                "x1": seg.from_node.x,
                "y1": seg.from_node.y,
                "x2": seg.to_node.x,
                "y2": seg.to_node.y,
                "length_m": seg.length_m,
                "speed_limit_kmh": seg.speed_limit_kmh,
                "bidirectional": seg.bidirectional,
                "block": self.segment_to_block(seg.id),
            })

        return {
            "type": "track_layout",
            "segments": out,
            "nodes": [
                {"id": n.id, "type": n.type, "x": n.x, "y": n.y}
                for n in self.nodes.values()
            ],
            "routes": {
                rt.id: {"segments": rt.segments, "stops": rt.stops}
                for rt in self.routes.values()
            },
        }
