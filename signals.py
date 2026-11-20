class LinesideSignal:
    def __init__(self, sig_id, segment, position_m, direction, block_id,
                 next_segment=None):
        self.id = sig_id
        self.segment = segment
        self.position_m = position_m
        self.direction = direction
        self.block_id = block_id
        self.next_segment = next_segment
        self.aspect = "RED"
