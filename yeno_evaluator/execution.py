"""Fee-inclusive, depth-aware execution. Mirrors published House Bot fee rounding."""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable

EPS = 1e-9


@dataclass(frozen=True)
class Fill:
    shares: float
    gross: float
    fees: float


def levels(rows: Iterable, *, bids: bool) -> list[tuple[float, float]]:
    parsed = []
    for row in rows:
        try:
            p, q = float(row[0]), float(row[1])
        except (TypeError, ValueError, IndexError):
            continue
        if math.isfinite(p) and math.isfinite(q) and 0 < p < 1 and q > 0:
            parsed.append((p, q))
    return sorted(parsed, reverse=bids)


def fees(fills: list[tuple[float, float]]) -> float:
    gross = sum(p * q for p, q in fills)
    protocol = sum(.07 * q * p * (1 - p) for p, q in fills)
    return round(protocol + 1e-12, 5) + round(.01 * gross + 1e-12, 5)


def _fill(ladder: list[tuple[float, float]], qty: float, adverse: float, *, buying: bool) -> Fill:
    parts = []
    filled = 0.
    for p, available in ladder:
        take = min(available, qty - filled)
        if take > EPS:
            # Conservative synthetic adverse-price perturbation; no optimistic improvement.
            p = min(1 - EPS, p + adverse) if buying else max(EPS, p - adverse)
            parts.append((p, take))
            filled += take
        if filled >= qty - EPS:
            break
    return Fill(filled, sum(p*q for p, q in parts), fees(parts))


def buy(asks: Iterable, cash_cap: float, *, max_shares: float = math.inf, adverse: float = 0) -> Fill:
    ladder = levels(asks, bids=False)
    available = sum(q for _, q in ladder)
    bound = min(max_shares, available)
    if not ladder or bound <= EPS or cash_cap <= EPS:
        return Fill(0, 0, 0)
    low, high = 0., bound
    for _ in range(48):
        mid = (low + high)/2
        fill = _fill(ladder, mid, adverse, buying=True)
        if fill.gross + fill.fees <= cash_cap + 1e-10:
            low = mid
        else:
            high = mid
    return _fill(ladder, low, adverse, buying=True)


def sell(bids: Iterable, shares: float, *, adverse: float = 0) -> Fill:
    if shares <= EPS:
        return Fill(0, 0, 0)
    return _fill(levels(bids, bids=True), shares, adverse, buying=False)
