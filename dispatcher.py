"""Interactive dispatching: put fleet trains onto routes while the sim runs.

A dispatch request is queued if the route's first block is occupied and the
train enters automatically as soon as it clears (checked every tick).

Trains have a location. A train that has never run sits in the depot and can
enter service on any route. Every route is a round trip, so once a train has
run it is stabled at the station it started from, and can only be dispatched
on routes that start there. Withdrawing a train mid-trip returns it to the
start of that trip (its passengers are lost).
"""

from loader import spawn_train


class Dispatcher:
    def __init__(self, world, fleet):
        self.world = world
        self.fleet = list(fleet)        # train ids that can be dispatched
        self.pending = []               # [{"train", "route", "since"}] in FIFO order
        self.location = {tid: None for tid in self.fleet}   # None = depot (any route)

    # ------------------------------------------------------------ helpers
    def origin(self, route_id):
        return self.world.segments[self.world.routes[route_id].segments[0]].from_node.id

    def allowed_routes(self, train_id):
        loc = self.location.get(train_id)
        return [r for r in self.world.routes if loc is None or self.origin(r) == loc]

    def _station_name(self, st_id):
        st = self.world.stations.get(st_id)
        return st.name if st else st_id

    def _update_locations(self):
        for tid in self.fleet:
            t = self.world.trains.get(tid)
            if t is not None and t.finished and t.at_station:
                self.location[tid] = t.at_station

    def _active(self, train_id):
        t = self.world.trains.get(train_id)
        return t is not None and not t.finished

    def _pending_for(self, train_id):
        return next((p for p in self.pending if p["train"] == train_id), None)

    def _start_block(self, route_id):
        first_seg = self.world.routes[route_id].segments[0]
        return first_seg, self.world.segment_to_block(first_seg)

    def _start_blocked_by(self, train_id, route_id):
        """Return the occupants of the first block, or [] if the train can enter."""
        seg_id, block_id = self._start_block(route_id)
        seg = self.world.segments[seg_id]
        if not self.world.block_has_conflict(
                block_id, train_id, (seg.from_node.id, seg.to_node.id), seg_id):
            return []
        return [o for o in self.world.block_occupancy.get(block_id, {}) if o != train_id]

    # ------------------------------------------------------------ commands
    def dispatch(self, train_id, route_id):
        if train_id not in self.fleet:
            return False, f"{train_id} is not in the fleet"
        if route_id not in self.world.routes:
            return False, f"Unknown route {route_id}"
        if self._active(train_id):
            return False, f"{train_id} is already in service – withdraw it first"
        self._update_locations()
        if route_id not in self.allowed_routes(train_id):
            loc = self.location[train_id]
            options = ", ".join(self.allowed_routes(train_id)) or "none"
            return False, (f"{train_id} is at {self._station_name(loc)}; {route_id} starts at "
                           f"{self._station_name(self.origin(route_id))}. Routes from here: {options}")
        existing = self._pending_for(train_id)
        if existing:
            existing["route"] = route_id      # re-dispatch while queued: change route
            existing["since"] = self.world.sim_time
            return True, f"{train_id} queued for {route_id}"

        self.pending.append({"train": train_id, "route": route_id,
                             "since": self.world.sim_time})
        self.process()
        if self._active(train_id):
            return True, f"{train_id} dispatched on {route_id}"
        _, block_id = self._start_block(route_id)
        return True, f"{train_id} queued for {route_id} – waiting for {block_id} to clear"

    def cancel(self, train_id):
        p = self._pending_for(train_id)
        if not p:
            return False, f"{train_id} has no queued dispatch"
        self.pending.remove(p)
        return True, f"{train_id} dispatch cancelled"

    def withdraw(self, train_id):
        """Take a train out of service (running or finished) and free what it holds."""
        if train_id not in self.world.trains:
            return self.cancel(train_id)
        t = self.world.trains[train_id]
        lost = t.passengers
        # Back to the station it set out from (a finished train is already there).
        self.location[train_id] = t.at_station if t.finished else self.origin(t.route_id)
        self.world.remove_train(train_id)
        where = self._station_name(self.location[train_id])
        return True, (f"{train_id} withdrawn to {where}"
                      + (f" – {lost} passengers lost" if lost else ""))

    # ------------------------------------------------------------ per tick
    def process(self):
        """Spawn any queued trains whose first block is now free (FIFO per block)."""
        self._update_locations()
        claimed_blocks = set()
        for p in list(self.pending):
            _, block_id = self._start_block(p["route"])
            if block_id in claimed_blocks:
                continue                     # an earlier request is waiting for it
            if self._start_blocked_by(p["train"], p["route"]):
                claimed_blocks.add(block_id)
                continue
            # A finished train with the same id is replaced by the new run.
            if p["train"] in self.world.trains:
                self.world.remove_train(p["train"])
            spawn_train(self.world, p["train"], p["route"])
            self.location[p["train"]] = self.origin(p["route"])   # where it will return to
            self.pending.remove(p)
            print(f"[dispatch] {p['train']} entered service on {p['route']}")

    # ------------------------------------------------------------ export
    def export(self):
        self._update_locations()
        fleet = []
        for tid in self.fleet:
            t = self.world.trains.get(tid)
            p = self._pending_for(tid)
            if p:
                _, block_id = self._start_block(p["route"])
                fleet.append({"id": tid, "state": "QUEUED", "route": p["route"],
                              "waiting_for": block_id,
                              "blocked_by": self._start_blocked_by(tid, p["route"])})
            elif t is not None and not t.finished:
                fleet.append({"id": tid, "state": "IN_SERVICE", "route": t.route_id})
            elif t is not None:
                fleet.append({"id": tid, "state": "FINISHED", "route": t.route_id})
            else:
                fleet.append({"id": tid, "state": "AVAILABLE", "route": None})
            fleet[-1]["location"] = self.location[tid]          # None = depot
            fleet[-1]["allowed_routes"] = self.allowed_routes(tid)
        return {"fleet": fleet}
