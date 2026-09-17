"""Offline ranking/pagination regressions for public funding downloads."""
import json

import pytest

from plumber.hyperliquid import tradfi_funding as funding


def metadata(coins, volumes, delisted=()):
    return [{"universe": [{"name": c, "isDelisted": c in delisted} for c in coins]},
            [{"dayNtlVlm": v} for v in volumes]]


def test_ranking_scans_all_dexs_and_excludes_crypto_delisted_unknown():
    calls = []
    responses = {
        "": metadata(["BTC"], ["9999999"]),
        "xyz": metadata(["xyz:GOLD", "xyz:TSLA", "xyz:NVDA", "xyz:NEW"],
                        ["9.1", "100", "99999", "999999"], ["xyz:NVDA"]),
        "cash": metadata(["cash:TSLA", "cash:BTC"], ["20", "999999"]),
    }
    def info(payload):
        calls.append(payload)
        if payload["type"] == "perpDexs":
            return [None, {"name": "xyz"}, {"name": "cash"}]
        return responses[payload["dex"]]
    ranked, unknown = funding.select_markets(info, top=3)
    assert [m["coin"] for m in ranked] == ["xyz:TSLA", "cash:TSLA", "xyz:GOLD"]
    assert {m["coin"] for m in unknown} == {"BTC", "cash:BTC", "xyz:NEW"}
    assert [c["dex"] for c in calls[1:]] == ["", "xyz", "cash"]


def test_explicit_classification_and_insufficient_universe():
    info = lambda _: metadata(["xyz:NEW", "xyz:GOLD"], ["50", "100"])
    ranked, _ = funding.select_markets(info, 1, ["xyz"], include=["xyz:NEW"], exclude=["xyz:GOLD"])
    assert ranked[0]["coin"] == "xyz:NEW"
    with pytest.raises(ValueError, match="Only 1"):
        funding.select_markets(info, 10, ["xyz"])


def row(t, rate="0.0000125"):
    return {"coin": "xyz:GOLD", "time": t, "fundingRate": rate, "premium": "0"}


def test_pagination_handles_short_unsorted_pages_and_deduplicates():
    pages = iter([[row(20), row(10), row(10)], [row(30, "-0.0001")], []])
    requests = []
    def info(payload):
        requests.append(payload)
        return next(pages)
    records = funding.funding_history(info, "xyz:GOLD", 10, 40)
    assert [r["time"] for r in records] == [10, 20, 30]
    assert [r["fundingRatePct"] for r in records] == ["0.0012500", "0.0012500", "-0.0100"]
    assert [p["startTime"] for p in requests] == [10, 21, 31]
    assert all(p["endTime"] == 39 and p["coin"] == "xyz:GOLD" for p in requests)


def test_bad_pagination_fails_instead_of_looping_or_silently_truncating():
    pages = iter([[row(10)], [row(10)]])
    with pytest.raises(ValueError, match="Unexpected funding record"):
        funding.funding_history(lambda _: next(pages), "xyz:GOLD", 10, 30)


def test_time_parsing_has_explicit_utc_semantics():
    assert funding.parse_time("2026-01-01") == funding.parse_time("2026-01-01T08:00:00+08:00")
    assert funding.parse_time("2026-01-01T00:00:00Z") == funding.parse_time("2026-01-01")


def test_frequency_is_protocol_hourly_and_annualization_is_simple():
    assert funding.FUNDING_INTERVAL_HOURS == 1
    assert funding.annualized_rate("0.0001") == funding.Decimal("0.876")
    details = funding.funding_frequency([0, 3_600_000, 7_200_000])
    assert details["label"] == "每小时"
    assert details["observed_interval_hours"] == 1
    assert details["same_across_assets"] is True


def test_cumulative_aggregation_groups_utc_months_and_does_not_fill_gaps():
    rows = [
        {"coin": "xyz:X", "time": funding.parse_time("2026-01-31T23:00:00Z"), "fundingRate": "0.001"},
        {"coin": "xyz:X", "time": funding.parse_time("2026-02-01T01:00:00Z"), "fundingRate": "-0.00025"},
    ]
    result = funding.aggregate_funding(rows, "month")
    assert [(r["period"], r["fundingRecords"]) for r in result] == [("2026-01", 1), ("2026-02", 1)]
    assert result[0]["cumulativeRatePct"] == "0.100"
    assert result[1]["cumulativeRatePct"] == "-0.02500"
    with pytest.raises(ValueError):
        funding.aggregate_funding(rows, "quarter")


def test_failed_coin_is_reported_with_nonzero_exit_and_other_results_saved(tmp_path, monkeypatch):
    def info(payload):
        if payload["type"] == "metaAndAssetCtxs":
            return metadata(["xyz:GOLD", "xyz:TSLA"], ["100", "50"])
        if payload["coin"] == "xyz:TSLA":
            raise RuntimeError("temporarily unavailable")
        return [row(1000)] if payload["startTime"] == 0 else []
    monkeypatch.setattr(funding, "PublicInfo", lambda: info)
    result = funding.main(["--dex", "xyz", "--top", "2", "--start", "1970-01-01",
                           "--end", "1970-01-02", "--output-dir", str(tmp_path)])
    assert result == 1
    output = json.loads((tmp_path / "tradfi_funding.json").read_text())
    assert output["errors"] == {"xyz:TSLA": "temporarily unavailable"}
    assert len(output["funding"]) == 1
    assert [m["status"] for m in output["markets"]] == ["ok", "error"]


def test_cumulative_mean_does_not_treat_missing_hours_as_zero():
    rows = [{"coin": "xyz:X", "time": funding.parse_time(t), "fundingRate": "0.0001"}
            for t in ["2026-01-01T00:00:00.010Z", "2026-01-01T02:00:00.020Z"]]
    result = funding.aggregate_funding(rows, "day")[0]
    assert result["coverageHours"] == "2"
    assert funding.Decimal(result["annualizedRatePct"]) == funding.Decimal("87.6")
    assert result["completePeriod"] is False


def test_cli_exports_new_annualization_fields(tmp_path, monkeypatch):
    import csv
    def info(payload):
        if payload["type"] == "metaAndAssetCtxs":
            return metadata(["xyz:GOLD"], ["100"])
        return [row(1000)] if payload["startTime"] == 0 else []
    monkeypatch.setattr(funding, "PublicInfo", lambda: info)
    assert funding.main(["--dex", "xyz", "--top", "1", "--start", "1970-01-01",
                         "--end", "1970-01-02", "--output-dir", str(tmp_path)]) == 0
    with (tmp_path / "tradfi_funding.csv").open() as file:
        exported = list(csv.DictReader(file))
    assert exported[0]["fundingIntervalHours"] == "1"
    assert funding.Decimal(exported[0]["annualizedRatePct"]) == funding.Decimal("10.95")
