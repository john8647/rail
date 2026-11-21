import asyncio
import json
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse

from dispatcher import Dispatcher
from loader import load_world_from_json

BASE_DIR = Path(__file__).parent
# simulated seconds per tick (also real seconds between ticks)
TICK_S = 0.2
SEND_TIMEOUT_S = 1.0   # drop clients that can't keep up instead of stalling the sim

# How many services (trains T1..Tn) a game may use; chosen in the UI per game.
# The final rating charges a time penalty per service actually used.
DEFAULT_SERVICES = 5
MAX_SERVICES = 12
# Optional services to dispatch at start-up, e.g. [("T1", "UP"), ("T2", "DOWN")].
# Empty = the network starts clear and everything is dispatched from the UI.
STARTUP_SERVICES = []

world = None
dispatcher = None
services = DEFAULT_SERVICES   # fleet size for the current game
result_recorded = False
results = []                  # finished games this server session, newest first


def fleet_for(n):
    return [f"T{i}" for i in range(1, n + 1)]


def new_game(n_services=None):
    """(Re)build the world from network.json: clock, score and passengers back to 0."""
    global world, dispatcher, services, result_recorded
    if n_services is not None:
        services = n_services
    world = load_world_from_json(BASE_DIR / "network.json")
    dispatcher = Dispatcher(world, fleet_for(services))
    result_recorded = False
    for train_id, route_id in STARTUP_SERVICES:
        dispatcher.dispatch(train_id, route_id)


def record_result():
    """Store the finished game's rating once, when the goal is first reached."""
    global result_recorded
    if result_recorded or not world.complete:
        return
    result_recorded = True
    r = world.passengers.rating(len(dispatcher.used))
    r.update(fleet=services, at=time.strftime("%H:%M"))
    results.insert(0, r)
    del results[20:]
    print(f"[game] goal in {r['goal_time']}s with {r['services_used']} services "
          f"-> rating {r['rating']}")


def game_summary():
    used = len(dispatcher.used)
    ps = world.passengers
    best = max(results, key=lambda r: r["rating"]) if results else None
    return {
        "services": services,
        "max_services": MAX_SERVICES,
        "used": used,
        "penalty_s": ps.service_penalty_s if ps else None,
        "result": ps.rating(used) if ps and ps.complete else None,
        "results": results[:10],
        "best": best,
    }


new_game()

# Every connected browser tab. The simulation is advanced by ONE loop
# (simulation_loop) and the resulting state is broadcast to all of them, so
# opening more tabs no longer speeds the world up.
clients: set[WebSocket] = set()


def state_message():
    state = world.export_state()
    state["viewers"] = len(clients)
    state["dispatch"] = dispatcher.export()
    state["game"] = game_summary()
    return json.dumps(state)


def handle_command(msg):
    """Apply a dispatcher command from a browser; returns (ok, message)."""
    action = msg.get("action")
    train_id = msg.get("train")
    if action == "new_game":
        n = msg.get("services", services)
        if not isinstance(n, int) or isinstance(n, bool) or not 1 <= n <= MAX_SERVICES:
            return False, f"Services must be a whole number from 1 to {MAX_SERVICES}"
        new_game(n)
        return True, f"New game started with {n} service{'s' if n != 1 else ''} – clock and score reset"
    if world.complete:
        return False, "Goal reached – start a new game to dispatch again"
    if action == "dispatch":
        return dispatcher.dispatch(train_id, msg.get("route"))
    if action == "cancel":
        return dispatcher.cancel(train_id)
    if action == "withdraw":
        return dispatcher.withdraw(train_id)
    return False, f"Unknown action {action!r}"


async def _send(ws: WebSocket, text: str):
    try:
        await asyncio.wait_for(ws.send_text(text), SEND_TIMEOUT_S)
    except Exception:
        clients.discard(ws)


async def broadcast(text: str):
    await asyncio.gather(*(_send(ws, text) for ws in list(clients)))


async def simulation_loop():
    loop = asyncio.get_running_loop()
    next_tick = loop.time()
    while True:
        # The world only advances while someone is watching (as before),
        # but always at exactly one tick per TICK_S, however many viewers.
        if clients:
            if not world.complete:
                dispatcher.process()  # let queued trains enter once their block clears
            world.update(TICK_S)
            record_result()
            await broadcast(state_message())
        next_tick += TICK_S
        delay = next_tick - loop.time()
        if delay < 0:          # fell behind (e.g. machine asleep): resync
            next_tick = loop.time()
            delay = 0
        await asyncio.sleep(delay)


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(simulation_loop())
    try:
        yield
    finally:
        task.cancel()


app = FastAPI(lifespan=lifespan)


@app.get("/")
async def index():
    return FileResponse(BASE_DIR / "index.html")


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()

    # Static data first, then the current state so the map draws immediately.
    await ws.send_text(json.dumps(world.export_track_layout()))
    await ws.send_text(json.dumps(world.export_stations()))
    clients.add(ws)
    await ws.send_text(state_message())

    try:
        while True:
            # Commands: {"type": "command", "action": "dispatch"|"cancel"|"withdraw",
            #            "train": "T1", "route": "UP"}
            #           {"type": "command", "action": "new_game", "services": 4}
            raw = await ws.receive_text()
            try:
                msg = json.loads(raw)
                ok, message = handle_command(msg)
            except Exception as exc:          # bad JSON or unexpected error
                ok, message = False, f"Command failed: {exc}"
            print(f"[dispatch] {'OK ' if ok else 'ERR'} {message}")
            await ws.send_text(json.dumps(
                {"type": "command_result", "ok": ok, "message": message}))
            # Everyone sees the change on the next tick (<= TICK_S), which keeps
            # train-movement smoothing in the browser steady.
    except WebSocketDisconnect:
        pass
    finally:
        clients.discard(ws)
        print(f"WebSocket disconnected ({len(clients)} viewer(s) left)")
