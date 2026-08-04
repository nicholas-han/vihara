#!/usr/bin/env python3
"""Seed the portfolio database with holdings extracted from brokerage screenshots.

Usage:
    python seed_holdings.py [--db-path PATH]

Data sources (2026-08-04 screenshots):
  - Futu HK Margin Account (3939): US stocks, HK stocks, A-share Connect
  - SBI Securities Cash Account (2913): US stocks (NISA + 特定)
  - 东方财富 信用交易: A-shares
  - Crypto: HYPE token
"""

from __future__ import annotations

import argparse
import sqlite3
from datetime import date
from decimal import Decimal
from pathlib import Path

SCHEMA_PATH = Path(__file__).resolve().parents[1] / "db" / "portfolio_records_schema.sql"
AS_OF = date(2026, 8, 4)

# ── Accounts ────────────────────────────────────────────────────

ACCOUNTS = [
    ("futu_hk_margin_3939", "Futu HK 保证金综合账户 (3939)", "HKD"),
    ("sbi_cash_2913_nisa", "SBI 証券 現物 NISA成長 (2913)", "USD"),
    ("sbi_cash_2913_tokutei", "SBI 証券 現物 特定 (2913)", "USD"),
    ("sbi_margin_2689", "SBI 証券 信用取引口座 (2689)", "USD"),
    ("eastmoney_credit", "东方财富 信用交易", "CNY"),
]

# ── Instruments ──────────────────────────────────────────────────

INSTRUMENTS: dict[str, tuple[str, str, str, str]] = {
    # US Stocks
    "ins_googl": ("GOOGL", "Alphabet Inc. Class A", "US", "USD"),
    "ins_nvda": ("NVDA", "NVIDIA Corporation", "US", "USD"),
    "ins_futu": ("FUTU", "Futu Holdings Ltd.", "US", "USD"),
    "ins_skhy": ("SKHY", "SK Hynix Inc.", "US", "USD"),
    "ins_goog": ("GOOG", "Alphabet Inc. Class C", "US", "USD"),
    # HK Stocks
    "ins_01171": ("01171", "兗礦能源集團股份有限公司", "HK", "HKD"),
    "ins_03968": ("03968", "招商銀行股份有限公司", "HK", "HKD"),
    "ins_02318": ("02318", "中國平安保險（集團）股份有限公司", "HK", "HKD"),
    "ins_00700": ("00700", "騰訊控股有限公司", "HK", "HKD"),
    "ins_02611": ("02611", "國泰海通證券股份有限公司", "HK", "HKD"),
    "ins_00300": ("00300", "美的集團股份有限公司", "HK", "HKD"),
    "ins_02259": ("02259", "紫金礦業集團股份有限公司", "HK", "HKD"),
    "ins_00883": ("00883", "中國海洋石油有限公司", "HK", "HKD"),
    "ins_01211": ("01211", "比亞迪股份有限公司", "HK", "HKD"),
    "ins_06881": ("06881", "中國銀河證券股份有限公司", "HK", "HKD"),
    "ins_01187": ("01187", "可孚醫療科技股份有限公司", "HK", "HKD"),
    "ins_06880": ("06880", "Momenta", "HK", "HKD"),
    "ins_03378": ("03378", "翰思艾泰生物科技股份有限公司", "HK", "HKD"),
    # CN Stocks (A-share)
    "ins_600519": ("600519", "貴州茅台酒股份有限公司", "CN", "CNY"),
    "ins_000651": ("000651", "格力电器", "CN", "CNY"),
    "ins_002594": ("002594", "比亚迪", "CN", "CNY"),
    "ins_600036": ("600036", "招商银行", "CN", "CNY"),
    "ins_601019": ("601019", "山东出版", "CN", "CNY"),
    "ins_601098": ("601098", "中南传媒", "CN", "CNY"),
    "ins_601318": ("601318", "中国平安", "CN", "CNY"),
    "ins_601900": ("601900", "南方传媒", "CN", "CNY"),
    # Crypto
    "ins_hype": ("HYPE", "HYPE Token", "CRYPTO", "USD"),
}

