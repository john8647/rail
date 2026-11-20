class Switch:
    def __init__(self, switch_id, node, legs, current_route):
        self.id = switch_id
        self.node = node
        self.legs = legs              # list of segment IDs
        self.current_route = current_route
        self.route_owner = None
        self.route_queue = []

    def request_route(self, train_id, segment_id):
        if segment_id not in self.legs:
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

    def release_route(self, train_id):
        if self.route_owner == train_id:
            self.route_owner = None
