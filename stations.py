class Station:
    def __init__(self, station_id, name, platforms, dwell_default_s):
        self.id = station_id
        self.name = name
        self.platforms = platforms    # dict: platform -> {length_m}
        self.dwell_default_s = dwell_default_s