# ── Positions (kind='opening' — representing current holdings) ───

POSITIONS = [
    # Futu HK Margin (3939) - US Stocks
    ("futu_hk_margin_3939", "ins_googl", "336", "326.336", "USD"),
    ("futu_hk_margin_3939", "ins_futu", "500", "112.35", "USD"),
    ("futu_hk_margin_3939", "ins_nvda", "55", "199.298", "USD"),
    ("futu_hk_margin_3939", "ins_skhy", "15", "146.667", "USD"),
    # Futu HK Margin (3939) - HK Stocks
    ("futu_hk_margin_3939", "ins_01171", "706700", "10.519", "HKD"),
    ("futu_hk_margin_3939", "ins_03968", "59500", "43.436", "HKD"),
    ("futu_hk_margin_3939", "ins_02318", "39000", "50.341", "HKD"),
    ("futu_hk_margin_3939", "ins_00700", "1500", "534.313", "HKD"),
    ("futu_hk_margin_3939", "ins_02611", "17000", "15.588", "HKD"),
    # 美的集团: cost not available
    ("futu_hk_margin_3939", "ins_00300", "1500", None, "HKD"),
    ("futu_hk_margin_3939", "ins_02259", "1200", "70.09", "HKD"),
    ("futu_hk_margin_3939", "ins_00883", "5000", "20.441", "HKD"),
    ("futu_hk_margin_3939", "ins_01211", "700", "107.058", "HKD"),
    ("futu_hk_margin_3939", "ins_06881", "5500", "7.97", "HKD"),
    ("futu_hk_margin_3939", "ins_01187", "500", "40.736", "HKD"),
    ("futu_hk_margin_3939", "ins_06880", "40", "293.50", "HKD"),
    ("futu_hk_margin_3939", "ins_03378", "100", "36.60", "HKD"),
    # Futu HK Margin (3939) - A-Share Connect
    ("futu_hk_margin_3939", "ins_600519", "200", "1701.27", "CNY"),
    # SBI Securities Cash NISA (2913)
    ("sbi_cash_2913_nisa", "ins_nvda", "140", "109.08", "USD"),
    # SBI Securities Cash 特定 (2913)
    ("sbi_cash_2913_tokutei", "ins_nvda", "100", "175.43", "USD"),
    ("sbi_cash_2913_tokutei", "ins_goog", "68", "201.35", "USD"),
    # 东方财富 信用交易 - A-shares
    ("eastmoney_credit", "ins_000651", "61200", "36.191", "CNY"),
    ("eastmoney_credit", "ins_002594", "600", "118.613", "CNY"),
    ("eastmoney_credit", "ins_600036", "45500", "41.568", "CNY"),
    ("eastmoney_credit", "ins_601019", "31700", "9.002", "CNY"),
    ("eastmoney_credit", "ins_601098", "24800", "11.201", "CNY"),
    ("eastmoney_credit", "ins_601318", "10000", "52.097", "CNY"),
    ("eastmoney_credit", "ins_601900", "16000", "14.473", "CNY"),
    # Crypto: HYPE — quantity and cost not tracked; price-only position
    # Skipped from position_snapshots (no quantity), tracked via market_prices only.
]

# ── Market prices ────────────────────────────────────────────────

