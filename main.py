import json
import logging
import os
import re
import uuid
from contextlib import asynccontextmanager
from html import escape
from pathlib import Path
from urllib.parse import urlencode

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles

from game.manager import GameManager
from game.db import get_pool, close_pool
from game.migrations import run_migrations
from game.config import DEBUG_MODE, MAX_LEVEL
from game.audio_clips import (
    MAX_AUDIO_FILE_BYTES,
    MAX_AUDIO_SECONDS,
    MAX_PLAYER_AUDIO_SLOTS,
    audio_slot_unlock_level,
    delete_player_audio_clip,
    detect_audio_duration_seconds,
    ensure_player_exists,
    fetch_audio_clip_binary,
    fetch_player_audio_clips,
    get_system_audio_clips,
    infer_extension,
    max_audio_slots_for_level,
    normalize_anon_id,
    normalize_audio_color,
    normalize_audio_emoji,
    normalize_audio_label,
    normalize_level,
    serialize_clip_row,
    upsert_player_audio_clip,
)

log = logging.getLogger(__name__)

app = FastAPI(title="Dudo")
app.mount("/static", StaticFiles(directory="static"), name="static")

def normalize_room_id(room_id: str) -> str:
    """Los códigos de sala no distinguen mayúsculas de minúsculas."""
    return room_id.strip().casefold()


manager = GameManager()
INDEX_PATH = Path("static/index.html")

_db_ok = False  # se vuelve True si la DB arranca bien

_STATIC_DIR = Path(__file__).resolve().parent / "static"

def _compute_static_version() -> int:
    version = 0
    for f in _STATIC_DIR.rglob("*"):
        if f.is_file():
            mtime = int(f.stat().st_mtime)
            version = max(version, mtime)
    return version

STATIC_VERSION = _compute_static_version()


async def _startup():
    global _db_ok
    try:
        pool = await get_pool()
        await run_migrations(pool)

        restored = await manager.restore_all_rooms_from_db()
        if restored > 0:
            log.info("[startup] %d sala(s) restaurada(s) desde la DB — jugadores pueden reconectar", restored)

        from game.player_model import bluff_model
        await bluff_model.load_and_train(pool)
        _db_ok = True
        log.info("Base de datos conectada y migraciones aplicadas.")
    except OSError as exc:
        log.error(
            "\n"
            "╔══════════════════════════════════════════════════════════╗\n"
            "║  ERROR: No se pudo conectar a PostgreSQL                ║\n"
            "╠══════════════════════════════════════════════════════════╣\n"
            "║  Host : %s\n"
            "║  Causa: %s\n"
            "╠══════════════════════════════════════════════════════════╣\n"
            "║  El servidor arranca en modo degradado (sin persistencia)║\n"
            "║  Verifica POSTGRES_HOST / PORT en el archivo .env        ║\n"
            "╚══════════════════════════════════════════════════════════╝",
            _db_host(),
            exc,
        )
    except Exception as exc:
        log.error(
            "\n"
            "╔══════════════════════════════════════════════════════════╗\n"
            "║  ERROR de base de datos al iniciar                      ║\n"
            "╠══════════════════════════════════════════════════════════╣\n"
            "║  %s\n"
            "╠══════════════════════════════════════════════════════════╣\n"
            "║  El servidor arranca en modo degradado (sin persistencia)║\n"
            "╚══════════════════════════════════════════════════════════╝",
            exc,
        )


def _db_host() -> str:
    import os
    host = os.getenv("POSTGRES_HOST", "localhost")
    port = os.getenv("POSTGRES_PORT", "5432")
    return f"{host}:{port}"


async def _shutdown():
    # Persistir todas las salas activas antes de cerrar la DB
    for room_id in list(manager.games):
        await manager._persist_room_state(room_id)
    await close_pool()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    await _startup()
    try:
        yield
    finally:
        await _shutdown()


app.router.lifespan_context = lifespan


