import asyncio
import json
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

# Trains the dispatcher can put into service from the UI.
FLEET = ["T1", "T2", "T3", "T4", "T5"]
# Optional services to dispatch at start-up, e.g. [("T1", "UP"), ("T2", "DOWN")].
# Empty = the network starts clear and everything is dispatched from the UI.
STARTUP_SERVICES = []

world = None
dispatcher = None


def new_game():
    """(Re)build the world from network.json: clock, score and passengers back to 0."""
    global world, dispatcher
    world = load_world_from_json(BASE_DIR / "network.json")
    dispatcher = Dispatcher(world, FLEET)
    for train_id, route_id in STARTUP_SERVICES:
        dispatcher.dispatch(train_id, route_id)


new_game()

# Every connected browser tab. The simulation is advanced by ONE loop
# (simulation_loop) and the resulting state is broadcast to all of them, so
# opening more tabs no longer speeds the world up.
clients: set[WebSocket] = set()


def state_message():
    state = world.export_state()
    state["viewers"] = len(clients)
    state["dispatch"] = dispatcher.export()
    return json.dumps(state)


def handle_command(msg):
    """Apply a dispatcher command from a browser; returns (ok, message)."""
    action = msg.get("action")
    train_id = msg.get("train")
    if action == "new_game":
        new_game()
        return True, "New game started – clock and score reset"
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
            # Dispatcher commands: {"type": "command", "action": "dispatch"|"cancel"|"withdraw",
            #                       "train": "T1", "route": "UP"}
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
