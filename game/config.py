import os


REVEAL_SECONDS = int(os.getenv("REVEAL_SECONDS", 7))
MAX_PLAYERS = int(os.getenv("MAX_PLAYERS", 6))
RATE_LIMIT_MS = int(os.getenv("RATE_LIMIT_MS", 200))
