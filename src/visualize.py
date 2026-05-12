"""
Plotly dashboard generator.

Emits a single self-contained HTML file to docs/index.html so GitHub Pages
can serve it directly from the /docs folder.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from db import load_dispersion, load_prices_wide, load_regime

OUT_PATH = Path(__file__).resolve().parent.parent / "docs" / "index.html"

REGIME_COLORS = {
    "risk_off":    "rgba(220, 50, 50, 0.12)",
    "rate_shock":  "rgba(240, 160, 30, 0.12)",
    "goldilocks":  "rgba(60, 180, 90, 0.10)",
    "neutral":     "rgba(160, 160, 160, 0.06)",
}


def _regime_bands(fig: go.Figure, regime: pd.DataFrame, row: int) -> None:
    """Draw vertical shaded bands per regime run."""
    if regime.empty:
        return
    labels = regime["label"]
    cur = labels.iloc[0]
    start = regime.index[0]
    for i in range(1, len(regime)):
        if labels.iloc[i] != cur:
            fig.add_vrect(
                x0=start, x1=regime.index[i],
                fillcolor=REGIME_COLORS.get(cur, "rgba(0,0,0,0)"),
                line_width=0,
                row=row, col=1,
            )
            cur = labels.iloc[i]
            start = regime.index[i]
    fig.add_vrect(
        x0=start, x1=regime.index[-1],
        fillcolor=REGIME_COLORS.get(cur, "rgba(0,0,0,0)"),
        line_width=0,
        row=row, col=1,
    )


def build_figure() -> go.Figure:
    disp = load_dispersion()
    regime = load_regime()
    prices = load_prices_wide(kind="equity")

    fig = make_subplots(
        rows=3, cols=1,
        shared_xaxes=True,
        vertical_spacing=0.06,
        subplot_titles=(
            "AI theme dispersion — avg pairwise correlation (lower = more alpha)",
            "Cross-sectional return std & top-bottom spread",
            "Indexed prices (=100 at start)",
        ),
        row_heights=[0.34, 0.33, 0.33],
    )

    # Row 1: avg correlation
    if not disp.empty:
        fig.add_trace(
            go.Scatter(
                x=disp.index, y=disp["avg_corr"],
                mode="lines", name="avg_corr",
                line=dict(width=2),
            ),
            row=1, col=1,
        )
        _regime_bands(fig, regime, row=1)

    # Row 2: std + spread on dual axes (simulate by scaling)
    if not disp.empty:
        fig.add_trace(
            go.Scatter(
                x=disp.index, y=disp["return_std"],
                mode="lines", name="return_std",
            ),
            row=2, col=1,
        )
        fig.add_trace(
            go.Scatter(
                x=disp.index, y=disp["top_bottom_spread"],
                mode="lines", name="top_bottom_spread",
            ),
            row=2, col=1,
        )
        _regime_bands(fig, regime, row=2)

    # Row 3: indexed prices
    if not prices.empty:
        idx = prices.divide(prices.iloc[0]).multiply(100)
        for col in idx.columns:
            fig.add_trace(
                go.Scatter(x=idx.index, y=idx[col], mode="lines", name=col,
                           opacity=0.85),
                row=3, col=1,
            )
        _regime_bands(fig, regime, row=3)

    fig.update_layout(
        height=900,
        title="AI Theme Dispersion Monitor — with macro regime overlay",
        legend=dict(orientation="h", y=-0.08),
        template="plotly_white",
        hovermode="x unified",
    )
    return fig


def main() -> None:
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    fig = build_figure()
    fig.write_html(OUT_PATH, include_plotlyjs="cdn", full_html=True)
    print(f"[visualize] wrote {OUT_PATH}")


if __name__ == "__main__":
    main()
