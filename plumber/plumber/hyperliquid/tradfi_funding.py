"""Public mainnet TradFi funding downloader; Python 3.11+, no SDK or keys."""
from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from statistics import median
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

API_URL = "https://api.hyperliquid.xyz/info"
FUNDING_INTERVAL_HOURS = 1
FUNDING_INTERVAL_MS = FUNDING_INTERVAL_HOURS * 60 * 60 * 1000
HOURS_PER_YEAR = 365 * 24
# Conservative underlying-symbol classification, not an official API category.
# Unknown names are reported, never automatically treated as traditional assets.
TRADFI_SYMBOLS = frozenset("""
AAOI AAPL ALUMINIUM AMAT AMD AMZN ARM ASML AVGO BABA BB BE BMNR BRENTOIL BX
CAR CIEN CIFR CL COHR COIN COPPER CORN COST CRCL CRDO CRWD CRWV CVX CXMT DELL
DKNG DRAM DXY EBAY EUR EWJ EWT EWY EWZ GBP GEV GLDMINE GLW GME GOLD GOLDJM
GOOGL GPRO HIMS HOOD HYUNDAI IBIDEN IBM IBOV IGV INTC IONQ IREN JP225 JPY
KIOXIA KORU KR200 KRW KWEB LITE LLY LRCX MAG7 MAGS MELI META MINIMAX MRNA
MRVL MSFT MSTR MU NATGAS NBIS NET NFLX NIFTY NOK NOW NVDA OIL ORCL PALLADIUM
PLATINUM PLTR QCOM RDDT RIVN RKLB RTX SEMI SEMIS SHEIN SILVER SILVERJM SKHX
SKHY SMALL2000 SMCI SMH SMSN SNDK SOFI SOFTBANK SOXL SOY SP500 SPCX STRC STX
TENCENT TER TSLA TSM TTF TTWO UNITREE URANIUM URNM USA100 USA500 US500 USBOND
USENERGY USOIL USTECH USAR VIX VST WDC WHEAT WTI XBI XIAOMI XLE XYZ100 YMTC
ZHIPU ZM 10Y GAS
""".split())


class PublicInfo:
    def __init__(self, timeout: float = 30, retries: int = 4):
        self.timeout = timeout
        self.retries = retries

    def __call__(self, payload: dict):
        request = Request(API_URL, data=json.dumps(payload).encode(),
                          headers={"Content-Type": "application/json",
                                   "User-Agent": "vihara-tradfi-funding/1.0"})
        for attempt in range(self.retries + 1):
            try:
                with urlopen(request, timeout=self.timeout) as response:
                    return json.load(response)
            except HTTPError as exc:
                if exc.code != 429 and not 500 <= exc.code < 600:
                    raise RuntimeError(f"Info API HTTP {exc.code}: {payload['type']}") from exc
                error = exc
            except (URLError, TimeoutError) as exc:
                error = exc
            if attempt == self.retries:
                raise RuntimeError(f"Info API failed after retries: {payload['type']}: {error}") from error
            time.sleep(min(2 ** attempt, 16))


def utc_iso(milliseconds: int) -> str:
    return datetime.fromtimestamp(milliseconds / 1000, timezone.utc).isoformat()


def annualized_rate(rate: Decimal | str) -> Decimal:
    """Simple annualization: one hourly rate multiplied by 8,760."""
    return Decimal(str(rate)) * HOURS_PER_YEAR


def funding_frequency(timestamps: list[int]) -> dict:
    """Describe the observed cadence while retaining the protocol rule."""
    ordered = sorted(set(timestamps))
    gaps = [b - a for a, b in zip(ordered, ordered[1:])]
    observed = round(median(gaps) / 3_600_000, 6) if gaps else None
    return {"interval_hours": FUNDING_INTERVAL_HOURS, "label": "每小时",
            "observed_interval_hours": observed,
            "same_across_assets": True,
            "source": "https://hyperliquid.gitbook.io/hyperliquid-docs/trading/funding"}


def parse_time(value: str) -> int:
    """ISO-8601; dates and naive datetimes are interpreted as UTC."""
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


