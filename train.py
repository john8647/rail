# train.py

import math


class Train:
    def __init__(self, train_id, route_id, world,
                 max_accel_mps2=0.7, max_brake_mps2=-1.0):
        self.id = train_id
        self.route_id = route_id
        self.world = world

        # Route traversal
        self.current_segment_index = 0
        self.pos_m = 0.0
        self.v_mps = 0.0
        self.target_v_mps = 0.0

        # Physics limits
        self.max_accel_mps2 = max_accel_mps2
        self.max_brake_mps2 = max_brake_mps2

        # State
        self.finished = False

        self.last_x = None
        self.last_y = None

        # Station
        self.dwell_remaining_s = 0.0
        self.at_station = None

        # What the train is doing right now, for the UI:
        # RUNNING, DWELL, SIGNAL, WAIT_BLOCK, WAIT_SWITCH, FINISHED
        self.status = "RUNNING"
        self.held_at = None           # signal / block / switch holding it
        self.last_segment_id = None

        # Passengers
        self.passengers = 0           # currently on board
        self.delivered = 0            # total delivered this run (points earned)

    @property
    def current_segment(self):
        route = self.world.routes[self.route_id]
        if self.finished or self.current_segment_index >= len(route.segments):
            return None

        seg_id = route.segments[self.current_segment_index]
        return self.world.segments[seg_id]

    def compute_target_speed(self):
        seg = self.current_segment
        base_v_mps = seg.speed_limit_kmh * 1000 / 3600
        self.target_v_mps = base_v_mps

    def gradient_accel_bias(self):
        seg = self.current_segment
        g_pct = seg.gradient_pct
        return -0.05 * (g_pct / 1.0)

    @property
    def travel_direction(self):
        seg = self.current_segment
        return (seg.from_node.id, seg.to_node.id)

    def next_signal(self):
        seg = self.current_segment
        if seg is None:
            return None

        # Find signals on this segment
        sigs = [
            s for s in self.world.signals.values()
            if s.segment == seg.id and (
                s.next_segment is None or
                self.current_segment_index +
                1 < len(self.world.routes[self.route_id].segments)
                and s.next_segment == self.world.routes[self.route_id].segments[
                    self.current_segment_index + 1]
            )
        ]

        if not sigs:
            return None

        # Find the next signal ahead of the train
        ahead = [s for s in sigs if s.position_m >= self.pos_m]
        if not ahead:
            return None

        # Return the closest signal ahead
        return min(ahead, key=lambda s: s.position_m)

    def update(self, dt_s):
        route = self.world.routes[self.route_id]
        seg = self.current_segment

        # If no segment, we're done
        if seg is None:
            self.finished = True
            self.v_mps = 0.0
            self.status, self.held_at = "FINISHED", None
            return
        self.last_segment_id = seg.id

        # 1. Handle dwell
        if self.dwell_remaining_s > 0:
            print(
                f"[{self.id}] Dwelling at {self.at_station}, remaining={self.dwell_remaining_s:.1f}s")
            self.dwell_remaining_s -= dt_s
            self.v_mps = 0.0
            self.status, self.held_at = "DWELL", self.at_station
            return

        # 2. End-of-segment / arrival at station
        if self.pos_m >= seg.length_m:
            end_node = seg.to_node

            next_index = self.current_segment_index + 1
            old_block = self.world.segment_to_block(seg.id)

            # Check end of route before attempting to reserve a next block.
            if next_index >= len(route.segments):
                self.world.release_block(old_block, self.id)
                print(f"[{self.id}] FINISHED route at {end_node.id}")
                self.finished = True
                self.v_mps = 0.0
                self.at_station = end_node.id
                self.status, self.held_at = "FINISHED", None
                if end_node.id in route.stops:
                    self.world.train_at_stop(self, end_node.id, final=True)
                return

            next_seg_id = route.segments[next_index]

            # Switch check
            sw = self.world.switch_at_node(end_node.id)
            if sw is not None:
                if not sw.request_route(self.id, next_seg_id):
                    print(
                        f"[{self.id}] Waiting at switch {sw.node}, route {next_seg_id} queued")
                    self.v_mps = 0.0
                    self.status, self.held_at = "WAIT_SWITCH", sw.id
                    return

            new_seg = self.world.segments[next_seg_id]
            new_block = self.world.segment_to_block(new_seg.id)
            if not self.world.occupy_block(
                    new_block, self.id,
                    (new_seg.from_node.id, new_seg.to_node.id), new_seg.id):
                if sw is not None:
                    sw.release_route(self.id)
                print(f"[{self.id}] Waiting for block {new_block}")
                self.v_mps = 0.0
                self.status, self.held_at = "WAIT_BLOCK", new_block
                return

            self.world.release_block(old_block, self.id)
            if sw is not None:
                sw.release_route(self.id)
            self.pos_m -= seg.length_m
            self.current_segment_index = next_index

            # If this node is a stop, start dwell
            if end_node.id in route.stops:
                print(f"[{self.id}] ARRIVED at {end_node.id}, starting dwell")
                self.dwell_remaining_s = 10.0
                self.at_station = end_node.id
                self.v_mps = 0.0
                self.pos_m = 0.0
                self.status, self.held_at = "DWELL", end_node.id
                self.world.train_at_stop(self, end_node.id, final=False)
                return

            # Continue on new segment
            seg = self.current_segment

        # 3. If finished, do nothing
        if self.finished:
            return

        # 4. Compute target speed
        self.compute_target_speed()

        # 4.A Signal checking
        sig = self.next_signal()
        if sig is not None:
            sig_pos = sig.position_m
            block_id = sig.block_id

            if self.pos_m < sig_pos:
                if self.world.block_has_conflict(
                        block_id, self.id, self.travel_direction, seg.id):
                    print(
                        f"[{self.id}] RED ahead at {sig.id} protecting {block_id}")
                    self.v_mps = 0.0
                    self.status, self.held_at = "SIGNAL", sig.id
                    return

        # Moving again
        self.status, self.held_at = "RUNNING", None
        self.at_station = None

        # 5. Acceleration
        dv = self.target_v_mps - self.v_mps
        if dv > 0:
            a = min(self.max_accel_mps2, dv / dt_s)
        else:
            a = max(self.max_brake_mps2, dv / dt_s)

        # 6. Gradient
        a += self.gradient_accel_bias()

        # 7. Update speed
        self.v_mps += a * dt_s
        self.v_mps = max(self.v_mps, 0.0)

        # 8. Update position
        self.pos_m += self.v_mps * dt_s
