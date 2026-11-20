class Node:
    def __init__(self, node_id, node_type, x, y):
        self.id = node_id
        self.type = node_type  # "station", "junction", "buffer"
        self.x = x
        self.y = y
