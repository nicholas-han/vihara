#!/usr/bin/env python3
"""Generate initial market universe seed data from downloaded public files."""

from __future__ import annotations

import argparse
import csv
import json
import re
from datetime import date
from pathlib import Path

CRYPTO_BASES = ["BTC", "ETH", "SOL", "XRP", "HYPE"]
MAG7 = [
    ("AAPL", "Apple Inc."),
    ("MSFT", "Microsoft Corporation"),
    ("NVDA", "NVIDIA Corporation"),
    ("AMZN", "Amazon.com, Inc."),
    ("GOOGL", "Alphabet Inc. Class A"),
    ("META", "Meta Platforms, Inc. Class A"),
    ("TSLA", "Tesla, Inc."),
]


class Json:
    def __init__(self, value: object):
        self.value = value


def lit(value: object) -> str:
    if isinstance(value, Json):
        return "'" + json.dumps(value.value, sort_keys=True, separators=(",", ":"), default=str).replace("'", "''") + "'::jsonb"
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return "null"
    if isinstance(value, (int, float)):
        return str(value)
    return "'" + str(value).replace("'", "''") + "'"


def insert(table: str, columns: list[str], rows: list[tuple[object, ...]]) -> str:
    values = ["    (" + ", ".join(lit(v) for v in row) + ")" for row in rows]
    return f"insert into {table} ({', '.join(columns)})\nvalues\n" + ",\n".join(values) + "\non conflict do nothing;\n"


def parse_osi(osi: str) -> tuple[str, date, str, str, str]:
    match = re.search(r"^(.{1,6})\s+(\d{6})([CP])(\d{8})$", osi)
    if not match:
        raise ValueError(f"Unsupported OSI symbol: {osi!r}")
    root = match.group(1).strip()
    raw = match.group(2)
    expiry = date(2000 + int(raw[:2]), int(raw[2:4]), int(raw[4:6]))
    option_type = "CALL" if match.group(3) == "C" else "PUT"
    strike_raw = match.group(4)
    strike = f"{int(strike_raw) / 1000:.3f}".rstrip("0").rstrip(".")
    return root, expiry, option_type, strike, strike_raw


