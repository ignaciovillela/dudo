import json
import re
import uuid
from html import escape
from pathlib import Path
from urllib.parse import urlencode

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from game.manager import GameManager

app = FastAPI(title="Dudo")
app.mount("/static", StaticFiles(directory="static"), name="static")

manager = GameManager()
INDEX_PATH = Path("static/index.html")


def _replace_meta_tag(html: str, attr_name: str, attr_value: str, content: str) -> str:
    pattern = rf'(<meta\s+[^>]*{attr_name}="{re.escape(attr_value)}"[^>]*content=")([^"]*)("[^>]*>)'
    return re.sub(pattern, rf'\1{escape(content, quote=True)}\3', html)


def _replace_title(html: str, title: str) -> str:
    return re.sub(r"<title>.*?</title>", f"<title>{escape(title)}</title>", html, flags=re.DOTALL)


def _replace_canonical(html: str, canonical_url: str) -> str:
    pattern = r'(<link\s+rel="canonical"\s+href=")([^"]*)("\s*/?>)'
    return re.sub(pattern, rf'\1{escape(canonical_url, quote=True)}\3', html)


def _share_description_for_room(room_id: str) -> str:
    game = manager.games.get(room_id)
    if not game or not game.players:
        return f"Sala {room_id} de Dudo. Entra y sumate a la partida en tiempo real."

    ordered_names: list[str] = []
    for pid in game.player_order:
        player = game.players.get(pid)
        if player:
            ordered_names.append(player.name)

    if not ordered_names:
        return f"Sala {room_id} de Dudo. Entra y sumate a la partida en tiempo real."

    preview = ordered_names[:4]
    suffix = f" +{len(ordered_names) - 4}" if len(ordered_names) > 4 else ""
    players_text = ", ".join(preview) + suffix
    return f"Sala {room_id} de Dudo. Jugadores: {players_text}."


def _build_index_with_dynamic_meta(request: Request, room_id: str | None = None) -> str:
    html = INDEX_PATH.read_text(encoding="utf-8")

    base_url = str(request.base_url).rstrip("/")
    if room_id:
        query = urlencode({"sala": room_id})
        share_url = f"{base_url}/?{query}"
        title = f"Dudo — Sala {room_id}"
        description = _share_description_for_room(room_id)
    else:
        share_url = f"{base_url}/"
        title = "Dudo — El Juego de los Cachos"
        description = "Juega Dudo online con amigos: apuesta, duda, calza y sobrevive hasta el final."

    image_url = f"{base_url}/static/og-cover.png"

    html = _replace_title(html, title)
    html = _replace_meta_tag(html, "name", "description", description)
    html = _replace_meta_tag(html, "property", "og:url", share_url)
    html = _replace_meta_tag(html, "property", "og:title", title)
    html = _replace_meta_tag(html, "property", "og:description", description)
    html = _replace_meta_tag(html, "property", "og:image", image_url)
    html = _replace_meta_tag(html, "property", "og:image:alt", f"Invitacion a {title}")
    html = _replace_meta_tag(html, "name", "twitter:title", title)
    html = _replace_meta_tag(html, "name", "twitter:description", description)
    html = _replace_meta_tag(html, "name", "twitter:image", image_url)
    html = _replace_canonical(html, share_url)
    return html


@app.get("/")
async def root(request: Request, sala: str | None = None):
    room_id = sala.strip()[:20] if sala else None
    return HTMLResponse(_build_index_with_dynamic_meta(request, room_id))


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
