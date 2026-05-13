"""
AI theme ticker universe definition.

This module is the project's "IP": the discretionary choice of which tickers
represent which sub-theme. Keeping this in code (not a config file) makes
the rationale reviewable in git history.
"""

# Sub-theme → tickers.
# Each list is meant to be PM-defendable: a clear thesis for inclusion.
AI_THEMES = {
    "gpu_camp": [
        "NVDA",   # GPU incumbent
        "AMD",    # GPU challenger
        "AVGO",   # custom ASIC + networking
    ],
    "tpu_camp": [
        "GOOGL",  # TPU host (Alphabet)
        "TSM",    # foundry for all camps
    ],
    "ai_infra": [
        "MU",     # HBM memory
        "ASML",   # EUV lithography
        "ARM",    # IP / edge AI
        "SMCI",   # AI servers
    ],
    "hyperscaler": [
        "MSFT",   # Azure / OpenAI
        "META",   # in-house silicon (MTIA)
        "AMZN",   # AWS / Trainium
    ],
    "kr_ai": [
        "005930.KS",   # Samsung Electronics — HBM, foundry
        "000660.KS",   # SK Hynix — HBM3E leader
        "042700.KS",   # Hanmi Semiconductor — TC bonder (HBM CAPEX beneficiary)
        "058470.KQ",   # Leeno Industrial — semi test sockets
    ],
}

# Macro/regime proxies — pulled with the same fetcher but used differently.
# These feed the regime classifier, not the dispersion metric.
MACRO_PROXIES = {
    "vix":      "^VIX",   # equity vol → risk-on/off
    "dxy":      "DX-Y.NYB",  # dollar strength → liquidity
    "ust10y":   "^TNX",   # 10Y yield → discount rate
    "wti":      "CL=F",   # oil → geopolitics / inflation
    "gold":     "GC=F",   # safe haven
}

# Convenience: flat list of equity tickers across all sub-themes.
def all_equity_tickers() -> list[str]:
    return [t for tickers in AI_THEMES.values() for t in tickers]


def all_macro_tickers() -> list[str]:
    return list(MACRO_PROXIES.values())


def ticker_to_theme() -> dict[str, str]:
    """Inverse map: ticker → sub-theme name. Used at DB load time."""
    out: dict[str, str] = {}
    for theme, tickers in AI_THEMES.items():
        for t in tickers:
            out[t] = theme
    return out


if __name__ == "__main__":
    print(f"Equity tickers ({len(all_equity_tickers())}):", all_equity_tickers())
    print(f"Macro tickers ({len(all_macro_tickers())}):", all_macro_tickers())
