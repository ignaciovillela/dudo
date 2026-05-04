import json
import uuid

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from game.manager import GameManager

app = FastAPI(title="Dudo")
app.mount("/static", StaticFiles(directory="static"), name="static")

manager = GameManager()


@app.get("/")
async def root():
    return FileResponse("static/index.html")


@app.websocket("/ws/{room_id}")
async def websocket_endpoint(websocket: WebSocket, room_id: str):
    session_player_id = str(uuid.uuid4())[:8]
    await manager.connect(websocket, room_id, session_player_id)
    try:
        while True:
            data = await websocket.receive_text()
            message = json.loads(data)
            current_player_id = manager.resolve_player_id(room_id, websocket) or session_player_id
            await manager.handle_message(room_id, current_player_id, message)
            session_player_id = manager.resolve_player_id(room_id, websocket) or current_player_id
    except WebSocketDisconnect:
        current_player_id = manager.resolve_player_id(room_id, websocket)
        if current_player_id:
            await manager.disconnect(room_id, current_player_id)
    except Exception as e:
        print(f"Error [{session_player_id}]: {e}")
        current_player_id = manager.resolve_player_id(room_id, websocket)
        if current_player_id:
            await manager.disconnect(room_id, current_player_id)