CANONICAL_URL = os.getenv("CANONICAL_URL", "https://dudo.igna.cl").rstrip("/")


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

    if len(ordered_names) == 1:
        players_text = ordered_names[0]
    else:
        players_text = ", ".join(ordered_names[:-1]) + f" y {ordered_names[-1]}"

    return f"Sala {room_id} de Dudo. Juega con {players_text}."


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
        title = "Dudo (Cacho, Perudo) — Juego de dados online gratis"
        description = (
            "Juega Dudo online y gratis, sin registro: el clásico juego de los cachos, también conocido como "
            "Perudo, Cachito o Liar's Dice. Crea una sala, invita a tus amigos o juega contra bots. "
            "Apuesta, duda, calza y sobrevive hasta el final."
        )

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
    # Las salas son efímeras: no se indexan y apuntan al home como canónica.
    html = _replace_canonical(html, f"{CANONICAL_URL}/")
    if room_id:
        html = _replace_meta_tag(html, "name", "robots", "noindex, follow")

    html = html.replace(
        'src="/static/app.js',
        f'src="/static/app.js?v={STATIC_VERSION}',
    )
    html = html.replace(
        'src="/static/tutorial.js',
        f'src="/static/tutorial.js?v={STATIC_VERSION}',
    )
    html = html.replace(
        'href="/static/style.css',
        f'href="/static/style.css?v={STATIC_VERSION}',
    )

    return html


@app.get("/")
async def root(request: Request, sala: str | None = None):
    room_id = normalize_room_id(sala)[:20] if sala else None
    return HTMLResponse(_build_index_with_dynamic_meta(request, room_id))



_PAGES_DIR = Path(__file__).resolve().parent / "static" / "pages"
_SEO_PAGES = (
    "como-jugar-dudo",
    "perudo",
    "liars-dice",
    "jugar-dudo-online",
    "estrategia-dudo",
    "glosario-dudo",
)
# URLs alternativas que la gente podría escribir o enlazar → página canónica.
_SEO_ALIASES = {
    "como-jugar": "como-jugar-dudo",
    "como-jugar-cacho": "como-jugar-dudo",
    "como-jugar-perudo": "perudo",
    "reglas": "como-jugar-dudo",
    "reglas-dudo": "como-jugar-dudo",
    "reglas-del-dudo": "como-jugar-dudo",
    "reglas-perudo": "perudo",
    "reglas-del-perudo": "perudo",
    "jugar-perudo": "perudo",
    "jugar-perudo-online": "perudo",
    "perudo-online": "perudo",
    "dudo-online": "jugar-dudo-online",
    "jugar-dudo": "jugar-dudo-online",
    "liar-s-dice": "liars-dice",
    "liarsdice": "liars-dice",
    "estrategia": "estrategia-dudo",
    "glosario": "glosario-dudo",
}


def _register_seo_page(slug: str) -> None:
    async def _page():
        return FileResponse(
            _PAGES_DIR / f"{slug}.html",
            media_type="text/html",
            headers={"Cache-Control": "public, max-age=3600"},
        )

    app.add_api_route(f"/{slug}", _page, methods=["GET"], include_in_schema=False)


def _register_seo_alias(alias: str, target: str) -> None:
    async def _redirect():
        return RedirectResponse(f"/{target}", status_code=301)

    for path in (f"/{alias}", f"/{alias}/"):
        app.add_api_route(path, _redirect, methods=["GET"], include_in_schema=False)


for _slug in _SEO_PAGES:
    _register_seo_page(_slug)
for _alias, _target in _SEO_ALIASES.items():
    _register_seo_alias(_alias, _target)


@app.get("/robots.txt", include_in_schema=False)
async def robots_txt():
    return FileResponse(Path(__file__).resolve().parent / "static" / "robots.txt", media_type="text/plain")


@app.get("/sitemap.xml", include_in_schema=False)
async def sitemap_xml():
    return FileResponse(Path(__file__).resolve().parent / "static" / "sitemap.xml", media_type="application/xml")


@app.get("/api/audio_clips/system")
async def get_system_audio_clips_api():
    return JSONResponse({"clips": get_system_audio_clips()})