def load_spx_may_options(path: Path) -> list[dict[str, object]]:
    out = []
    with path.open(newline="") as file:
        for row in csv.DictReader(file):
            if row["Underlying"] != "SPX":
                continue
            root, expiry, option_type, strike, strike_raw = parse_osi(row["OSI Symbol"])
            if expiry.year != 2026 or expiry.month != 5:
                continue
            cp = "C" if option_type == "CALL" else "P"
            out.append({
                "instrument_id": f"CBOE_{root}_2026{expiry.month:02d}{expiry.day:02d}_{cp}_{strike_raw}",
                "root": root,
                "expiry": expiry,
                "option_type": option_type,
                "strike": strike,
                "strike_raw": strike_raw,
                "osi_symbol": row["OSI Symbol"],
                "cboe_symbol": row["Cboe Symbol"],
                "matching_unit": row["Matching Unit"],
                "closing_only": row["Closing Only"] == "True",
            })
    return sorted(out, key=lambda x: (x["expiry"], x["root"], x["strike_raw"], x["option_type"]))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cboe-all-series", required=True, type=Path)
    parser.add_argument("--okx-spot", required=True, type=Path)
    parser.add_argument("--okx-swap", required=True, type=Path)
    parser.add_argument("--binance-futures", required=True, type=Path)
    parser.add_argument("--hyperliquid-meta", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    spx_options = load_spx_may_options(args.cboe_all_series)
    okx_spot = {x["instId"] for x in json.loads(args.okx_spot.read_text())["data"]}
    okx_swap = {x["instId"] for x in json.loads(args.okx_swap.read_text())["data"]}
    binance_futures = {x["symbol"] for x in json.loads(args.binance_futures.read_text())["symbols"] if x.get("status") == "TRADING"}
    hyperliquid = {x["name"]: x for x in json.loads(args.hyperliquid_meta.read_text())["universe"]}

    sql = [
        "-- Generated initial instrument universe seed.\n",
        "-- Sources: Cboe all-series CSV, OKX instruments API, Binance futures exchangeInfo API, Hyperliquid meta API.\n",
        f"-- SPX May 2026 Cboe option instruments: {len(spx_options)}.\n\n",
    ]
    sql.append(insert("asset_classes", ["asset_class_id", "parent_asset_class_id", "name", "description", "is_assignable"], [
        ("PUBLIC_EQUITY", "EQUITY", "Public Equity", "Equity of publicly listed companies", False),
        ("COMMON_STOCK", "PUBLIC_EQUITY", "Common Stock", "Listed common equity shares", True),
        ("EQUITY_INDEX", "EQUITY", "Equity Index", "Equity index references", True),
    ]))
    assets = [
        ("USDT", "CURRENCY", "USDT", "Tether USD", "TRANSFERABLE", Json({"issuer": "Tether"})),
        ("SPX", "EQUITY_INDEX", "SPX", "S&P 500 Index", "REFERENCE", Json({"provider": "S&P Dow Jones Indices"})),
        ("SOL", "CRYPTO", "SOL", "Solana", "TRANSFERABLE", Json({})),
        ("XRP", "CRYPTO", "XRP", "XRP", "TRANSFERABLE", Json({})),
        ("HYPE", "CRYPTO", "HYPE", "Hyperliquid", "TRANSFERABLE", Json({})),
    ] + [(s, "COMMON_STOCK", s, n, "TRANSFERABLE", Json({})) for s, n in MAG7]
    sql.append(insert("assets", ["asset_id", "asset_class_id", "symbol", "name", "asset_kind", "metadata"], assets))
    sql.append(insert("instrument_types", ["instrument_type_id", "name", "description", "requires_underlying", "is_tradable_by_default"], [
        ("EQUITY", "Equity", "Listed equity security", False, True),
    ]))
    sql.append(insert("venues", ["venue_id", "name", "venue_type", "metadata"], [
        ("NASDAQ", "Nasdaq", "EXCHANGE", Json({})),
        ("CBOE_OPTIONS", "Cboe Options", "EXCHANGE", Json({"source": "https://cdn.cboe.com/data/us/options/market_statistics/symbol_reference/cone-all-series.csv"})),
        ("CME_GLOBEX", "CME Globex", "EXCHANGE", Json({})),
        ("BINANCE", "Binance", "EXCHANGE", Json({"futures_source": "https://fapi.binance.com/fapi/v1/exchangeInfo"})),
        ("OKX", "OKX", "EXCHANGE", Json({"source": "https://www.okx.com/api/v5/public/instruments"})),
    ]))

    families = [
        ("US_LISTED_COMMON_STOCKS", "EQUITY", "COMMON_STOCK", "US Listed Common Stocks", None, None, "USD", None, None, None, None, Json({})),
        ("SPX_INDEX_REFERENCES", "INDEX", "EQUITY_INDEX", "S&P 500 Index References", "SPX", None, "USD", None, None, None, None, Json({})),
        ("SPX_CASH_SETTLED_OPTIONS", "OPTION", "EQUITY_INDEX", "SPX Cash Settled Options", "SPX", None, "USD", 100, "CASH", "EUROPEAN", "Cboe listed SPX/SPXW expirations", Json({"source": "Cboe all-series CSV"})),
        ("EMINI_SP500_FUTURES", "FUTURE", "EQUITY_INDEX", "E-mini S&P 500 Futures", "SPX", None, "USD", 50, "CASH", None, "CME ES futures calendar", Json({"venue": "CME"})),
        ("EMINI_SP500_OPTIONS_ON_FUTURES", "OPTION", "EQUITY_INDEX", "E-mini S&P 500 Options on Futures", None, "EMINI_SP500_FUTURES", "USD", 50, "PHYSICAL_TO_FUTURE", "AMERICAN", "CME ES options calendar", Json({"venue": "CME", "note": "Full near-three-month option series still needs a structured CME source or bulletin parser."})),
        ("SP_SP500_FUTURES", "FUTURE", "EQUITY_INDEX", "S&P 500 Futures", "SPX", None, "USD", 250, "CASH", None, "CME SP futures calendar", Json({"venue": "CME"})),
        ("SP_SP500_OPTIONS_ON_FUTURES", "OPTION", "EQUITY_INDEX", "S&P 500 Options on Futures", None, "SP_SP500_FUTURES", "USD", 250, "PHYSICAL_TO_FUTURE", "AMERICAN", "CME SP options calendar", Json({"venue": "CME", "note": "Full near-three-month option series still needs a structured CME source or bulletin parser."})),
    ]
    for base in CRYPTO_BASES:
        families += [
            (f"{base}_USDT_SPOT", "SPOT", "CRYPTO", f"{base}/USDT Spot", base, None, "USDT", 1, "PHYSICAL", None, "{BASE}USDT", Json({})),
            (f"{base}_USD_PERPETUALS", "PERPETUAL", "CRYPTO", f"{base}-USD Perpetuals", base, None, "USDC", 1, "CASH", None, "{BASE}_USD_PERP", Json({})),
            (f"{base}_USDT_PERPETUALS", "PERPETUAL", "CRYPTO", f"{base}-USDT Perpetuals", base, None, "USDT", 1, "CASH", None, "{BASE}USDT_PERP", Json({})),
        ]
    sql.append(insert("instrument_families", ["instrument_family_id", "instrument_type_id", "asset_class_id", "name", "underlying_asset_id", "underlying_instrument_family_id", "settlement_asset_id", "contract_multiplier", "settlement_type", "exercise_style", "symbol_convention", "metadata"], families))

    instruments = [("SPX_INDEX", "SPX_INDEX_REFERENCES", "INDEX", "EQUITY_INDEX", None, "USD", "USD", "SPX", "S&P 500 Index", False, None, None, Json({}))]
    instruments += [(s, "US_LISTED_COMMON_STOCKS", "EQUITY", "COMMON_STOCK", s, None, "USD", s, n, True, None, None, Json({})) for s, n in MAG7]
    for base in CRYPTO_BASES:
        instruments += [
            (f"{base}_USDT_SPOT", f"{base}_USDT_SPOT", "SPOT", "CRYPTO", base, "USDT", None, f"{base}/USDT", f"{base}/USDT Spot", True, 1, None, Json({})),
            (f"{base}_USD_PERP", f"{base}_USD_PERPETUALS", "PERPETUAL", "CRYPTO", base, "USD", "USDC", f"{base}-USD-PERP", f"{base}-USD Perpetual", True, 1, None, Json({})),
            (f"{base}_USDT_PERP", f"{base}_USDT_PERPETUALS", "PERPETUAL", "CRYPTO", base, "USDT", "USDT", f"{base}-USDT-PERP", f"{base}-USDT Perpetual", True, 1, None, Json({})),
        ]
    for row in spx_options:
        instruments.append((row["instrument_id"], "SPX_CASH_SETTLED_OPTIONS", "OPTION", "EQUITY_INDEX", None, "USD", "USD", row["osi_symbol"].strip(), f"{row['root']} {row['expiry']} {row['option_type']} {row['strike']}", True, 100, f"{row['expiry']} 00:00:00+00", Json(row)))
    sql.append(insert("instruments", ["instrument_id", "instrument_family_id", "instrument_type_id", "asset_class_id", "base_asset_id", "quote_asset_id", "settlement_asset_id", "symbol", "name", "is_tradable", "contract_multiplier", "expiration_at", "metadata"], instruments))

    relationships = []
    for row in spx_options:
        relationships += [(row["instrument_id"], "SPX_INDEX", "UNDERLYING", None, Json({})), (row["instrument_id"], "SPX_INDEX", "DERIVATIVE_OF", None, Json({}))]
    sql.append(insert("instrument_relationships", ["from_instrument_id", "to_instrument_id", "relationship_type", "weight", "metadata"], relationships))

    venue_rows = [(f"NASDAQ_{s}", "NASDAQ", s, s, None, "ACTIVE", Json({})) for s, _ in MAG7]
    for row in spx_options:
        venue_rows.append((f"CBOE_{row['cboe_symbol']}", "CBOE_OPTIONS", row["instrument_id"], row["osi_symbol"].strip(), row["cboe_symbol"], "ACTIVE", Json({"matching_unit": row["matching_unit"], "closing_only": row["closing_only"]})))
    for base in CRYPTO_BASES:
        if f"{base}USDT" in binance_futures:
            venue_rows.append((f"BINANCE_{base}USDT_PERP", "BINANCE", f"{base}_USDT_PERP", f"{base}USDT", None, "ACTIVE", Json({"market_type": "USDT_FUTURES"})))
        venue_rows.append((f"BINANCE_{base}USDT_SPOT", "BINANCE", f"{base}_USDT_SPOT", f"{base}USDT", None, "INACTIVE" if base == "HYPE" else "ACTIVE", Json({"market_type": "SPOT", "note": "HYPE spot invalid on Binance API at generation time" if base == "HYPE" else ""})))
        if f"{base}-USDT" in okx_spot:
            venue_rows.append((f"OKX_{base}_USDT_SPOT", "OKX", f"{base}_USDT_SPOT", f"{base}-USDT", None, "ACTIVE", Json({"market_type": "SPOT"})))
        if f"{base}-USDT-SWAP" in okx_swap:
            venue_rows.append((f"OKX_{base}_USDT_SWAP", "OKX", f"{base}_USDT_PERP", f"{base}-USDT-SWAP", None, "ACTIVE", Json({"market_type": "SWAP"})))
        if base in hyperliquid:
            venue_rows.append((f"HYPERLIQUID_{base}_PERP", "HYPERLIQUID", f"{base}_USD_PERP", base, None, "ACTIVE", Json({"market_type": "PERP", **hyperliquid[base]})))
    sql.append(insert("venue_instruments", ["venue_instrument_id", "venue_id", "instrument_id", "venue_symbol", "venue_market_id", "status", "metadata"], venue_rows))

    risk_groups = [("US_EQUITY_MAG7", "Magnificent 7 Equity Exposure", "Mag7 common stocks", None, None, Json({})), ("US_EQUITY_SP500", "S&P 500 Equity Index Exposure", "SPX-linked exposure", "SPX", "SPX_INDEX", Json({}))]
    risk_groups += [(f"CRYPTO_{b}", f"{b} Exposure", f"{b}-linked exposure", b, None, Json({})) for b in CRYPTO_BASES]
    sql.append(insert("risk_underlying_groups", ["risk_underlying_group_id", "name", "description", "primary_asset_id", "primary_instrument_id", "metadata"], risk_groups))

    risk_members = [("US_EQUITY_MAG7", s, None, "COMMON_STOCK", 1, 1, Json({})) for s, _ in MAG7]
    risk_members += [("US_EQUITY_SP500", "SPX_INDEX", None, "INDEX_REFERENCE", 1, 1, Json({})), ("US_EQUITY_SP500", None, "SPX_CASH_SETTLED_OPTIONS", "OPTION_FAMILY", 1, 1, Json({})), ("US_EQUITY_SP500", None, "EMINI_SP500_FUTURES", "FUTURE_FAMILY", 1, 1, Json({})), ("US_EQUITY_SP500", None, "EMINI_SP500_OPTIONS_ON_FUTURES", "OPTION_ON_FUTURE_FAMILY", 1, 1, Json({})), ("US_EQUITY_SP500", None, "SP_SP500_FUTURES", "FUTURE_FAMILY", 1, 1, Json({})), ("US_EQUITY_SP500", None, "SP_SP500_OPTIONS_ON_FUTURES", "OPTION_ON_FUTURE_FAMILY", 1, 1, Json({}))]
    for base in CRYPTO_BASES:
        risk_members += [(f"CRYPTO_{base}", f"{base}_USDT_SPOT", None, "SPOT", 1, 1, Json({})), (f"CRYPTO_{base}", f"{base}_USD_PERP", None, "PERPETUAL", 1, 1, Json({})), (f"CRYPTO_{base}", f"{base}_USDT_PERP", None, "PERPETUAL", 1, 1, Json({}))]
    sql.append(insert("risk_underlying_group_members", ["risk_underlying_group_id", "instrument_id", "instrument_family_id", "exposure_type", "hedge_ratio", "beta", "metadata"], risk_members))

    args.output.write_text("\n".join(sql))


if __name__ == "__main__":
    main()
