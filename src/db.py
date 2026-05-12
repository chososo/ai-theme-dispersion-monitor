"""
SQLite persistence layer.

Design choices (interview talking points):
- Idempotent ingestion via INSERT OR REPLACE → daily re-runs are safe.
- Normalized into 3 tables (prices / tickers / derived metrics) so derived
  logic can be re-computed from raw without re-fetching.
- Context-managed connection: avoid leaks; transactions auto-commit/rollback.
- SQL-side JOIN for the wide-format pivot in load_prices_wide.
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

import pandas as pd

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "market.db"


SCHEMA = """
CREATE TABLE IF NOT EXISTS tickers (
    ticker TEXT PRIMARY KEY,
    theme  TEXT NOT NULL,
    kind   TEXT NOT NULL CHECK (kind IN ('equity','macro'))
);

CREATE TABLE IF NOT EXISTS prices (
    ticker TEXT NOT NULL,
    date   TEXT NOT NULL,
    close  REAL NOT NULL,
    PRIMARY KEY (ticker, date),
    FOREIGN KEY (ticker) REFERENCES tickers(ticker)
);

CREATE TABLE IF NOT EXISTS dispersion (
    date              TEXT PRIMARY KEY,
    avg_corr          REAL,
    return_std        REAL,
    top_bottom_spread REAL
);

CREATE TABLE IF NOT EXISTS regime (
    date    TEXT PRIMARY KEY,
    label   TEXT NOT NULL,
    vix     REAL,
    dxy     REAL,
    ust10y  REAL
);

CREATE INDEX IF NOT EXISTS idx_prices_date ON prices(date);
"""


@contextmanager
def connect(db_path: Path = DB_PATH) -> Iterator[sqlite3.Connection]:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(SCHEMA)
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def upsert_tickers(rows: list[tuple[str, str, str]]) -> None:
    """rows: list of (ticker, theme, kind)."""
    with connect() as conn:
        conn.executemany(
            "INSERT OR REPLACE INTO tickers(ticker, theme, kind) VALUES (?, ?, ?)",
            rows,
        )


def upsert_prices(ticker: str, df: pd.DataFrame) -> int:
    """df indexed by date with a 'close' column. Returns rows written."""
    if df.empty:
        return 0
    payload = [(ticker, str(idx.date()), float(row["close"]))
               for idx, row in df.iterrows()]
    with connect() as conn:
        conn.executemany(
            "INSERT OR REPLACE INTO prices(ticker, date, close) VALUES (?, ?, ?)",
            payload,
        )
    return len(payload)


def upsert_dispersion(df: pd.DataFrame) -> int:
    """df indexed by date with columns: avg_corr, return_std, top_bottom_spread."""
    if df.empty:
        return 0
    payload = [(str(idx.date()),
                _none_if_nan(row.get("avg_corr")),
                _none_if_nan(row.get("return_std")),
                _none_if_nan(row.get("top_bottom_spread")))
               for idx, row in df.iterrows()]
    with connect() as conn:
        conn.executemany(
            "INSERT OR REPLACE INTO dispersion VALUES (?, ?, ?, ?)",
            payload,
        )
    return len(payload)


def upsert_regime(df: pd.DataFrame) -> int:
    if df.empty:
        return 0
    payload = [(str(idx.date()),
                str(row["label"]),
                _none_if_nan(row.get("vix")),
                _none_if_nan(row.get("dxy")),
                _none_if_nan(row.get("ust10y")))
               for idx, row in df.iterrows()]
    with connect() as conn:
        conn.executemany(
            "INSERT OR REPLACE INTO regime VALUES (?, ?, ?, ?, ?)",
            payload,
        )
    return len(payload)


def get_last_date(ticker: str) -> str | None:
    with connect() as conn:
        cur = conn.execute(
            "SELECT MAX(date) FROM prices WHERE ticker = ?", (ticker,)
        )
        (val,) = cur.fetchone()
        return val


def load_prices_wide(kind: str = "equity") -> pd.DataFrame:
    """Return a date-indexed, ticker-columned price matrix.

    SQL-side JOIN filters by kind so we don't pull macro data into the
    dispersion calc by accident.
    """
    query = """
    SELECT p.date, p.ticker, p.close
    FROM prices p
    JOIN tickers t ON p.ticker = t.ticker
    WHERE t.kind = ?
    ORDER BY p.date
    """
    with connect() as conn:
        long = pd.read_sql_query(query, conn, params=(kind,))
    if long.empty:
        return pd.DataFrame()
    long["date"] = pd.to_datetime(long["date"])
    wide = long.pivot(index="date", columns="ticker", values="close")
    return wide.sort_index()


def load_dispersion() -> pd.DataFrame:
    with connect() as conn:
        df = pd.read_sql_query(
            "SELECT * FROM dispersion ORDER BY date", conn, parse_dates=["date"]
        )
    return df.set_index("date") if not df.empty else df


def load_regime() -> pd.DataFrame:
    with connect() as conn:
        df = pd.read_sql_query(
            "SELECT * FROM regime ORDER BY date", conn, parse_dates=["date"]
        )
    return df.set_index("date") if not df.empty else df


def _none_if_nan(v):
    try:
        if v is None:
            return None
        if pd.isna(v):
            return None
    except (TypeError, ValueError):
        return v
    return float(v)
