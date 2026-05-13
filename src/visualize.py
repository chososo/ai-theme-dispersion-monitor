"""
Multi-page Plotly dashboard generator.

Emits 3 self-contained HTML pages to docs/ with a shared top nav:
  - index.html      Overview (KPIs + dispersion + regime overlay)
  - backtest.html   Strategy NAV vs benchmark, drawdown, monthly heatmap
  - signals.html    Factor exposure heatmap + per-ticker dispersion contribution
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from db import (
    load_backtest_returns,
    load_dispersion,
    load_latest_factor_exposure,
    load_prices_wide,
    load_regime,
)

DOCS = Path(__file__).resolve().parent.parent / "docs"

REGIME_COLORS = {
    "risk_off":   "rgba(220, 50, 50, 0.12)",
    "rate_shock": "rgba(240, 160, 30, 0.12)",
    "goldilocks": "rgba(60, 180, 90, 0.10)",
    "neutral":    "rgba(160, 160, 160, 0.06)",
}

CSS = """
<style>
  *{box-sizing:border-box}
  body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
       margin:0;background:#f5f7fa;color:#1a1f2c}
  .nav{display:flex;gap:24px;padding:18px 32px;background:#fff;
       border-bottom:1px solid #e4e7ec;align-items:center;
       position:sticky;top:0;z-index:10}
  .nav .brand{font-weight:700;font-size:18px;color:#1a1f2c}
  .nav a{color:#3a4554;text-decoration:none;font-size:14px;padding:6px 0}
  .nav a:hover{color:#1f6feb}
  .nav a.active{color:#1f6feb;font-weight:600;border-bottom:2px solid #1f6feb}
  .container{max-width:1280px;margin:24px auto;padding:0 24px}
  h1{font-size:24px;margin:0 0 6px}
  .subtitle{color:#6b7280;font-size:14px;margin-bottom:24px}
  .kpi{display:grid;grid-template-columns:repeat(4,1fr);gap:16px;margin-bottom:24px}
  .kpi .card{background:#fff;padding:20px;border-radius:12px;
             box-shadow:0 1px 3px rgba(0,0,0,.06)}
  .kpi .label{font-size:11px;color:#6b7280;text-transform:uppercase;letter-spacing:.5px}
  .kpi .value{font-size:24px;font-weight:700;margin-top:6px;color:#1a1f2c}
  .kpi .sub{font-size:12px;color:#6b7280;margin-top:4px}
  .panel{background:#fff;padding:16px;border-radius:12px;
         box-shadow:0 1px 3px rgba(0,0,0,.06);margin-bottom:24px}
  .panel h2{font-size:16px;margin:0 0 12px;color:#1a1f2c}
  .footer{padding:24px;text-align:center;color:#9aa3b2;font-size:12px}
  @media (max-width:768px){.kpi{grid-template-columns:repeat(2,1fr)}}
</style>
"""


def _nav(active: str, updated: str) -> str:
    pages = [("index.html", "Overview"),
             ("backtest.html", "Backtest"),
             ("signals.html", "Signals")]
    items = "".join(
        f'<a href="{href}" class="{"active" if href == active else ""}">{label}</a>'
        for href, label in pages
    )
    return f"""
    <nav class="nav">
      <div class="brand">AI Theme Dispersion Monitor</div>
      {items}
      <span style="margin-left:auto;font-size:12px;color:#6b7280">
        Updated {updated}
      </span>
    </nav>
    """


def _kpi_cards(items: list[tuple[str, str, str]]) -> str:
    """items: list of (label, value, sub)"""
    cards = "".join(
        f'<div class="card"><div class="label">{lab}</div>'
        f'<div class="value">{val}</div>'
        f'<div class="sub">{sub}</div></div>'
        for lab, val, sub in items
    )
    return f'<div class="kpi">{cards}</div>'


def _wrap(title: str, active: str, kpi_html: str, body_html: str) -> str:
    updated = dt.date.today().isoformat()
    nav = _nav(active, updated)
    return f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title} — AI Theme Dispersion Monitor</title>
{CSS}
</head><body>
{nav}
<div class="container">
  <h1>{title}</h1>
  <div class="subtitle">Last updated {updated} · 16 equities · 4 sub-themes</div>
  {kpi_html}
  {body_html}
</div>
<div class="footer">Data via yfinance · auto-refreshed by GitHub Actions</div>
</body></html>"""


def _regime_bands(fig: go.Figure, regime: pd.DataFrame, row: int = None) -> None:
    if regime.empty:
        return
    labels = regime["label"]
    cur = labels.iloc[0]
    start = regime.index[0]
    kw = dict(line_width=0)
    if row is not None:
        kw["row"] = row
        kw["col"] = 1
    for i in range(1, len(regime)):
        if labels.iloc[i] != cur:
            fig.add_vrect(
                x0=start, x1=regime.index[i],
                fillcolor=REGIME_COLORS.get(cur, "rgba(0,0,0,0)"),
                **kw,
            )
            cur = labels.iloc[i]
            start = regime.index[i]
    fig.add_vrect(
        x0=start, x1=regime.index[-1],
        fillcolor=REGIME_COLORS.get(cur, "rgba(0,0,0,0)"),
        **kw,
    )


def _fig_html(fig: go.Figure) -> str:
    return fig.to_html(include_plotlyjs="cdn", full_html=False,
                       div_id=None, default_width="100%", default_height="500px")


# ---------- Page 1: Overview ----------

def build_overview() -> str:
    disp = load_dispersion()
    regime = load_regime()

    if disp.empty:
        kpi_html = _kpi_cards([("Status", "no data", "run the pipeline first")] * 4)
        body = '<div class="panel"><h2>No data</h2>' \
               '<p>Run <code>fetch.py → dispersion.py → regime.py</code>.</p></div>'
        return _wrap("Overview", "index.html", kpi_html, body)

    last = disp.iloc[-1]
    last_30_spread = disp["top_bottom_spread"].tail(30).mean()
    cur_regime = regime.iloc[-1]["label"] if not regime.empty else "n/a"

    kpi = _kpi_cards([
        ("Avg pairwise corr", f"{last['avg_corr']:.2f}",
         "lower → more selection alpha"),
        ("Cross-sectional std", f"{last['return_std']:.3f}",
         "daily differentiation"),
        ("30d avg spread", f"{last_30_spread:.2%}",
         "best − worst, daily"),
        ("Current regime", cur_regime,
         "rule-based macro classifier"),
    ])

    fig = make_subplots(
        rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.08,
        subplot_titles=("Average pairwise correlation (21d rolling)",
                        "Cross-sectional return std & top-bottom spread"),
        row_heights=[0.5, 0.5],
    )
    fig.add_trace(go.Scatter(x=disp.index, y=disp["avg_corr"], name="avg_corr",
                             line=dict(width=2, color="#1f6feb")), row=1, col=1)
    fig.add_trace(go.Scatter(x=disp.index, y=disp["return_std"], name="return_std",
                             line=dict(color="#10b981")), row=2, col=1)
    fig.add_trace(go.Scatter(x=disp.index, y=disp["top_bottom_spread"],
                             name="top_bottom_spread",
                             line=dict(color="#f59e0b")), row=2, col=1)
    _regime_bands(fig, regime, row=1)
    _regime_bands(fig, regime, row=2)
    fig.update_layout(height=620, template="plotly_white",
                      legend=dict(orientation="h", y=-0.12),
                      hovermode="x unified", margin=dict(t=40, l=40, r=20, b=40))

    body = f'<div class="panel"><h2>Dispersion with regime overlay</h2>{_fig_html(fig)}</div>'
    return _wrap("Overview", "index.html", kpi, body)


# ---------- Page 2: Backtest ----------

def build_backtest() -> str:
    bt = load_backtest_returns()
    if bt.empty:
        kpi_html = _kpi_cards([("Status", "no data", "run backtest.py first")] * 4)
        body = '<div class="panel"><h2>No backtest results</h2>' \
               '<p>Run <code>python backtest.py</code>.</p></div>'
        return _wrap("Backtest", "backtest.html", kpi_html, body)

    strat = bt[bt["strategy"] == "rotation"].set_index("date").sort_index()
    bench = bt[bt["strategy"] == "benchmark"].set_index("date").sort_index()

    from backtest import metrics
    m = metrics(strat["ret"])

    kpi = _kpi_cards([
        ("CAGR (strategy)", f"{m['cagr']:.2%}",
         f"vs benchmark {metrics(bench['ret'])['cagr']:.2%}"),
        ("Sharpe", f"{m['sharpe']:.2f}", "annualized, rf=0"),
        ("Max drawdown", f"{m['mdd']:.2%}", "trough vs peak"),
        ("Hit rate", f"{m['hit_rate']:.1%}", "fraction of up-days"),
    ])

    # NAV
    nav_fig = go.Figure()
    nav_fig.add_trace(go.Scatter(x=strat.index, y=strat["nav"], name="rotation",
                                 line=dict(width=2, color="#1f6feb")))
    nav_fig.add_trace(go.Scatter(x=bench.index, y=bench["nav"], name="benchmark",
                                 line=dict(width=2, color="#9ca3af")))
    nav_fig.update_layout(height=380, template="plotly_white",
                          title="NAV (start = 1.00)",
                          legend=dict(orientation="h", y=-0.15),
                          margin=dict(t=40, l=40, r=20, b=40))

    # Drawdown
    dd = strat["nav"] / strat["nav"].cummax() - 1.0
    dd_fig = go.Figure()
    dd_fig.add_trace(go.Scatter(x=dd.index, y=dd, fill="tozeroy",
                                line=dict(color="#ef4444"), name="drawdown"))
    dd_fig.update_layout(height=260, template="plotly_white",
                         title="Drawdown",
                         yaxis=dict(tickformat=".0%"),
                         margin=dict(t=40, l=40, r=20, b=40))

    # Monthly heatmap
    monthly = (1.0 + strat["ret"]).resample("ME").prod() - 1.0
    if len(monthly) > 0:
        mat = pd.DataFrame({"y": monthly.index.year, "m": monthly.index.month, "r": monthly.values})
        pivot = mat.pivot(index="y", columns="m", values="r")
        hm = go.Figure(go.Heatmap(
            z=pivot.values * 100, x=[f"{m:02d}" for m in pivot.columns],
            y=pivot.index, colorscale="RdYlGn", zmid=0,
            colorbar=dict(title="%"),
            text=[[f"{v:.1f}" if pd.notna(v) else "" for v in row] for row in pivot.values * 100],
            texttemplate="%{text}", textfont=dict(size=10),
        ))
        hm.update_layout(height=320, template="plotly_white",
                         title="Monthly returns (%)",
                         margin=dict(t=40, l=40, r=20, b=40))
        hm_html = _fig_html(hm)
    else:
        hm_html = "<p>Not enough history for monthly heatmap.</p>"

    body = (
        f'<div class="panel"><h2>NAV: rotation vs benchmark</h2>{_fig_html(nav_fig)}</div>'
        f'<div class="panel"><h2>Drawdown</h2>{_fig_html(dd_fig)}</div>'
        f'<div class="panel"><h2>Monthly returns</h2>{hm_html}</div>'
    )
    return _wrap("Backtest", "backtest.html", kpi, body)


# ---------- Page 3: Signals ----------

def build_signals() -> str:
    expo = load_latest_factor_exposure()
    prices = load_prices_wide(kind="equity")

    if expo.empty:
        kpi_html = _kpi_cards([("Status", "no data", "run factors.py first")] * 4)
        body = '<div class="panel"><h2>No signal data</h2>' \
               '<p>Run <code>python factors.py</code>.</p></div>'
        return _wrap("Signals", "signals.html", kpi_html, body)

    # KPIs: top tickers per momentum / lowvol / quality
    def _top(col: str) -> str:
        if col not in expo.columns:
            return "n/a"
        s = expo[col].dropna()
        if s.empty:
            return "n/a"
        return s.idxmax()

    kpi = _kpi_cards([
        ("Top momentum",  _top("momentum"),  "highest 12-1 z-score"),
        ("Most defensive", _top("lowvol"),   "lowest 60d vol"),
        ("Top quality",   _top("quality"),   "best return/vol"),
        ("Universe size", f"{len(expo)}",    "tickers ranked"),
    ])

    # Factor heatmap
    cols = [c for c in ["momentum", "lowvol", "quality", "size", "reversal"]
            if c in expo.columns]
    mat = expo[cols].sort_values(by=cols[0], ascending=False)
    hm = go.Figure(go.Heatmap(
        z=mat.values, x=mat.columns, y=mat.index,
        colorscale="RdBu_r", zmid=0,
        colorbar=dict(title="z-score"),
        text=[[f"{v:.2f}" if pd.notna(v) else "" for v in row] for row in mat.values],
        texttemplate="%{text}", textfont=dict(size=10),
    ))
    hm.update_layout(height=480, template="plotly_white",
                     title="Latest factor exposure (cross-sectional z-score)",
                     margin=dict(t=40, l=80, r=20, b=40))

    # Dispersion contribution: leave-one-out impact on avg pairwise correlation
    contrib_html = "<p>Need ≥ 2 tickers with recent returns for contribution.</p>"
    if not prices.empty and prices.shape[1] >= 2:
        rets = prices.pct_change().dropna(how="all").tail(60)
        rets = rets.dropna(axis=1, how="any")
        if rets.shape[1] >= 3:
            full = rets.corr()
            n = full.shape[0]
            mask = ~np.eye(n, dtype=bool)
            base = float(full.values[mask].mean())
            contribs = {}
            for t in rets.columns:
                sub = rets.drop(columns=[t]).corr().values
                m = ~np.eye(sub.shape[0], dtype=bool)
                contribs[t] = base - float(sub[m].mean())  # >0 → t raises avg corr
            ser = pd.Series(contribs).sort_values()
            cb = go.Figure(go.Bar(
                x=ser.values, y=ser.index, orientation="h",
                marker=dict(color=["#10b981" if v < 0 else "#ef4444" for v in ser.values]),
            ))
            cb.update_layout(
                height=420, template="plotly_white",
                title="Dispersion contribution (∂ avg_corr if ticker dropped, last 60d)",
                xaxis_title="Δ avg correlation",
                margin=dict(t=40, l=80, r=20, b=40),
            )
            contrib_html = _fig_html(cb)

    body = (
        f'<div class="panel"><h2>Factor exposure heatmap</h2>{_fig_html(hm)}</div>'
        f'<div class="panel"><h2>Per-ticker dispersion contribution</h2>{contrib_html}</div>'
    )
    return _wrap("Signals", "signals.html", kpi, body)


def main() -> None:
    DOCS.mkdir(parents=True, exist_ok=True)
    pages = {
        "index.html":    build_overview(),
        "backtest.html": build_backtest(),
        "signals.html":  build_signals(),
    }
    for name, html in pages.items():
        out = DOCS / name
        out.write_text(html, encoding="utf-8")
        print(f"[visualize] wrote {out}  ({len(html):,} bytes)")


if __name__ == "__main__":
    main()