MARKET_PRICES: dict[str, Decimal] = {
    "GOOGL": Decimal("367.609"),
    "NVDA": Decimal("208.72"),
    "FUTU": Decimal("107.25"),
    "SKHY": Decimal("147.58"),
    "GOOG": Decimal("366.911"),
    "01171": Decimal("11.58"),
    "03968": Decimal("49.46"),
    "02318": Decimal("57.85"),
    "00700": Decimal("487.60"),
    "02611": Decimal("14.54"),
    "00300": Decimal("96.95"),
    "02259": Decimal("117.10"),
    "00883": Decimal("23.58"),
    "01211": Decimal("93.45"),
    "06881": Decimal("7.66"),
    "01187": Decimal("33.30"),
    "06880": Decimal("254.20"),
    "03378": Decimal("29.00"),
    "600519": Decimal("1328.36"),
    "000651": Decimal("40.520"),
    "002594": Decimal("91.150"),
    "600036": Decimal("39.280"),
    "601019": Decimal("7.450"),
    "601098": Decimal("10.960"),
    "601318": Decimal("53.930"),
    "601900": Decimal("11.830"),
    "HYPE": Decimal("55.26"),
}

FX_RATES = [
    ("HKD", "USD", AS_OF.isoformat(), "0.1279"),
    ("CNY", "USD", AS_OF.isoformat(), "0.1375"),
    ("USD", "HKD", AS_OF.isoformat(), "7.8182"),
    ("USD", "CNY", AS_OF.isoformat(), "7.2727"),
]


def create_db(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()
    with sqlite3.connect(db_path) as conn:
        conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        _insert_all(conn)
    no_cost = sum(1 for _, _, _, cost, _ in POSITIONS if cost is None)
    print(f"✓ Database seeded: {db_path}")
    print(f"  Accounts: {len(ACCOUNTS)}")
    print(f"  Instruments: {len(INSTRUMENTS)}")
    print(f"  Positions: {len(POSITIONS)} ({no_cost} without cost basis)")
    print(f"  Market prices: {len(MARKET_PRICES)}")
    print(f"  FX rates: {len(FX_RATES)}")


def _insert_all(conn: sqlite3.Connection) -> None:
    conn.executemany(
        "insert into accounts(account_id, name, currency) values (?, ?, ?)",
        ACCOUNTS,
    )
    conn.executemany(
        "insert into instruments(instrument_id, symbol, name, market, currency, status) "
        "values (?, ?, ?, ?, ?, 'ACTIVE')",
        [(iid, sym, name, mkt, ccy) for iid, (sym, name, mkt, ccy) in INSTRUMENTS.items()],
    )
    # Positions with cost
    with_cost = [(a, i, AS_OF.isoformat(), q, c, ccy, "opening")
                 for a, i, q, c, ccy in POSITIONS if c is not None and q is not None]
    conn.executemany(
        "insert into position_snapshots(account_id, instrument_id, as_of, quantity, "
        "average_cost, currency, kind) values (?, ?, ?, ?, ?, ?, ?)",
        with_cost,
    )
    # Positions without cost (quantity only, store as opening with null cost for tracking)
    no_cost = [(a, i, AS_OF.isoformat(), q, ccy, "opening")
               for a, i, q, c, ccy in POSITIONS if c is None and q is not None]
    for acct, iid, as_of, qty, ccy, kind in no_cost:
        conn.execute(
            "insert or ignore into position_snapshots(account_id, instrument_id, as_of, "
            "quantity, average_cost, currency, kind) values (?, ?, ?, ?, '0', ?, ?)",
            (acct, iid, as_of, qty, ccy, kind),
        )

    conn.execute(
        "create table if not exists market_prices ("
        "  ticker text not null, as_of text not null, price text not null,"
        "  primary key (ticker, as_of))"
    )
    conn.executemany(
        "insert or replace into market_prices(ticker, as_of, price) values (?, ?, ?)",
        [(t, AS_OF.isoformat(), str(p)) for t, p in MARKET_PRICES.items()],
    )
    conn.executemany(
        "insert or replace into fx_rates(base_currency, quote_currency, as_of, rate) "
        "values (?, ?, ?, ?)",
        FX_RATES,
    )
    conn.commit()


def main():
    parser = argparse.ArgumentParser(description="Seed portfolio holdings database")
    parser.add_argument("--db-path", default="build/holdings_20260804.sqlite3")
    args = parser.parse_args()
    create_db(Path(args.db_path))


if __name__ == "__main__":
    main()
