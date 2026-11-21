class LinesideSignal:
    """A stop signal protecting the move from `segment` into `next_segment`.

    Junction signals also name the switch they protect (`switch`) and the
    outgoing segment that switch must be set to (`required_route`, which
    defaults to next_segment). Such a signal only clears when the switch is
    set and locked for the approaching train and the destination block is free.
    """

    def __init__(self, sig_id, segment, position_m, direction, block_id,
                 next_segment=None, switch=None, required_route=None):
        self.id = sig_id
        self.segment = segment
        self.position_m = position_m
        self.direction = direction
        self.block_id = block_id
        self.next_segment = next_segment
        self.switch = switch
        self.required_route = required_route or next_segment
        self.aspect = "RED"
