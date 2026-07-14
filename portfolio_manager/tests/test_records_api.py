from pathlib import Path

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from portfolio_manager.records.app import create_app  # noqa: E402
from portfolio_manager.records.config import PortfolioRecordsSettings  # noqa: E402
from portfolio_manager.records.sample_db import create_sample_db  # noqa: E402

TEMPLATE = Path("portfolio_manager/templates/trades_import_v1.csv")


@pytest.fixture
def client(tmp_path: Path):
    db_path = tmp_path / "records.db"
    create_sample_db(db_path)
    app = create_app(PortfolioRecordsSettings(portfolio_db_path=db_path))
    with TestClient(app) as client:
        yield client


def test_list_accounts(client):
    response = client.get("/api/accounts")

    assert response.status_code == 200
    assert [account["account_id"] for account in response.json()] == ["hk_broker", "retirement", "taxable"]


def test_holdings_endpoint(client):
    response = client.get("/api/holdings", params={"account_id": "taxable", "cost_method": "fifo"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["cost_method"] == "fifo"
    symbols = {row["symbol"] for row in payload["rows"]}
    assert symbols == {"AAPL", "MSFT"}


def test_import_endpoint_roundtrip_is_idempotent(client):
    body = TEMPLATE.read_bytes()

    first = client.post("/api/imports", content=body, headers={"x-filename": TEMPLATE.name})
    assert first.status_code == 200
    assert first.json()["inserted"] == 2

    second = client.post("/api/imports", content=body)
    assert second.status_code == 200
    assert second.json()["inserted"] == 0
    assert second.json()["skipped"] == 2


def test_import_endpoint_rejects_invalid_csv(client):
    response = client.post("/api/imports", content=b"not,a,valid,header\n1,2,3,4\n")

    assert response.status_code == 400
    assert "missing required columns" in response.json()["detail"]


def test_reconciliation_endpoint_is_clean_on_sample_data(client):
    response = client.get("/api/reconciliation")

    assert response.status_code == 200
    assert response.json()["issues"] == []


def test_reconciliation_endpoint_flags_mismatch_after_new_trades(client):
    # a new MSFT trade after the 2024-12-31 checkpoint does NOT break it,
    # so introduce a mismatch by backdating a trade before the checkpoint
    csv_body = (
        "schema_version,account_id,trade_date,symbol,market,side,quantity,price,trade_currency\n"
        "1,taxable,2024-11-01,MSFT,US,buy,2,410.00,USD\n"
    ).encode()
    assert client.post("/api/imports", content=csv_body).status_code == 200

    issues = client.get("/api/reconciliation", params={"account_id": "taxable"}).json()["issues"]

    assert len(issues) == 1
    assert issues[0]["instrument_id"] == "MSFT.US"
    assert float(issues[0]["difference"]) == 2.0


def test_summary_endpoint_returns_base_currency_totals(client):
    response = client.get("/api/summary", params={"base_currency": "usd"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["base_currency"] == "USD"
    assert payload["unconverted_currencies"] == []
    currencies = {b["currency"] for b in payload["by_currency"]}
    assert currencies == {"USD", "HKD", "CNY"}
    assert float(payload["realized_pnl_base"]) == pytest.approx(219.8)


def test_dividend_import_endpoint_is_idempotent(client):
    csv_body = (
        "schema_version,account_id,pay_date,symbol,market,amount,currency,external_id\n"
        "1,taxable,2024-11-14,AAPL,US,3.85,USD,DIV-AAPL-2024Q4\n"
    ).encode()

    first = client.post("/api/imports/dividends", content=csv_body)
    assert first.status_code == 200
    assert first.json()["inserted"] == 1

    second = client.post("/api/imports/dividends", content=csv_body)
    assert second.json()["inserted"] == 0
    assert second.json()["skipped"] == 1

    holdings = client.get("/api/holdings", params={"account_id": "taxable"}).json()["rows"]
    aapl = next(row for row in holdings if row["symbol"] == "AAPL")
    assert float(aapl["dividends_received"]) == pytest.approx(7.05 + 3.85)
