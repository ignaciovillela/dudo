from __future__ import annotations

import io
import json
import math
import re
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlencode

from mutagen import File as MutagenFile

from game.config import MAX_LEVEL

ALLOWED_AUDIO_EXTENSIONS = {".wav", ".mp3", ".ogg", ".m4a", ".webm"}
# Slots totales posibles (techo absoluto, alcanzable solo en MAX_LEVEL). La cantidad
# de slots realmente desbloqueados para un jugador depende de su nivel: ver
# `max_audio_slots_for_level`. En el nivel mínimo (1) no hay ningún slot disponible.
MAX_PLAYER_AUDIO_SLOTS = 3
MAX_AUDIO_SECONDS = 7.0
MAX_AUDIO_FILE_BYTES = 3_000_000
MAX_AUDIO_LABEL_LENGTH = 28

_STATIC_DIR = Path(__file__).resolve().parents[1] / "static"
_SYSTEM_AUDIO_CLIPS_DIR = _STATIC_DIR / "audio_clips"
_SYSTEM_AUDIO_META_PATH = _SYSTEM_AUDIO_CLIPS_DIR / "buttons.json"

_HEX_COLOR_RE = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")


def _round_half_up(value: float) -> int:
    """Redondeo consistente con Math.round() de JS (mitad siempre hacia arriba),
    a diferencia del round() nativo de Python que usa banker's rounding."""
    return math.floor(value + 0.5)


def normalize_level(value: Any) -> int:
    """Normaliza un nivel reportado por el cliente a [1, MAX_LEVEL]."""
    try:
        level = int(value)
    except (TypeError, ValueError):
        return 1
    return max(1, min(level, MAX_LEVEL))


def max_audio_slots_for_level(level: int) -> int:
    """Cantidad de slots de audio desbloqueados para un nivel dado.

    Proporcional entre 0 (nivel mínimo) y MAX_PLAYER_AUDIO_SLOTS (MAX_LEVEL).
    Debe coincidir exactamente con `maxAudioSlotsForLevel` en static/app.js.
    """
    lvl = normalize_level(level)
    return _round_half_up((lvl / MAX_LEVEL) * MAX_PLAYER_AUDIO_SLOTS)


def audio_slot_unlock_level(slot: int) -> int:
    """Nivel mínimo necesario para desbloquear un slot (1..MAX_PLAYER_AUDIO_SLOTS)."""
    for lvl in range(1, MAX_LEVEL + 1):
        if max_audio_slots_for_level(lvl) >= slot:
            return lvl
    return MAX_LEVEL