def select_markets(info, top: int = 10, dexs: list[str] | None = None,
                   symbols=TRADFI_SYMBOLS, include=(), exclude=()):
    if top < 1:
        raise ValueError("top must be positive")
    if dexs is None:
        raw = info({"type": "perpDexs"})
        if not isinstance(raw, list):
            raise ValueError("Invalid perpDexs response")
        dexs = [""] + [d["name"] for d in raw if d is not None]
    markets, unclassified = [], []
    for dex in dict.fromkeys(dexs):
        raw = info({"type": "metaAndAssetCtxs", "dex": dex})
        if not isinstance(raw, list) or len(raw) != 2:
            raise ValueError(f"Invalid metadata for DEX {dex!r}")
        meta, contexts = raw
        if len(meta["universe"]) != len(contexts):
            raise ValueError(f"Metadata/context length mismatch for {dex!r}")
        for asset, context in zip(meta["universe"], contexts):
            coin = asset["name"]
            if asset.get("isDelisted") or coin in exclude:
                continue
            volume = Decimal(context["dayNtlVlm"])
            if not volume.is_finite() or volume < 0:
                raise ValueError(f"Invalid volume for {coin}")
            market = {"coin": coin, "dex": dex, "dayNtlVlm": str(volume)}
            if coin in include or coin.split(":")[-1] in symbols:
                markets.append(market)
            else:
                unclassified.append(market)
    markets.sort(key=lambda m: (-Decimal(m["dayNtlVlm"]), m["coin"]))
    unclassified.sort(key=lambda m: (-Decimal(m["dayNtlVlm"]), m["coin"]))
    if len(markets) < top:
        raise ValueError(f"Only {len(markets)} classified TradFi contracts found; requested {top}")
    return [dict(m, rank=i) for i, m in enumerate(markets[:top], 1)], unclassified


def funding_history(info, coin: str, start: int, end: int):
    """Fetch [start, end), advancing past each returned page's last timestamp."""
    if not 0 <= start < end:
        raise ValueError("Require 0 <= start < end")
    cursor, records = start, {}
    while cursor < end:
        page = info({"type": "fundingHistory", "coin": coin,
                     "startTime": cursor, "endTime": end - 1})
        if not isinstance(page, list):
            raise ValueError(f"Invalid fundingHistory response for {coin}")
        if not page:
            break
        for row in page:
            timestamp = int(row["time"])
            if row["coin"] != coin or timestamp < cursor or timestamp >= end:
                raise ValueError(f"Unexpected funding record for {coin}")
            rate = Decimal(row["fundingRate"])
            if not rate.is_finite():
                raise ValueError(f"Invalid funding rate for {coin}")
            records[timestamp] = {"coin": coin, "time": timestamp,
                                  "time_utc": utc_iso(timestamp),
                                  "fundingRate": row["fundingRate"],
                                  "fundingRatePct": str(rate * 100),
                                  "annualizedRate": str(annualized_rate(rate)),
                                  "annualizedRatePct": str(annualized_rate(rate) * 100),
                                  "fundingIntervalHours": FUNDING_INTERVAL_HOURS,
                                  "premium": row.get("premium", "")}
        # Do not assume a specific page limit or stop on a short page.
        cursor = max(int(row["time"]) for row in page) + 1
    return [records[t] for t in sorted(records)]


