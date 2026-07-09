import json
import os
from pathlib import Path

from dotenv import load_dotenv

_ROOT = Path(__file__).resolve().parents[1]

load_dotenv(_ROOT / ".env")

REVEAL_SECONDS = int(os.getenv("REVEAL_SECONDS", 7))
MAX_PLAYERS = int(os.getenv("MAX_PLAYERS", 6))
RATE_LIMIT_MS = int(os.getenv("RATE_LIMIT_MS", 200))
DISCONNECT_GRACE_SECONDS = int(os.getenv("DISCONNECT_GRACE_SECONDS", 300))
CHALLENGE_GUARD_MS = int(os.getenv("CHALLENGE_GUARD_MS", 500))
CHALLENGE_CONSECUTIVE_MS = int(os.getenv("CHALLENGE_CONSECUTIVE_MS", 300))

DEBUG_MODE = os.getenv("DEBUG_MODE", "false").strip().lower() == "true"

# Fuente de verdad: /static/face_names.json (compartido con el front)
_face_data = json.loads((_ROOT / "static" / "face_names.json").read_text(encoding="utf-8"))
FACE_NAMES_SINGULAR: list[str] = [f["singular"] for f in _face_data]  # índice 0 = cara 1
FACE_NAMES_PLURAL:   list[str] = [f["plural"]   for f in _face_data]


def face_name(face: int, plural: bool = False) -> str:
    """Retorna el nombre de una cara (1-6). plural=True para la forma plural."""
    names = FACE_NAMES_PLURAL if plural else FACE_NAMES_SINGULAR
    return names[face - 1] if 1 <= face <= 6 else str(face)


# Fuente de verdad: /static/levels.json (compartido con el front, static/app.js LEVEL_XP_THRESHOLDS)
# Umbrales de XP por nivel (índice 0 = nivel 1). El nivel máximo es la cantidad de umbrales.
LEVEL_XP_THRESHOLDS: list[int] = json.loads((_ROOT / "static" / "levels.json").read_text(encoding="utf-8"))
MAX_LEVEL: int = len(LEVEL_XP_THRESHOLDS)