@app.get("/api/player/{anon_id}/audio_clips")
async def get_player_audio_clips_api(anon_id: str, room_id: str):
    normalized_anon_id = normalize_anon_id(anon_id)
    if not normalized_anon_id:
        raise HTTPException(status_code=400, detail="anon_id inválido")

    room_id = normalize_room_id(room_id)
    if not manager.is_anon_present(room_id, normalized_anon_id):
        return JSONResponse({"clips": []})

    try:
        pool = await get_pool()
        rows = await fetch_player_audio_clips(pool, normalized_anon_id)
    except Exception as exc:
        log.warning("No se pudieron cargar audios de %s: %s", normalized_anon_id, exc)
        return JSONResponse({"clips": []}, status_code=503)

    return JSONResponse({
        "clips": [serialize_clip_row(row, room_id=room_id) for row in rows],
        "max_slots": MAX_PLAYER_AUDIO_SLOTS,
        "max_seconds": MAX_AUDIO_SECONDS,
        "max_level": MAX_LEVEL,
    })


@app.post("/api/player/{anon_id}/audio_clips")
async def upload_player_audio_clip_api(
    anon_id: str,
    room_id: str = Form(...),
    slot: int = Form(...),
    label: str = Form(...),
    emoji: str = Form("🎵"),
    color: str | None = Form(None),
    display_name: str = Form(""),
    level: int = Form(1),
    file: UploadFile = File(...),
):
    normalized_anon_id = normalize_anon_id(anon_id)
    if not normalized_anon_id:
        raise HTTPException(status_code=400, detail="anon_id inválido")

    room_id = normalize_room_id(room_id)
    if not manager.is_anon_present(room_id, normalized_anon_id):
        raise HTTPException(status_code=403, detail="Jugador no presente en la sala")

    if slot < 1 or slot > MAX_PLAYER_AUDIO_SLOTS:
        raise HTTPException(status_code=400, detail=f"slot debe ser 1..{MAX_PLAYER_AUDIO_SLOTS}")

    normalized_level = normalize_level(level)
    unlocked_slots = max_audio_slots_for_level(normalized_level)
    if slot > unlocked_slots:
        required_level = audio_slot_unlock_level(slot)
        raise HTTPException(
            status_code=403,
            detail=f"Necesitas nivel {required_level} para desbloquear el slot {slot} (tu nivel: {normalized_level})",
        )

    file_ext = infer_extension(file.filename)
    if not file_ext:
        raise HTTPException(status_code=400, detail="Formato no soportado")

    payload = await file.read()
    if not payload:
        raise HTTPException(status_code=400, detail="Archivo vacío")
    if len(payload) > MAX_AUDIO_FILE_BYTES:
        raise HTTPException(status_code=400, detail="Archivo demasiado grande")

    duration_seconds = detect_audio_duration_seconds(payload, filename=file.filename)
    if duration_seconds is None:
        raise HTTPException(status_code=400, detail="No se pudo leer la duración del audio")
    if duration_seconds > MAX_AUDIO_SECONDS:
        raise HTTPException(status_code=400, detail=f"El audio no puede durar más de {MAX_AUDIO_SECONDS:.0f}s")

    clip_label = normalize_audio_label(label)
    clip_emoji = normalize_audio_emoji(emoji)
    clip_color = normalize_audio_color(color)

    mime_type = file.content_type or "application/octet-stream"
    safe_file_name = (file.filename or f"audio{file_ext}").strip()[:120]

    try:
        pool = await get_pool()
        await ensure_player_exists(pool, normalized_anon_id, display_name)
        row = await upsert_player_audio_clip(
            pool,
            anon_id=normalized_anon_id,
            slot=slot,
            label=clip_label,
            emoji=clip_emoji,
            color=clip_color,
            file_name=safe_file_name,
            file_ext=file_ext,
            mime_type=mime_type,
            duration_seconds=duration_seconds,
            audio_data=payload,
        )
        await manager.notify_audio_clips_updated(room_id, normalized_anon_id)
    except Exception as exc:
        log.warning("Error guardando audio de %s: %s", normalized_anon_id, exc)
        raise HTTPException(status_code=503, detail="No se pudo guardar el audio")

    return JSONResponse({
        "ok": True,
        "clip": serialize_clip_row(row, room_id=room_id),
    })


