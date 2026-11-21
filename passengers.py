"""Passengers and scoring.

Rules:
* Each station accumulates waiting passengers at a steady rate, from 0 up to
  ``spawn_max`` in ``fill_time_s`` seconds, and never above ``spawn_max``.
* A train carries at most ``train_capacity`` passengers.
* At every stop, everyone on board gets off (1 point each, so 1 point per
  passenger per trip), then waiting passengers board, unless the stop is the
  end of the train's route.
* The game is complete when the score reaches ``goal_points``. The world then
  stops advancing and ``goal_time`` records how long it took.
* The final rating rewards reaching the goal quickly with few trains:
  every service (train) used adds ``service_penalty_s`` to the goal time, and
  rating = RATING_SCALE / (goal_time + service_penalty_s * services_used).
  Higher is better.
"""

RATING_SCALE = 1_000_000

DEFAULTS = {
    "spawn_max": 50,
    "fill_time_s": 120,
    "train_capacity": 40,
    "goal_points": 500,
    "service_penalty_s": 60,
}


class PassengerSystem:
    def __init__(self, world, config=None):
        cfg = {**DEFAULTS, **(config or {})}
        self.world = world
        self.spawn_max = cfg["spawn_max"]
        self.fill_time_s = cfg["fill_time_s"]
        self.rate_per_s = self.spawn_max / self.fill_time_s
        self.capacity = cfg["train_capacity"]
        self.goal = cfg["goal_points"]
        self.service_penalty_s = cfg["service_penalty_s"]

        self.waiting = {st_id: 0.0 for st_id in world.stations}
        self.score = 0
        self.boarded_total = 0
        self.delivered_at = {st_id: 0 for st_id in world.stations}
        self.goal_time = None
        self.events = []            # recent (time, text) for the UI log

    @property
    def complete(self):
        return self.goal_time is not None

    def rating(self, services_used):
        """Final rating once the goal is reached (None before then)."""
        if self.goal_time is None:
            return None
        adjusted_s = self.goal_time + self.service_penalty_s * max(services_used, 1)
        return {
            "rating": round(RATING_SCALE / adjusted_s),
            "goal_time": round(self.goal_time, 1),
            "services_used": services_used,
            "penalty_s": self.service_penalty_s,
            "adjusted_s": round(adjusted_s, 1),
        }

    def update(self, dt_s):
        for st_id in self.waiting:
            self.waiting[st_id] = min(self.spawn_max,
                                      self.waiting[st_id] + self.rate_per_s * dt_s)

    def _log(self, text):
        self.events.append((round(self.world.sim_time, 1), text))
        del self.events[:-12]

    def alight(self, train, station_id):
        n = train.passengers
        if n <= 0:
            return 0
        train.passengers = 0
        self.score += n
        self.delivered_at[station_id] = self.delivered_at.get(station_id, 0) + n
        train.delivered += n
        self._log(f"{train.id} delivered {n} at {station_id} (+{n})")
        if self.goal_time is None and self.score >= self.goal:
            self.goal_time = self.world.sim_time
            self._log(f"GOAL {self.goal} reached at {self.goal_time:.1f}s")
        return n

    def board(self, train, station_id):
        if station_id not in self.waiting:
            return 0
        space = self.capacity - train.passengers
        n = int(min(space, self.waiting[station_id] + 1e-6))   # 1e-6: float tick drift
        if n <= 0:
            return 0
        self.waiting[station_id] = max(0.0, self.waiting[station_id] - n)
        train.passengers += n
        self.boarded_total += n
        self._log(f"{train.id} boarded {n} at {station_id}")
        return n

    def export(self):
        return {
            "score": self.score,
            "goal": self.goal,
            "goal_time": self.goal_time,
            "complete": self.complete,
            "capacity": self.capacity,
            "spawn_max": self.spawn_max,
            "service_penalty_s": self.service_penalty_s,
            "on_board": sum(t.passengers for t in self.world.trains.values()),
            "waiting": {st: int(w + 1e-6) for st, w in self.waiting.items()},
            "delivered_at": dict(self.delivered_at),
            "events": [{"t": t, "text": x} for t, x in reversed(self.events)],
        }
