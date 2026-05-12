from __future__ import annotations

from statistics import mean


def pct_change(current: int | None, previous: int | None) -> float:
    if not current or not previous:
        return 0.0
    return ((current - previous) / previous) * 100


def trend_label(changes: list[float]) -> str:
    if not changes:
        return "sideways"
    avg = mean(changes)
    if avg > 1.5:
        return "up"
    if avg < -1.5:
        return "down"
    return "sideways"


def evaluate_signal(current: int | None, previous: int | None, threshold_pct: float) -> dict:
    change = pct_change(current, previous)
    return {
        "change": change,
        "crossed": abs(change) >= threshold_pct,
        "buy_signal": change <= -threshold_pct,
        "sell_signal": change >= threshold_pct,
    }
