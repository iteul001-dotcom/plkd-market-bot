from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable

from analyzer import evaluate_signal, pct_change, trend_label


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class TrackerService:
    def __init__(self, db, futbin_client, config, logger):
        self.db = db
        self.futbin = futbin_client
        self.config = config
        self.logger = logger

    async def track_player(self, query: str, threshold: float | None = None) -> dict[str, Any]:
        player = await self.futbin.search_player(query)
        ts = now_iso()
        await self.db.execute(
            """
            INSERT INTO tracked_players (futbin_player_id, player_name, rating, rarity, threshold_percent, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(futbin_player_id) DO UPDATE SET
              player_name=excluded.player_name,
              rating=excluded.rating,
              rarity=excluded.rarity,
              threshold_percent=excluded.threshold_percent,
              updated_at=excluded.updated_at
            """,
            (
                player["id"],
                player["name"],
                player["rating"],
                player["rarity"],
                threshold if threshold is not None else self.config.alert_threshold_percent,
                ts,
                ts,
            ),
        )
        return player

    async def untrack_player(self, query: str) -> dict[str, Any] | None:
        tracked = await self.db.fetchall("SELECT * FROM tracked_players ORDER BY player_name")
        found = None
        for row in tracked:
            if row["futbin_player_id"] == query or row["player_name"].lower() == query.lower():
                found = row
                break
        if not found:
            return None
        await self.db.execute("DELETE FROM tracked_players WHERE futbin_player_id=?", (found["futbin_player_id"],))
        return found

    async def get_price(self, query: str) -> dict[str, Any]:
        player = await self.futbin.search_player(query)
        prev = await self.db.fetchone(
            "SELECT * FROM price_history WHERE futbin_player_id=? ORDER BY fetched_at DESC LIMIT 1",
            (player["id"],),
        )
        prices = await self.futbin.get_prices(
            player["id"],
            {
                "ps": prev["price_ps"] if prev else None,
                "xbox": prev["price_xbox"] if prev else None,
                "pc": prev["price_pc"] if prev else None,
            },
        )
        return {"player": player, "prices": prices}

    async def get_tracked_players(self) -> list[dict[str, Any]]:
        return await self.db.fetchall("SELECT * FROM tracked_players ORDER BY player_name")

    async def get_alerts(self) -> list[dict[str, Any]]:
        return await self.db.fetchall("SELECT * FROM alerts_log ORDER BY created_at DESC LIMIT 20")

    async def get_portfolio(self) -> list[dict[str, Any]]:
        return await self.db.fetchall("SELECT * FROM portfolio ORDER BY created_at DESC")

    async def _history_since(self, player_id: str, days: int) -> list[dict[str, Any]]:
        since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        return await self.db.fetchall(
            "SELECT * FROM price_history WHERE futbin_player_id=? AND fetched_at>=? ORDER BY fetched_at DESC",
            (player_id, since),
        )

    async def build_trend(self, player_id: str, platform: str = "ps") -> dict[str, Any]:
        key = "price_ps" if platform == "ps" else "price_xbox" if platform == "xbox" else "price_pc"
        history = await self._history_since(player_id, 7)
        values = [r[key] for r in history if r[key]]
        if len(values) < 2:
            return {"trend": "sideways", "change24h": 0.0, "change7d": 0.0, "avg": values[0] if values else 0}

        latest = values[0]
        oldest = values[-1]
        day_pivot = values[min(len(values) - 1, max(1, len(values) // 3))]
        changes = [pct_change(values[i], values[i + 1]) for i in range(len(values) - 1)]
        return {
            "trend": trend_label(changes),
            "change24h": pct_change(latest, day_pivot),
            "change7d": pct_change(latest, oldest),
            "avg": int(sum(values) / len(values)),
        }

    async def top_movers(self, mover_type: str, limit: int = 10) -> list[dict[str, Any]]:
        rows = await self.db.fetchall(
            """
            WITH ranked AS (
              SELECT futbin_player_id, player_name, price_ps, fetched_at,
                     ROW_NUMBER() OVER (PARTITION BY futbin_player_id ORDER BY fetched_at DESC) rn
              FROM price_history
            )
            SELECT r1.futbin_player_id, r1.player_name, r1.price_ps AS current_price, r2.price_ps AS old_price
            FROM ranked r1
            JOIN ranked r2 ON r1.futbin_player_id = r2.futbin_player_id
            WHERE r1.rn=1 AND r2.rn=2 AND r1.price_ps IS NOT NULL AND r2.price_ps IS NOT NULL
            """
        )
        enriched = []
        for row in rows:
            row["pct"] = pct_change(row["current_price"], row["old_price"])
            enriched.append(row)

        enriched.sort(key=lambda x: x["pct"], reverse=(mover_type == "risers"))
        return enriched[:limit]

    async def run_cycle(self, notify_cb: Callable[[dict[str, Any]], Awaitable[None]], summary_cb: Callable[[str, list[str]], Awaitable[None]]) -> None:
        tracked = await self.get_tracked_players()
        if not tracked:
            return

        self.logger.info("Tracking cycle start (%s players)", len(tracked))
        fetched_at = now_iso()

        for player in tracked:
            try:
                prev = await self.db.fetchone(
                    "SELECT * FROM price_history WHERE futbin_player_id=? ORDER BY fetched_at DESC LIMIT 1",
                    (player["futbin_player_id"],),
                )
                prices = await self.futbin.get_prices(
                    player["futbin_player_id"],
                    {
                        "ps": prev["price_ps"] if prev else None,
                        "xbox": prev["price_xbox"] if prev else None,
                        "pc": prev["price_pc"] if prev else None,
                    },
                )
                await self.db.execute(
                    "INSERT INTO price_history (futbin_player_id, player_name, price_ps, price_xbox, price_pc, fetched_at) VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        player["futbin_player_id"],
                        player["player_name"],
                        prices["ps"],
                        prices["xbox"],
                        prices["pc"],
                        fetched_at,
                    ),
                )

                if not prev:
                    continue

                for platform, current_val, old_val in [
                    ("ps", prices["ps"], prev["price_ps"]),
                    ("xbox", prices["xbox"], prev["price_xbox"]),
                    ("pc", prices["pc"], prev["price_pc"]),
                ]:
                    signal = evaluate_signal(current_val, old_val, float(player["threshold_percent"]))
                    if not signal["crossed"]:
                        continue

                    alert_type = "buy" if signal["buy_signal"] else "sell" if signal["sell_signal"] else "price"
                    msg = f"{player['player_name']} {platform}: {signal['change']:.2f}%"
                    await self.db.execute(
                        "INSERT INTO alerts_log (futbin_player_id, player_name, alert_type, message, created_at) VALUES (?, ?, ?, ?, ?)",
                        (player["futbin_player_id"], player["player_name"], alert_type, msg, fetched_at),
                    )

                    await notify_cb(
                        {
                            "player_name": player["player_name"],
                            "platform": platform,
                            "current_price": current_val,
                            "previous_price": old_val,
                            "change_percent": signal["change"],
                            "signal_type": alert_type,
                            "source": prices["source"],
                        }
                    )
            except Exception as exc:  # noqa: BLE001
                self.logger.exception("Cycle error for %s: %s", player["player_name"], exc)

        risers = await self.top_movers("risers", 5)
        fallers = await self.top_movers("fallers", 5)
        if risers:
            await summary_cb("Top Risers", [f"📈 {r['player_name']}: +{r['pct']:.2f}%" for r in risers])

        crash = len(fallers) >= 3 and all(r["pct"] <= -8 for r in fallers)
        if crash:
            await summary_cb("🔥 Crash Detection", [f"📉 {r['player_name']}: {r['pct']:.2f}%" for r in fallers])
