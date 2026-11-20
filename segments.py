class TrackSegment:
    def __init__(self, seg_id, from_node, to_node,
                 length_m, speed_limit_kmh, gradient_pct, bidirectional):
        self.id = seg_id
        self.from_node = from_node
        self.to_node = to_node
        self.length_m = length_m
        self.speed_limit_kmh = speed_limit_kmh
        self.gradient_pct = gradient_pct
        self.bidirectional = bidirectional
