class Route:
    def __init__(self, route_id, segments, stops):
        self.id = route_id
        self.segments = segments      # ordered list
        self.stops = stops            # list of dicts {station, platform}
