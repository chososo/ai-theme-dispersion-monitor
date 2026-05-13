"""
Dispersion-conditional rotation backtest.

Thesis (PM-readable rule):
- When intra-theme dispersion is HIGH (avg_corr in bottom 30th percentile of
  trailing 252d), stock-selection alpha is achievable
    → hold top N momentum names (21d return), equal weight.
- When dispersion is LOW (avg_corr in top 30th percentile),
  stock-selection alpha is hard
    → fall back to equal-weighted full universe (capture beta).
- Rebalance: month-end.
- Benchmark: equal-weighted buy & hold of full universe.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from db import (
    load_dispersion,
    load_prices_wide,
    upsert_backtest_returns,
)

TOP_N = 3
LOOKBACK_MOM = 21
DISP_PCT_LO = 0.30   # below this percentile of avg_corr → high dispersion regime
DISP_PCT_HI = 0.70


def _monthly_rebal_dates(idx: pd.DatetimeIndex) -> pd.DatetimeIndex:
    """Last trading day of each month present in the index."""
    s = pd.Series(idx, index=idx)
    last = s.groupby([idx.year, idx.month]).max()
    return pd.DatetimeIndex(last.values)


def _select_weights(
    prices_to_date: pd.DataFrame,
    dispersion_to_date: pd.Series,
) -> pd.Series:
    """Decide weights for the next holding period given info up to `t`."""
    universe = prices_to_date.columns
    if dispersion_to_date.empty or prices_to_date.shape[0] < LOOKBACK_MOM + 1:
        # warmup → equal weight
        return pd.Series(1.0 / len(universe), index=universe)

    # rolling percentile rank of current avg_corr in trailing 252d
    trail = dispersion_to_date.tail(252)
    cur = trail.iloc[-1]
    pct = (trail <= cur).mean()

    if pct <= DISP_PCT_LO:
        # high-dispersion (low correlation) → momentum
        mom = (prices_to_date.iloc[-1] / prices_to_date.iloc[-LOOKBACK_MOM - 1]) - 1
        mom = mom.dropna()
        if len(mom) < TOP_N:
            return pd.Series(1.0 / len(universe), index=universe)
        top = mom.nlargest(TOP_N).index
        w = pd.Series(0.0, index=universe)
        w[top] = 1.0 / TOP_N
        return w

    # low-dispersion (high correlation) or middle → equal weight
    valid = prices_to_date.iloc[-1].dropna().index
    if len(valid) == 0:
        return pd.Series(1.0 / len(universe), index=universe)
    w = pd.Series(0.0, index=universe)
    w[valid] = 1.0 / len(valid)
    return w


def run_backtest(prices: pd.DataFrame, dispersion: pd.DataFrame) -> pd.DataFrame:
    """Returns daily returns & NAV for strategy + benchmark."""
    if prices.empty or dispersion.empty:
        return pd.DataFrame()

    # align frequencies; forward-fill prices for occasional holiday mismatches
    prices = prices.sort_index().ffill()
    daily_rets = prices.pct_change().fillna(0.0)
    avg_corr = dispersion["avg_corr"].reindex(prices.index).ffill()

    rebal_dates = _monthly_rebal_dates(prices.index)
    # initial weights at first available date
    weights = pd.Series(1.0 / prices.shape[1], index=prices.columns)
    strat_rets: list[float] = []
    bench_rets: list[float] = []

    rebal_set = set(rebal_dates)
    for t in prices.index:
        # apply weights chosen at *previous* rebal to today's returns
        r_strat = float((weights * daily_rets.loc[t]).sum())
        r_bench = float(daily_rets.loc[t].mean())
        strat_rets.append(r_strat)
        bench_rets.append(r_bench)
        if t in rebal_set:
            # rebalance using info up to and including t
            weights = _select_weights(
                prices.loc[:t],
                avg_corr.loc[:t].dropna(),
            )

    out = pd.DataFrame({
        "date": prices.index,
        "strategy_ret": strat_rets,
        "bench_ret": bench_rets,
    }).set_index("date")
    out["strategy_nav"] = (1.0 + out["strategy_ret"]).cumprod()
    out["bench_nav"] = (1.0 + out["bench_ret"]).cumprod()
    return out


def metrics(ret: pd.Series, periods_per_year: int = 252) -> dict:
    ret = ret.dropna()
    if ret.empty:
        return {}
    cum = (1.0 + ret).prod()
    years = len(ret) / periods_per_year
    cagr = cum ** (1 / years) - 1 if years > 0 else np.nan
    vol = ret.std() * np.sqrt(periods_per_year)
    sharpe = (ret.mean() * periods_per_year) / vol if vol > 0 else np.nan
    nav = (1.0 + ret).cumprod()
    mdd = (nav / nav.cummax() - 1.0).min()
    hit = float((ret > 0).mean())
    return {
        "cagr": float(cagr),
        "vol": float(vol),
        "sharpe": float(sharpe),
        "mdd": float(mdd),
        "hit_rate": hit,
    }


def _to_long(bt: pd.DataFrame) -> pd.DataFrame:
    a = pd.DataFrame({
        "date": bt.index,
        "strategy": "rotation",
        "ret": bt["strategy_ret"].values,
        "nav": bt["strategy_nav"].values,
    })
    b = pd.DataFrame({
        "date": bt.index,
        "strategy": "benchmark",
        "ret": bt["bench_ret"].values,
        "nav": bt["bench_nav"].values,
    })
    return pd.concat([a, b], ignore_index=True)


def main() -> None:
    prices = load_prices_wide(kind="equity")
    disp = load_dispersion()
    if prices.empty or disp.empty:
        print("[backtest] missing inputs — run fetch.py and dispersion.py first")
        return
    bt = run_backtest(prices, disp)
    m_strat = metrics(bt["strategy_ret"])
    m_bench = metrics(bt["bench_ret"])
    print(f"[backtest] strategy: CAGR={m_strat['cagr']:.2%}  "
          f"Sharpe={m_strat['sharpe']:.2f}  MDD={m_strat['mdd']:.2%}  "
          f"hit={m_strat['hit_rate']:.2%}")
    print(f"[backtest] bench:    CAGR={m_bench['cagr']:.2%}  "
          f"Sharpe={m_bench['sharpe']:.2f}  MDD={m_bench['mdd']:.2%}  "
          f"hit={m_bench['hit_rate']:.2%}")
    n = upsert_backtest_returns(_to_long(bt))
    print(f"[backtest] wrote {n} rows")


if __name__ == "__main__":
    main()
