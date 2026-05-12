# AI Theme Dispersion Monitor

A daily monitor for **intra-AI-theme dispersion** with a macro/geopolitical
regime overlay. Built as an interpretable, PM-facing PoC.

> **Thesis.** As the AI trade matures, the headline beta compresses while
> *within-theme* dispersion widens. Catching those windows is where active
> stock-selection alpha lives. This tool turns that idea into three daily
> metrics, overlaid with a rule-based regime label.

The dashboard is published via GitHub Pages from `/docs`.

---

## What it does

Three lenses on the same phenomenon (within-AI-theme differentiation):

| Metric | Measures | Read |
|---|---|---|
| `avg_corr` (rolling avg pairwise correlation) | How much tickers move together | ↓ ⇒ more diversification benefit |
| `return_std` (cross-sectional std of daily returns) | Same-day differentiation | ↑ ⇒ more daily alpha potential |
| `top_bottom_spread` (best − worst daily return) | Magnitude of dispersion in P&L | ↑ ⇒ wider alpha capture |

Macro regime (rule-based, four labels: `risk_off`, `rate_shock`,
`goldilocks`, `neutral`) is rendered as shaded vertical bands on every chart.

---

## Architecture

```
universe.py   → IP: which tickers belong to which sub-theme
fetch.py      → yfinance ingestion, incremental + per-ticker failure-isolated
demo_data.py  → synthetic prices for offline testing (drop-in for fetch.py)
db.py         → SQLite: 3 tables (tickers / prices / derived), idempotent upserts
dispersion.py → avg_corr / return_std / top_bottom_spread
regime.py     → rule-based macro classifier
visualize.py  → single self-contained Plotly HTML → docs/index.html
```

### Why these choices

- **SQLite + INSERT OR REPLACE** → daily re-runs are safe (idempotency).
  Raw `prices` is separated from derived `dispersion` / `regime` so
  metric logic can change without re-fetching.
- **Rule-based regime, not ML** → at PoC stage interpretability comes first;
  a PM has to be able to read the rule and immediately understand *why*
  today is `risk_off`. ML is the explicit V2 path once a labeled
  validation set exists.
- **Three metrics, not one** → correlation / volatility / spread are
  three angles on the same idea. Cross-validating reduces noise.

---

## Quick start

```bash
pip install -r requirements.txt
cd src

# Option A — real data
python fetch.py

# Option B — synthetic data (no internet needed)
python demo_data.py

# Compute and render
python dispersion.py
python regime.py
python visualize.py
```

The dashboard lands at `docs/index.html`. Open it in a browser, or enable
GitHub Pages (Settings → Pages → Source: `main` branch, `/docs` folder).

---

## Roadmap (V2)

- KRX ingestion (SK Hynix, Samsung Electronics, Hanmi Semiconductor) on
  the same schema
- GPR (Geopolitical Risk Index) external feed
- Rotation backtest: momentum tilt when dispersion is high, equal-weight
  when low
- ML regime classifier once enough labeled data is collected

---

## Built with Claude Code

Pair-programmed with [Claude Code](https://claude.com/claude-code):
schema design discussion, statistical sanity-check on the dispersion
metrics, and the rule-based-vs-ML trade-off conversation.
