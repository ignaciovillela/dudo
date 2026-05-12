"""
Versioned migrations for the dudo game database.
Each migration is a tuple (version: int, sql: str).
Migrations run in order; already-applied versions are skipped.
The schema is created if it doesn't exist.
"""
from __future__ import annotations

import os

import asyncpg

_SCHEMA = os.getenv("POSTGRES_SCHEMA", "games")

# ---------------------------------------------------------------------------
# Migration definitions
# ---------------------------------------------------------------------------
MIGRATIONS: list[tuple[int, str]] = [
    (
        1,
        f"""
        -- players: one row per anonymous device
        CREATE TABLE IF NOT EXISTS {_SCHEMA}.players (
            anon_id     TEXT PRIMARY KEY,
            display_name TEXT NOT NULL DEFAULT '',
            xp          INTEGER NOT NULL DEFAULT 0,
            level       INTEGER NOT NULL DEFAULT 1,
            games_played INTEGER NOT NULL DEFAULT 0,
            games_won    INTEGER NOT NULL DEFAULT 0,
            -- cumulative counters (synced from client on first seen + updated server-side)
            total_duelos        INTEGER NOT NULL DEFAULT 0,
            duelos_won          INTEGER NOT NULL DEFAULT 0,
            total_calzas        INTEGER NOT NULL DEFAULT 0,
            calzas_hit          INTEGER NOT NULL DEFAULT 0,
            total_pasos         INTEGER NOT NULL DEFAULT 0,
            pasos_bluff         INTEGER NOT NULL DEFAULT 0,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );

        -- game_sessions: one row per completed game
        CREATE TABLE IF NOT EXISTS {_SCHEMA}.game_sessions (
            id          BIGSERIAL PRIMARY KEY,
            room_id     TEXT NOT NULL,
            started_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            ended_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            player_count INTEGER NOT NULL,
            winner_anon_id TEXT REFERENCES {_SCHEMA}.players(anon_id) ON DELETE SET NULL,
            rules       JSONB NOT NULL DEFAULT '{{}}'
        );

        -- game_participants: each player's result in a session
        CREATE TABLE IF NOT EXISTS {_SCHEMA}.game_participants (
            id              BIGSERIAL PRIMARY KEY,
            session_id      BIGINT NOT NULL REFERENCES {_SCHEMA}.game_sessions(id) ON DELETE CASCADE,
            anon_id         TEXT REFERENCES {_SCHEMA}.players(anon_id) ON DELETE SET NULL,
            display_name    TEXT NOT NULL,
            finish_position INTEGER NOT NULL,  -- 1 = winner
            is_bot          BOOLEAN NOT NULL DEFAULT FALSE,
            xp_earned       INTEGER NOT NULL DEFAULT 0
        );

        CREATE INDEX IF NOT EXISTS idx_game_participants_session
            ON {_SCHEMA}.game_participants(session_id);
        CREATE INDEX IF NOT EXISTS idx_game_participants_anon
            ON {_SCHEMA}.game_participants(anon_id);
        """,
    ),
    (
        2,
        f"""
        -- player_bid_stats: per-player bid behavior aggregated for ML training.
        -- One row per (anon_id, face, qty_bucket).
        -- qty_bucket: 1=low, 2=medium, 3=high  (relative to total dice in game).
        CREATE TABLE IF NOT EXISTS {_SCHEMA}.player_bid_stats (
            anon_id         TEXT NOT NULL REFERENCES {_SCHEMA}.players(anon_id) ON DELETE CASCADE,
            face            SMALLINT NOT NULL CHECK (face BETWEEN 1 AND 6),
            qty_bucket      SMALLINT NOT NULL CHECK (qty_bucket BETWEEN 1 AND 3),
            bids_total      INTEGER NOT NULL DEFAULT 0,
            bids_bluff      INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (anon_id, face, qty_bucket)
        );

        -- player_paso_stats: separate table for paso behavior (no face/qty dims).
        CREATE TABLE IF NOT EXISTS {_SCHEMA}.player_paso_stats (
            anon_id         TEXT PRIMARY KEY REFERENCES {_SCHEMA}.players(anon_id) ON DELETE CASCADE,
            pasos_total     INTEGER NOT NULL DEFAULT 0,
            pasos_bluff     INTEGER NOT NULL DEFAULT 0,
            paso_dice_sum   INTEGER NOT NULL DEFAULT 0  -- for avg_dice_when_paso
        );

        CREATE INDEX IF NOT EXISTS idx_player_bid_stats_anon
            ON {_SCHEMA}.player_bid_stats(anon_id);
        """,
    ),
    (
        3,
        f"""
        ALTER TABLE {_SCHEMA}.player_bid_stats
            ADD COLUMN IF NOT EXISTS bid_time_bluff_sum  FLOAT   NOT NULL DEFAULT 0,
            ADD COLUMN IF NOT EXISTS bid_time_bluff_n    INTEGER NOT NULL DEFAULT 0,
            ADD COLUMN IF NOT EXISTS bid_time_truth_sum  FLOAT   NOT NULL DEFAULT 0,
            ADD COLUMN IF NOT EXISTS bid_time_truth_n    INTEGER NOT NULL DEFAULT 0;
        """,
    ),
]


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

async def run_migrations(pool: asyncpg.Pool) -> None:
    async with pool.acquire() as conn:
        # Ensure schema exists
        await conn.execute(f"CREATE SCHEMA IF NOT EXISTS {_SCHEMA}")

        # Ensure migrations tracking table exists (in schema)
        await conn.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {_SCHEMA}.schema_migrations (
                version     INTEGER PRIMARY KEY,
                applied_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )

        applied: set[int] = {
            row["version"]
            for row in await conn.fetch(f"SELECT version FROM {_SCHEMA}.schema_migrations")
        }

        for version, sql in MIGRATIONS:
            if version in applied:
                continue
            async with conn.transaction():
                await conn.execute(sql)
                await conn.execute(
                    f"INSERT INTO {_SCHEMA}.schema_migrations (version) VALUES ($1)",
                    version,
                )
            print(f"[db] migration {version} applied")