def normalize_anon_id(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    anon_id = value.strip()
    if not anon_id:
        return None
    return anon_id[:120]


def normalize_audio_label(value: Any) -> str:
    if isinstance(value, str):
        label = value.strip()
        if label:
            return label[:MAX_AUDIO_LABEL_LENGTH]
    return "Audio"


def normalize_audio_emoji(value: Any) -> str:
    if isinstance(value, str):
        emoji = value.strip()
        if emoji:
            return emoji[:8]
    return "🎵"


def normalize_audio_color(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    color = value.strip()
    if not _HEX_COLOR_RE.fullmatch(color):
        return None
    return color.lower()


def infer_extension(filename: str | None) -> str | None:
    if not filename:
        return None
    suffix = Path(filename).suffix.lower()
    return suffix if suffix in ALLOWED_AUDIO_EXTENSIONS else None


def detect_audio_duration_seconds(payload: bytes, filename: str | None = None) -> float | None:
    try:
        fileobj = io.BytesIO(payload)
        fileobj.name = filename or "upload.bin"
        audio = MutagenFile(fileobj)
    except Exception:
        return None
    if audio is None or getattr(audio, "info", None) is None:
        return None
    length = getattr(audio.info, "length", None)
    if length is None:
        return None
    try:
        seconds = float(length)
    except (TypeError, ValueError):
        return None
    if seconds <= 0:
        return None
    return seconds


def _normalize_system_clip_id(raw_name: str) -> str:
    cleaned = re.sub(r"[^a-z0-9_]+", "_", raw_name.strip().lower().replace(" ", "_"))
    return cleaned.strip("_")


def _load_system_audio_overrides() -> dict[str, dict[str, str]]:
    if not _SYSTEM_AUDIO_META_PATH.exists():
        return {}
    try:
        payload = json.loads(_SYSTEM_AUDIO_META_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}

    if not isinstance(payload, dict):
        return {}

    overrides: dict[str, dict[str, str]] = {}
    for raw_id, raw_cfg in payload.items():
        if not isinstance(raw_id, str) or not isinstance(raw_cfg, dict):
            continue
        clip_id = _normalize_system_clip_id(raw_id)
        if not clip_id:
            continue

        data: dict[str, str] = {}
        label = raw_cfg.get("label")
        if isinstance(label, str) and label.strip():
            data["label"] = normalize_audio_label(label)

        emoji = raw_cfg.get("emoji")
        if isinstance(emoji, str) and emoji.strip():
            data["emoji"] = normalize_audio_emoji(emoji)

        color = normalize_audio_color(raw_cfg.get("color"))
        if color:
            data["color"] = color

        if data:
            overrides[clip_id] = data
    return overrides


def get_system_audio_clips() -> tuple[dict[str, Any], ...]:
    if not _SYSTEM_AUDIO_CLIPS_DIR.exists():
        return ()

    overrides = _load_system_audio_overrides()
    clips: list[dict[str, Any]] = []

    for path in sorted(_SYSTEM_AUDIO_CLIPS_DIR.iterdir(), key=lambda p: p.name.lower()):
        if not path.is_file():
            continue
        ext = path.suffix.lower()
        if ext not in ALLOWED_AUDIO_EXTENSIONS:
            continue

        clip_id = _normalize_system_clip_id(path.stem)
        if not clip_id:
            continue

        config = overrides.get(clip_id, {})
        label = config.get("label", normalize_audio_label(path.stem.replace("_", " ").replace("-", " ")))
        emoji = config.get("emoji", "🎵")
        color = config.get("color")
        clips.append({
            "kind": "system",
            "id": clip_id,
            "label": label,
            "emoji": emoji,
            "color": color,
            "stream_url": f"/static/audio_clips/{quote(path.name)}",
        })

    return tuple(clips)


def get_system_audio_clip_by_id(clip_id: str) -> dict[str, Any] | None:
    normalized_id = _normalize_system_clip_id(clip_id)
    if not normalized_id:
        return None
    for clip in get_system_audio_clips():
        if clip["id"] == normalized_id:
            return clip
    return None


async def ensure_player_exists(pool, anon_id: str, display_name: str = "") -> None:
    safe_name = (display_name or "").strip()[:20]
    await pool.execute(
        """
        INSERT INTO players (anon_id, display_name)
        VALUES ($1, $2)
        ON CONFLICT (anon_id) DO UPDATE SET
            display_name = CASE
                WHEN EXCLUDED.display_name <> '' THEN EXCLUDED.display_name
                ELSE players.display_name
            END,
            updated_at = NOW()
        """,
        anon_id,
        safe_name,
    )


async def upsert_player_audio_clip(
    pool,
    *,
    anon_id: str,
    slot: int,
    label: str,
    emoji: str,
    color: str | None,
    file_name: str,
    file_ext: str,
    mime_type: str,
    duration_seconds: float,
    audio_data: bytes,
):
    return await pool.fetchrow(
        """
        INSERT INTO player_audio_clips (
            anon_id, slot, label, emoji, color,
            file_name, file_ext, mime_type,
            duration_seconds, audio_data
        )
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
        ON CONFLICT (anon_id, slot) DO UPDATE SET
            label = EXCLUDED.label,
            emoji = EXCLUDED.emoji,
            color = EXCLUDED.color,
            file_name = EXCLUDED.file_name,
            file_ext = EXCLUDED.file_ext,
            mime_type = EXCLUDED.mime_type,
            duration_seconds = EXCLUDED.duration_seconds,
            audio_data = EXCLUDED.audio_data,
            updated_at = NOW()
        RETURNING id, anon_id, slot, label, emoji, color,
                  file_name, file_ext, mime_type,
                  duration_seconds, updated_at
        """,
        anon_id,
        slot,
        label,
        emoji,
        color,
        file_name,
        file_ext,
        mime_type,
        duration_seconds,
        audio_data,
    )


async def fetch_player_audio_clips(pool, anon_id: str):
    return await pool.fetch(
        """
        SELECT id, anon_id, slot, label, emoji, color,
               file_name, file_ext, mime_type,
               duration_seconds, updated_at
        FROM player_audio_clips
        WHERE anon_id = $1
        ORDER BY slot ASC
        """,
        anon_id,
    )


async def fetch_player_audio_clip_by_id(pool, clip_id: int):
    """Busca un clip de jugador solo por id (cualquiera puede disparar el audio
    de cualquier jugador presente; el dueño no tiene que ser quien lo envía)."""
    return await pool.fetchrow(
        """
        SELECT id, anon_id, slot, label, emoji, color,
               file_name, file_ext, mime_type, duration_seconds, updated_at
        FROM player_audio_clips
        WHERE id = $1
        """,
        clip_id,
    )


async def fetch_audio_clip_binary(pool, clip_id: int):
    return await pool.fetchrow(
        """
        SELECT id, anon_id, mime_type, audio_data
        FROM player_audio_clips
        WHERE id = $1
        """,
        clip_id,
    )


async def delete_player_audio_clip(pool, *, anon_id: str, slot: int) -> bool:
    """Borra el audio de un slot (deja el slot vacío). Devuelve True si borró algo."""
    result = await pool.execute(
        "DELETE FROM player_audio_clips WHERE anon_id = $1 AND slot = $2",
        anon_id,
        slot,
    )
    try:
        return int(result.split()[-1]) > 0
    except (AttributeError, ValueError, IndexError):
        return False


def _clip_cache_version(updated_at: Any) -> str:
    """Timestamp corto usado como cache-buster: cambia cuando se reemplaza el audio."""
    try:
        return str(int(updated_at.timestamp()))
    except (AttributeError, TypeError, ValueError):
        return "0"


def build_player_clip_stream_url(clip_id: int, updated_at: Any, room_id: str | None = None) -> str:
    query: dict[str, str] = {"v": _clip_cache_version(updated_at)}
    if room_id:
        query["room_id"] = room_id
    return f"/api/audio_clips/{clip_id}/stream?{urlencode(query)}"


def serialize_clip_row(row, room_id: str | None = None) -> dict[str, Any]:
    stream_url = build_player_clip_stream_url(row["id"], row["updated_at"], room_id)
    return {
        "id": row["id"],
        "slot": row["slot"],
        "label": row["label"],
        "emoji": row["emoji"] or "🎵",
        "color": row["color"],
        "duration_seconds": float(row["duration_seconds"]),
        "stream_url": stream_url,
    }
