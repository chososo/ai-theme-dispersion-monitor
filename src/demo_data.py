"""
Generate synthetic prices so the whole pipeline can be tested without
internet access. Drop-in replacement for `fetch.py`.

Usage:
    python demo_data.py   # populates data/market.db with ~3 years of fake data
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from db import upsert_prices, upsert_tickers
from universe import AI_THEMES, MACRO_PROXIES

RNG = np.random.default_rng(42)

# Per-ticker annualized drift / vol to make the synthetic series look
# vaguely plausible. Not calibrated to real history.
EQUITY_PARAMS = {
    "NVDA":  (0.45, 0.45),
    "AMD":   (0.20, 0.50),
    "AVGO":  (0.35, 0.35),
    "GOOGL": (0.18, 0.30),
    "TSM":   (0.22, 0.35),
    "MU":    (0.15, 0.45),
    "ASML":  (0.20, 0.35),
    "ARM":   (0.25, 0.45),
    "SMCI":  (0.30, 0.65),
    "MSFT":  (0.20, 0.25),
    "META":  (0.25, 0.40),
    "AMZN":  (0.18, 0.30),
}

MACRO_LEVELS = {
    "^VIX":     (18.0, 0.06,  True),   # mean, daily vol, mean-revert
    "DX-Y.NYB": (103.0, 0.005, True),
    "^TNX":     (42.0, 0.01,  True),   # 4.2% × 10
    "CL=F":     (78.0, 0.02,  True),
    "GC=F":     (2000.0, 0.01, True),
}


def _gbm_path(mu: float, sigma: float, n: int, s0: float = 100.0) -> np.ndarray:
    dt = 1 / 252
    shocks = RNG.normal(loc=(mu - 0.5 * sigma ** 2) * dt,
                        scale=sigma * np.sqrt(dt), size=n)
    return s0 * np.exp(np.cumsum(shocks))


def _mean_revert(level: float, vol: float, n: int) -> np.ndarray:
    out = np.empty(n)
    x = level
    for i in range(n):
        x = x + 0.05 * (level - x) + RNG.normal(scale=level * vol)
        out[i] = max(x, 0.01)
    return out


def main() -> None:
    dates = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=750)

    # Register universe.
    rows = []
    for theme, tickers in AI_THEMES.items():
        for t in tickers:
            rows.append((t, theme, "equity"))
    for name, t in MACRO_PROXIES.items():
        rows.append((t, name, "macro"))
    upsert_tickers(rows)

    # Equities.
    total = 0
    for t in [tt for ts in AI_THEMES.values() for tt in ts]:
        mu, sigma = EQUITY_PARAMS.get(t, (0.15, 0.40))
        path = _gbm_path(mu, sigma, len(dates))
        df = pd.DataFrame({"close": path}, index=dates)
        df.index.name = "date"
        total += upsert_prices(t, df)
    print(f"[demo_data] equity rows: {total}")

    # Macros.
    total = 0
    for t, (level, vol, _mr) in MACRO_LEVELS.items():
        path = _mean_revert(level, vol, len(dates))
        df = pd.DataFrame({"close": path}, index=dates)
        df.index.name = "date"
        total += upsert_prices(t, df)
    print(f"[demo_data] macro rows: {total}")


if __name__ == "__main__":
    main()