def aggregate_funding(rows: list[dict], frequency: str = "month") -> list[dict]:
    """Sum observed funding rates by UTC period; missing observations stay missing."""
    if frequency not in {"day", "week", "month"}:
        raise ValueError("frequency must be day, week, or month")
    buckets = defaultdict(list)
    for row in rows:
        dt = datetime.fromtimestamp(int(row["time"]) / 1000, timezone.utc)
        if frequency == "day":
            period = dt.strftime("%Y-%m-%d")
        elif frequency == "week":
            monday = dt.date() - timedelta(days=dt.weekday())
            period = monday.isoformat()
        else:
            period = dt.strftime("%Y-%m")
        buckets[(row["coin"], period)].append(row)
    result = []
    for (coin, period), records in sorted(buckets.items(), key=lambda item: (item[0][1], item[0][0])):
        total = sum((Decimal(str(row["fundingRate"])) for row in records), Decimal(0))
        first, last = min(row["time"] for row in records), max(row["time"] for row in records)
        # A missing observation is not a zero-rate hour. Annualize only the sample mean.
        observed_hours = len(records) * FUNDING_INTERVAL_HOURS
        start_dt = datetime.fromisoformat(period + ("-01" if frequency == "month" else "")).replace(tzinfo=timezone.utc)
        if frequency == "month":
            end_dt = start_dt.replace(year=start_dt.year + 1, month=1) if start_dt.month == 12 else start_dt.replace(month=start_dt.month + 1)
        else:
            end_dt = start_dt + timedelta(days=7 if frequency == "week" else 1)
        full_hours = int((end_dt - start_dt).total_seconds() / 3600)
        slots = {int(row["time"]) // FUNDING_INTERVAL_MS for row in records}
        if len(slots) != len(records):
            raise ValueError(f"Duplicate hourly funding records for {coin}")
        result.append({"coin": coin, "period": period, "frequency": frequency,
                       "fundingRecords": len(records), "firstTime": first, "lastTime": last,
                       "cumulativeRate": str(total), "cumulativeRatePct": str(total * 100),
                       "annualizedRate": str(total / observed_hours * HOURS_PER_YEAR),
                       "annualizedRatePct": str(total / observed_hours * HOURS_PER_YEAR * 100),
                       "coverageHours": str(observed_hours), "fullPeriodHours": full_hours,
                       "completePeriod": len(slots) == full_hours})
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--top", type=int, default=10)
    parser.add_argument("--days", type=int, default=30, help="Lookback from end; default 30")
    parser.add_argument("--start", help="Inclusive ISO date/time (default end minus days)")
    parser.add_argument("--end", help="Exclusive ISO date/time (default now); naive times use UTC")
    parser.add_argument("--dex", action="append", help="Restrict DEX; repeatable, default all")
    parser.add_argument("--include", action="append", default=[], help="Additional full coin, e.g. xyz:NEW")
    parser.add_argument("--exclude", action="append", default=[], help="Exclude full coin")
    parser.add_argument("--output-dir", type=Path, default=Path("/tmp/hyperliquid-tradfi-funding"))
    args = parser.parse_args(argv)
    try:
        if args.days <= 0 or args.top <= 0:
            raise ValueError("--days and --top must be positive")
        end = parse_time(args.end) if args.end else int(time.time() * 1000)
        start = parse_time(args.start) if args.start else end - int(timedelta(days=args.days).total_seconds() * 1000)
        if not 0 <= start < end:
            raise ValueError("Require 0 <= start < end")
        info = PublicInfo()
        snapshot_start = utc_iso(int(time.time() * 1000))
        markets, unclassified = select_markets(info, args.top, args.dex,
                                               include=args.include, exclude=args.exclude)
        snapshot_end = utc_iso(int(time.time() * 1000))
        rows, errors = [], {}
        for market in markets:
            coin = market["coin"]
            print(f"{market['rank']:2d}. {coin:20s} 24h volume={market['dayNtlVlm']}", file=sys.stderr)
            try:
                history = funding_history(info, coin, start, end)
                market["funding_records"] = len(history)
                market["status"] = "ok" if history else "empty"
                market["funding_frequency"] = funding_frequency([row["time"] for row in history])
                rows.extend(dict(row, rank=market["rank"], dayNtlVlm=market["dayNtlVlm"]) for row in history)
                if not history:
                    print(f"Warning: no funding records for {coin} in requested interval", file=sys.stderr)
            except (ValueError, KeyError, TypeError, RuntimeError) as exc:
                market["status"] = "error"
                errors[coin] = str(exc)
        result = {"ranking": "current rolling 24h dayNtlVlm, per contract (not per underlying)",
                  "classification": "conservative symbol allowlist plus explicit includes; not official or exhaustive",
                  "funding_spec": {"interval_hours": FUNDING_INTERVAL_HOURS, "label": "每小时",
                                   "same_across_assets": True,
                                   "annualization": "simple hourly rate multiplied by 8,760",
                                   "cumulative": "sum of observed records; missing observations are not filled with zero"},
                  "snapshot_start_utc": snapshot_start, "snapshot_end_utc": snapshot_end,
                  "start_utc_inclusive": utc_iso(start), "end_utc_exclusive": utc_iso(end),
                  "include": args.include, "exclude": args.exclude,
                  "markets": markets, "unclassified": unclassified, "errors": errors,
                  "funding": rows, "cumulative": aggregate_funding(rows, "month")}
        args.output_dir.mkdir(parents=True, exist_ok=True)
        json_path = args.output_dir / "tradfi_funding.json"
        json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        csv_path = args.output_dir / "tradfi_funding.csv"
        with csv_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=["rank", "coin", "dayNtlVlm", "time", "time_utc",
                                                        "fundingRate", "fundingRatePct", "fundingIntervalHours",
                                                        "annualizedRate", "annualizedRatePct", "premium"])
            writer.writeheader()
            writer.writerows(rows)
        print(f"Saved {len(rows)} records: {csv_path.resolve()} and {json_path.resolve()}")
        if errors:
            print(f"Incomplete download: {json.dumps(errors)}", file=sys.stderr)
            return 1
        return 0
    except (ValueError, KeyError, TypeError, RuntimeError, OSError, OverflowError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
