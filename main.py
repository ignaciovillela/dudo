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
    player_id = str(uuid.uuid4())[:8]
    await manager.connect(websocket, room_id, player_id)
    try:
        while True:
            data = await websocket.receive_text()
            message = json.loads(data)
            await manager.handle_message(room_id, player_id, message)
    except WebSocketDisconnect:
        await manager.disconnect(room_id, player_id)
    except Exception as e:
        print(f"Error [{player_id}]: {e}")
        await manager.disconnect(room_id, player_id)
