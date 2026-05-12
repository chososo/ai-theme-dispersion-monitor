"""
Price ingestion via yfinance.

Robustness choices:
- auto_adjust=True   → split/dividend-adjusted close
- per-ticker try/except → one bad ticker doesn't kill the batch
- incremental: only pull from get_last_date(ticker) forward
"""
from __future__ import annotations

import datetime as dt
import sys
from typing import Iterable

import pandas as pd

from db import get_last_date, upsert_prices, upsert_tickers
from universe import (
    AI_THEMES,
    MACRO_PROXIES,
    all_equity_tickers,
    all_macro_tickers,
    ticker_to_theme,
)

DEFAULT_START = "2022-01-01"


def _register_universe() -> None:
    rows: list[tuple[str, str, str]] = []
    for theme, tickers in AI_THEMES.items():
        for t in tickers:
            rows.append((t, theme, "equity"))
    for name, t in MACRO_PROXIES.items():
        rows.append((t, name, "macro"))
    upsert_tickers(rows)


def fetch_one(ticker: str, start: str) -> pd.DataFrame:
    import yfinance as yf  # imported lazily so demo_data.py runs without it
    df = yf.download(
        ticker,
        start=start,
        progress=False,
        auto_adjust=True,
        threads=False,
    )
    if df is None or df.empty:
        return pd.DataFrame()
    # yfinance sometimes returns a MultiIndex column when a single ticker is
    # passed; normalize to a flat 'close' series.
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df = df.rename(columns={"Close": "close"})[["close"]]
    df.index = pd.to_datetime(df.index)
    return df


def fetch_all(tickers: Iterable[str], default_start: str = DEFAULT_START) -> dict[str, int]:
    written: dict[str, int] = {}
    for t in tickers:
        last = get_last_date(t)
        start = (
            (dt.date.fromisoformat(last) + dt.timedelta(days=1)).isoformat()
            if last else default_start
        )
        try:
            df = fetch_one(t, start)
            n = upsert_prices(t, df)
            written[t] = n
            print(f"  {t:8s}  {n:5d} rows from {start}")
        except Exception as e:  # noqa: BLE001 — we want broad isolation here
            print(f"  {t:8s}  FAILED: {e}", file=sys.stderr)
            written[t] = -1
    return written


def main() -> None:
    print("[fetch] registering universe …")
    _register_universe()

    print("[fetch] equities …")
    fetch_all(all_equity_tickers())

    print("[fetch] macros …")
    fetch_all(all_macro_tickers())


if __name__ == "__main__":
    main()
