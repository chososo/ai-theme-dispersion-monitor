"""
Cross-sectional factor exposures (returns-based proxies).

Five factors, each cross-sectionally z-scored on every date so rows are
directly comparable across factors:

  momentum  : 252d return minus 21d return (12-1 momentum)
  lowvol    : -1 × 60d daily return std (higher z = more defensive)
  quality   : 252d return / 252d vol (information-ratio proxy)
  size      : -1 × log(close)  (small-cap tilt; price proxy until mkt cap added)
  reversal  : -1 × 21d return  (short-term mean reversion)

Stored long-format (date, ticker, factor, score). Last 30 dates persisted to
keep the table compact.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from db import load_prices_wide, upsert_factor_exposure

KEEP_LAST_DAYS = 30
TRADING_YEAR = 252


def _zscore_cross_section(df: pd.DataFrame) -> pd.DataFrame:
    """Z-score each row (date) across columns (tickers)."""
    mean = df.mean(axis=1)
    std = df.std(axis=1).replace(0, np.nan)
    return df.sub(mean, axis=0).div(std, axis=0)


def compute_factors(prices: pd.DataFrame) -> pd.DataFrame:
    """Returns long-format df with columns: date, ticker, factor, score."""
    if prices.shape[0] < TRADING_YEAR + 21:
        # not enough history for momentum/quality
        return pd.DataFrame(columns=["date", "ticker", "factor", "score"])

    rets = prices.pct_change()

    ret_252 = prices.pct_change(TRADING_YEAR)
    ret_21 = prices.pct_change(21)
    momentum = ret_252 - ret_21

    vol_60 = rets.rolling(60).std()
    lowvol = -vol_60

    vol_252 = rets.rolling(TRADING_YEAR).std() * np.sqrt(TRADING_YEAR)
    quality = ret_252 / vol_252.replace(0, np.nan)

    size = -np.log(prices.where(prices > 0))

    reversal = -ret_21

    raw = {
        "momentum": momentum,
        "lowvol":   lowvol,
        "quality":  quality,
        "size":     size,
        "reversal": reversal,
    }

    long_frames = []
    for name, df in raw.items():
        z = _zscore_cross_section(df).dropna(how="all")
        if z.empty:
            continue
        z = z.tail(KEEP_LAST_DAYS)
        long = z.stack().rename("score").reset_index()
        long.columns = ["date", "ticker", "score"]
        long["factor"] = name
        long_frames.append(long[["date", "ticker", "factor", "score"]])

    if not long_frames:
        return pd.DataFrame(columns=["date", "ticker", "factor", "score"])
    return pd.concat(long_frames, ignore_index=True)


def main() -> None:
    prices = load_prices_wide(kind="equity")
    if prices.empty:
        print("[factors] no prices — run fetch.py first")
        return
    long = compute_factors(prices)
    if long.empty:
        print("[factors] not enough history yet (need ≥ 273 trading days)")
        return
    n = upsert_factor_exposure(long)
    last_date = long["date"].max()
    snap = long[long["date"] == last_date].pivot(
        index="ticker", columns="factor", values="score"
    )
    print(f"[factors] wrote {n} rows  (latest date={last_date.date()})")
    print(snap.round(2))


if __name__ == "__main__":
    main()
