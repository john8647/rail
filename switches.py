class Switch:
    """One set of points at a junction node.

    approaches: the incoming segments whose trains this switch routes.
    routes:     the outgoing segments it can be set to (one at a time).

    A junction can have several switches (JCT1 has SW_JCT1 for trains from
    MAIN and SW_JCT2 for trains from BRANCH_HALT / NORTH_HALT). A switch is
    locked to one train from the moment that train's signal clears until the
    train has entered the outgoing segment; while it is locked it cannot move.
    """

    def __init__(self, switch_id, node, routes, current_route, approaches=None):
        self.id = switch_id
        self.node = node
        self.routes = list(routes)            # outgoing segment IDs
        self.approaches = list(approaches or [])   # incoming segment IDs
        self.current_route = current_route
        self.route_owner = None
        self.route_queue = []

    def controls(self, from_seg, to_seg):
        return from_seg in self.approaches and to_seg in self.routes

    def is_set_for(self, segment_id, train_id=None):
        """Points lie towards segment_id and are not locked for another train."""
        return (self.current_route == segment_id
                and self.route_owner in (None, train_id))

    def set_route(self, segment_id):
        """Move the points without locking them (dispatcher / signaller control).

        Refused while a train holds the switch or for a route it cannot set.
        """
        if segment_id not in self.routes:
            return False, f"{self.id} cannot be set to {segment_id}"
        if self.route_owner is not None:
            return False, f"{self.id} is locked by {self.route_owner}"
        self.current_route = segment_id
        return True, f"{self.id} set to {segment_id}"

    def request_route(self, train_id, segment_id):
        """Set and lock the points for train_id towards segment_id.

        Returns True when the switch is (now) set and locked for this train.
        Requests that cannot be granted yet are queued in arrival order.
        """
        if segment_id not in self.routes:
            return False
        if self.route_owner == train_id:
            return self.current_route == segment_id
        if self.route_owner is None:
            if self.route_queue and self.route_queue[0] != (train_id, segment_id):
                return False
            if self.route_queue:
                self.route_queue.pop(0)
            self.route_owner = train_id
            self.current_route = segment_id
            return True
        request = (train_id, segment_id)
        if request not in self.route_queue:
            self.route_queue.append(request)
        return False

    def withdraw_request(self, train_id):
        """Drop a train's queued requests (it can't use the route right now)."""
        self.route_queue = [r for r in self.route_queue if r[0] != train_id]

    def release_route(self, train_id):
        if self.route_owner == train_id:
            self.route_owner = None
