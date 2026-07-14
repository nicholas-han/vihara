"""Sample SQLite data for local portfolio records demos and tests.

Money and quantity values are TEXT decimal strings, matching schema v2.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
SCHEMA_PATH = ROOT / "portfolio_manager" / "db" / "portfolio_records_schema.sql"


def create_sample_db(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()

    with sqlite3.connect(db_path) as conn:
        conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        insert_sample_data(conn)


def insert_sample_data(conn: sqlite3.Connection) -> None:
    conn.executemany(
        "insert into accounts(account_id, name, currency) values (?, ?, ?)",
        [
            ("taxable", "Taxable Brokerage", "USD"),
            ("retirement", "Retirement Account", "USD"),
            ("hk_broker", "HK Broker", "HKD"),
        ],
    )

    conn.executemany(
        """
        insert into instruments(instrument_id, symbol, name, market, currency, status)
        values (?, ?, ?, ?, ?, ?)
        """,
        [
            ("AAPL.US", "AAPL", "Apple Inc.", "US", "USD", "ACTIVE"),
            ("MSFT.US", "MSFT", "Microsoft Corp.", "US", "USD", "ACTIVE"),
            ("0700.HK", "0700", "Tencent Holdings Ltd.", "HK", "HKD", "ACTIVE"),
            ("0005.HK", "0005", "HSBC Holdings plc", "HK", "HKD", "ACTIVE"),
            ("600519.CN", "600519", "Kweichow Moutai Co., Ltd.", "CN", "CNY", "ACTIVE"),
        ],
    )

    conn.executemany(
        """
        insert into instrument_aliases(instrument_id, scheme, identifier)
        values (?, 'TICKER', ?)
        """,
        [
            ("AAPL.US", "AAPL.US"),
            ("MSFT.US", "MSFT.US"),
            ("0700.HK", "0700.HK"),
            ("0005.HK", "0005.HK"),
            ("600519.CN", "600519.CN"),
        ],
    )

    conn.executemany(
        """
        insert into trades(account_id, instrument_id, trade_date, side, quantity, price, fee, currency)
        values (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            ("taxable", "AAPL.US", "2024-01-10", "buy", "10", "175.00", "1.00", "USD"),
            ("taxable", "AAPL.US", "2024-04-15", "buy", "5", "168.00", "1.00", "USD"),
            ("taxable", "AAPL.US", "2024-09-20", "sell", "4", "228.00", "1.00", "USD"),
            ("taxable", "MSFT.US", "2024-02-12", "buy", "8", "405.00", "1.00", "USD"),
            ("hk_broker", "0700.HK", "2024-03-08", "buy", "300", "290.00", "18.00", "HKD"),
            ("hk_broker", "0700.HK", "2024-10-16", "buy", "200", "420.00", "18.00", "HKD"),
            # 0005.HK trades sit after its opening snapshot (2024-01-01).
            ("hk_broker", "0005.HK", "2024-06-12", "buy", "100", "68.00", "18.00", "HKD"),
            ("retirement", "600519.CN", "2024-05-22", "buy", "100", "1650.00", "12.00", "CNY"),
        ],
    )

    conn.executemany(
        """
        insert into position_snapshots(account_id, instrument_id, as_of, quantity, average_cost, currency, cost_method, kind)
        values (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            # Checkpoints: broker statement figures to reconcile against.
            ("taxable", "MSFT.US", "2024-12-31", "8", "405.125", "USD", "average", "checkpoint"),
            ("retirement", "600519.CN", "2024-12-31", "100", "1650.12", "CNY", "average", "checkpoint"),
            # Opening balance: history before 2024-01-01 unavailable.
            ("hk_broker", "0005.HK", "2024-01-01", "400", "60.00", "HKD", "average", "opening"),
        ],
    )

    conn.executemany(
        """
        insert into dividend_payments(account_id, instrument_id, pay_date, amount, currency, withholding_tax, external_id)
        values (?, ?, ?, ?, ?, ?, ?)
        """,
        [
            ("taxable", "AAPL.US", "2024-05-16", "3.30", "USD", "0.99", "DIV-AAPL-2024Q2"),
            ("taxable", "AAPL.US", "2024-08-15", "3.75", "USD", "1.13", "DIV-AAPL-2024Q3"),
            ("hk_broker", "0005.HK", "2024-09-26", "1240.00", "HKD", "0", "DIV-0005-2024I2"),
        ],
    )

    conn.executemany(
        """
        insert into fx_rates(base_currency, quote_currency, as_of, rate)
        values (?, ?, ?, ?)
        """,
        [
            ("HKD", "USD", "2024-12-31", "0.1287"),
            ("CNY", "USD", "2024-12-31", "0.1370"),
            ("HKD", "USD", "2025-06-30", "0.1274"),
            ("CNY", "USD", "2025-06-30", "0.1394"),
        ],
    )

    conn.executemany(
        """
        insert into dividends(instrument_id, fiscal_year, dividend_per_share, currency)
        values (?, ?, ?, ?)
        """,
        [
            ("AAPL.US", 2024, "0.99", "USD"),
            ("MSFT.US", 2024, "3.00", "USD"),
            ("0700.HK", 2024, "3.40", "HKD"),
            ("600519.CN", 2024, "30.88", "CNY"),
        ],
    )

    conn.executemany(
        """
        insert into financials(instrument_id, fiscal_year, eps, currency)
        values (?, ?, ?, ?)
        """,
        [
            ("AAPL.US", 2024, "6.08", "USD"),
            ("MSFT.US", 2024, "11.80", "USD"),
            ("0700.HK", 2024, "17.58", "HKD"),
            ("600519.CN", 2024, "59.49", "CNY"),
        ],
    )
