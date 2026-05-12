from __future__ import annotations

import os
from typing import Any
import aiosqlite


class Database:
    def __init__(self, path: str):
        self.path = path

    def connect(self):
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        return aiosqlite.connect(self.path)

    async def init(self) -> None:
        async with self.connect() as db:
            db.row_factory = aiosqlite.Row
            await db.executescript(
                """
                CREATE TABLE IF NOT EXISTS tracked_players (
                    futbin_player_id TEXT PRIMARY KEY,
                    player_name TEXT NOT NULL,
                    rating INTEGER,
                    rarity TEXT,
                    threshold_percent REAL NOT NULL DEFAULT 5,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS price_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    futbin_player_id TEXT NOT NULL,
                    player_name TEXT NOT NULL,
                    price_ps INTEGER,
                    price_xbox INTEGER,
                    price_pc INTEGER,
                    fetched_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_price_history_player_time
                ON price_history (futbin_player_id, fetched_at DESC);

                CREATE TABLE IF NOT EXISTS alerts_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    futbin_player_id TEXT NOT NULL,
                    player_name TEXT NOT NULL,
                    alert_type TEXT NOT NULL,
                    message TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS portfolio (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    futbin_player_id TEXT NOT NULL,
                    player_name TEXT NOT NULL,
                    buy_price INTEGER NOT NULL,
                    quantity INTEGER NOT NULL DEFAULT 1,
                    platform TEXT NOT NULL DEFAULT 'ps',
                    created_at TEXT NOT NULL
                );
                """
            )
            await db.commit()

    async def execute(self, query: str, params: tuple[Any, ...] = ()) -> None:
        async with self.connect() as db:
            db.row_factory = aiosqlite.Row
            await db.execute(query, params)
            await db.commit()

    async def fetchone(self, query: str, params: tuple[Any, ...] = ()) -> dict[str, Any] | None:
        async with self.connect() as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(query, params)
            row = await cursor.fetchone()
            return dict(row) if row else None

    async def fetchall(self, query: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        async with self.connect() as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(query, params)
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]
