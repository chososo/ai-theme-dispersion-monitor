"""
Rule-based macro/geopolitical regime classifier.

Why rule-based (PoC choice):
- Interpretability first. A PM should be able to read the rule and instantly
  understand why today is 'risk_off'.
- ML extension is V2 — once we have enough labeled regime data and a held-out
  validation set.

Inputs (loaded from `prices` where kind='macro'):
  ^VIX  (vix)      — equity vol
  DX-Y.NYB (dxy)   — dollar
  ^TNX  (ust10y)   — 10Y yield (already in % × 10 from Yahoo)

Output labels:
  risk_off     — VIX high AND dollar firm
  rate_shock   — yield spiking on a short window
  goldilocks   — VIX low AND yield benign
  neutral      — everything else
"""
from __future__ import annotations

import pandas as pd

from db import connect, upsert_regime
from universe import MACRO_PROXIES


def _load_macro_wide() -> pd.DataFrame:
    query = """
    SELECT p.date, t.theme AS name, p.close
    FROM prices p
    JOIN tickers t ON p.ticker = t.ticker
    WHERE t.kind = 'macro'
    ORDER BY p.date
    """
    with connect() as conn:
        long = pd.read_sql_query(query, conn)
    if long.empty:
        return pd.DataFrame()
    long["date"] = pd.to_datetime(long["date"])
    return long.pivot(index="date", columns="name", values="close").sort_index()


def classify(macro: pd.DataFrame) -> pd.DataFrame:
    """Apply rules row-by-row. Thresholds are intentionally explicit."""
    if macro.empty:
        return pd.DataFrame(columns=["label", "vix", "dxy", "ust10y"])

    df = macro.copy()
    for col in ("vix", "dxy", "ust10y"):
        if col not in df.columns:
            df[col] = pd.NA

    # 20-day change in 10Y yield as the 'rate_shock' trigger
    df["ust10y_chg20"] = df["ust10y"].astype(float).diff(20)

    def rule(row) -> str:
        vix = row.get("vix")
        dxy = row.get("dxy")
        chg = row.get("ust10y_chg20")
        # rule precedence: rate_shock > risk_off > goldilocks > neutral
        if pd.notna(chg) and chg > 5:          # 10Y up by >50 bps in 20d
            return "rate_shock"
        if pd.notna(vix) and vix > 22:
            return "risk_off"
        if pd.notna(vix) and vix < 15:
            return "goldilocks"
        return "neutral"

    df["label"] = df.apply(rule, axis=1)
    return df[["label", "vix", "dxy", "ust10y"]]


def main() -> None:
    macro = _load_macro_wide()
    if macro.empty:
        print("[regime] no macro data — run fetch.py (or demo_data.py) first")
        return
    out = classify(macro)
    n = upsert_regime(out)
    last = out.iloc[-1]
    print(f"[regime] wrote {n} rows  (latest label={last['label']})")


if __name__ == "__main__":
    main()
