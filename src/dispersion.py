"""
Dispersion metrics — the core insight module.

Three angles on the same phenomenon (within-theme differentiation):
  1) avg_corr           — average pairwise correlation (rolling)
  2) return_std         — cross-sectional std of daily returns
  3) top_bottom_spread  — best-minus-worst daily return

Lower correlation + higher std + wider spread ⇒ more stock-selection alpha.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from db import load_prices_wide, upsert_dispersion

ROLL_WINDOW = 21  # ≈ 1 trading month


def _avg_pairwise_corr(returns: pd.DataFrame, window: int) -> pd.Series:
    """Rolling mean of off-diagonal entries of the correlation matrix."""
    out: dict[pd.Timestamp, float] = {}
    cols = returns.columns
    n = len(cols)
    if n < 2:
        return pd.Series(dtype=float, name="avg_corr")
    for end in range(window, len(returns) + 1):
        win = returns.iloc[end - window:end]
        c = win.corr().to_numpy()
        # off-diagonal mean
        mask = ~np.eye(n, dtype=bool)
        vals = c[mask]
        out[returns.index[end - 1]] = float(np.nanmean(vals)) if vals.size else np.nan
    s = pd.Series(out, name="avg_corr")
    s.index = pd.DatetimeIndex(s.index)
    return s


def compute_dispersion(prices: pd.DataFrame, window: int = ROLL_WINDOW) -> pd.DataFrame:
    if prices.empty or prices.shape[1] < 2:
        return pd.DataFrame(columns=["avg_corr", "return_std", "top_bottom_spread"])

    rets = prices.pct_change().dropna(how="all")
    return_std = rets.std(axis=1).rename("return_std")
    spread = (rets.max(axis=1) - rets.min(axis=1)).rename("top_bottom_spread")
    avg_corr = _avg_pairwise_corr(rets, window)

    df = pd.concat([avg_corr, return_std, spread], axis=1)
    df.index.name = "date"
    return df.dropna(how="all")


def main() -> None:
    prices = load_prices_wide(kind="equity")
    if prices.empty:
        print("[dispersion] no prices found — run fetch.py (or demo_data.py) first")
        return
    disp = compute_dispersion(prices)
    n = upsert_dispersion(disp)
    print(f"[dispersion] wrote {n} rows  "
          f"(latest avg_corr={disp['avg_corr'].iloc[-1]:.3f})")


if __name__ == "__main__":
    main()