@app.delete("/api/player/{anon_id}/audio_clips/{slot}")
async def delete_player_audio_clip_api(anon_id: str, slot: int, room_id: str):
    normalized_anon_id = normalize_anon_id(anon_id)
    if not normalized_anon_id:
        raise HTTPException(status_code=400, detail="anon_id inválido")

    room_id = normalize_room_id(room_id)
    if not manager.is_anon_present(room_id, normalized_anon_id):
        raise HTTPException(status_code=403, detail="Jugador no presente en la sala")

    if slot < 1 or slot > MAX_PLAYER_AUDIO_SLOTS:
        raise HTTPException(status_code=400, detail=f"slot debe ser 1..{MAX_PLAYER_AUDIO_SLOTS}")

    try:
        pool = await get_pool()
        deleted = await delete_player_audio_clip(pool, anon_id=normalized_anon_id, slot=slot)
        if deleted:
            await manager.notify_audio_clips_updated(room_id, normalized_anon_id)
    except Exception as exc:
        log.warning("Error borrando audio de %s: %s", normalized_anon_id, exc)
        raise HTTPException(status_code=503, detail="No se pudo borrar el audio")

    return JSONResponse({"ok": True, "deleted": deleted})


@app.get("/api/audio_clips/{clip_id}/stream")
async def stream_audio_clip_api(clip_id: int, room_id: str):
    try:
        pool = await get_pool()
        row = await fetch_audio_clip_binary(pool, clip_id)
    except Exception as exc:
        log.warning("No se pudo leer audio %s: %s", clip_id, exc)
        raise HTTPException(status_code=503, detail="No se pudo leer el audio")

    if row is None:
        raise HTTPException(status_code=404, detail="Audio no encontrado")

    room_id = normalize_room_id(room_id)
    if not manager.is_anon_present(room_id, row["anon_id"]):
        raise HTTPException(status_code=404, detail="Audio no disponible")

    return Response(content=bytes(row["audio_data"]), media_type=row["mime_type"])


# ---------------------------------------------------------------------------
# DEBUG / ADMIN (solo disponible cuando DEBUG_MODE=true)
# ---------------------------------------------------------------------------

_ADMIN_HTML: str | None = None


def _load_admin_html() -> str:
    global _ADMIN_HTML
    if _ADMIN_HTML is None:
        p = Path(__file__).resolve().parent / "static" / "admin.html"
        if p.exists():
            _ADMIN_HTML = p.read_text(encoding="utf-8")
        else:
            _ADMIN_HTML = "<h1>admin.html no encontrado</h1>"
    return _ADMIN_HTML


@app.get("/admin")
async def admin_page():
    if not DEBUG_MODE:
        return HTMLResponse("<h1>404 Not Found</h1>", status_code=404)
    return HTMLResponse(_load_admin_html())


@app.websocket("/ws/{room_id}")
async def websocket_endpoint(websocket: WebSocket, room_id: str):
    room_id = normalize_room_id(room_id)
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


@app.get("/api/player/{anon_id}")
async def get_player(anon_id: str):
    """Return persistent stats for a player identified by their anonymous ID."""
    try:
        pool = await get_pool()
    except Exception:
        return JSONResponse({"found": False, "error": "db_unavailable"}, status_code=503)
    try:
        row = await pool.fetchrow(
            """
            SELECT anon_id, display_name, xp, level,
                   games_played, games_won,
                   total_duelos, duelos_won,
                   total_calzas, calzas_hit,
                   total_pasos, pasos_bluff
            FROM players
            WHERE anon_id = $1
            """,
            anon_id,
        )
    except Exception as exc:
        log.warning("Error consultando jugador %s: %s", anon_id, exc)
        return JSONResponse({"found": False, "error": "db_error"}, status_code=503)
    if row is None:
        return JSONResponse({"found": False})
    return JSONResponse({"found": True, **dict(row)})
