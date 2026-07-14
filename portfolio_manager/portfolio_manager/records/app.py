"""FastAPI app for the portfolio records view."""

# No `from __future__ import annotations` here: FastAPI must resolve endpoint
# annotations at runtime, and Request/Query are imported lazily inside
# create_app, out of module scope.

from dataclasses import asdict
from datetime import date
from pathlib import Path

from .config import PortfolioRecordsSettings
from .import_service import import_dividends_text, import_trades_text
from .models import CostMethod
from .service import PortfolioRecordsService
from .sqlite_repos import SQLiteRecordsStore


def create_app(settings: PortfolioRecordsSettings | None = None):
    try:
        from fastapi import FastAPI, HTTPException, Query, Request
        from fastapi.responses import FileResponse
        from fastapi.staticfiles import StaticFiles
    except ImportError as exc:
        raise RuntimeError("Install portfolio_manager[web] to run the records API") from exc

    settings = settings or PortfolioRecordsSettings.from_env()
    store = SQLiteRecordsStore(settings)
    service = PortfolioRecordsService(store)
    static_dir = settings.static_dir or Path(__file__).resolve().parents[1] / "web"

    app = FastAPI(title="Portfolio Manager Records", version="0.1.0")
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

    @app.get("/")
    def index():
        return FileResponse(static_dir / "index.html")

    @app.get("/api/accounts")
    def list_accounts():
        return [asdict(account) for account in service.list_accounts()]

    @app.get("/api/holdings")
    def holdings(
        account_id: str | None = None,
        account_ids: list[str] | None = Query(default=None),
        exclude_accounts: bool = False,
        as_of: date | None = None,
        cost_method: CostMethod = Query(default=CostMethod.AVERAGE),
    ):
        requested_account_ids = list(account_ids or [])
        if account_id:
            requested_account_ids.append(account_id)
        requested_account_ids = list(dict.fromkeys(requested_account_ids))
        rows = service.holdings_for_accounts(
            account_ids=requested_account_ids,
            as_of=as_of,
            cost_method=cost_method,
            exclude_accounts=exclude_accounts,
        )
        return {
            "account_ids": requested_account_ids,
            "exclude_accounts": exclude_accounts,
            "as_of": as_of.isoformat() if as_of else None,
            "cost_method": cost_method,
            "rows": [asdict(row) for row in rows],
        }

    @app.get("/api/summary")
    def summary(
        base_currency: str = "USD",
        account_id: str | None = None,
        account_ids: list[str] | None = Query(default=None),
        exclude_accounts: bool = False,
        as_of: date | None = None,
        cost_method: CostMethod = Query(default=CostMethod.AVERAGE),
    ):
        requested_account_ids = list(account_ids or [])
        if account_id:
            requested_account_ids.append(account_id)
        requested_account_ids = list(dict.fromkeys(requested_account_ids))
        result = service.portfolio_summary(
            account_ids=requested_account_ids,
            base_currency=base_currency.upper(),
            as_of=as_of,
            cost_method=cost_method,
            exclude_accounts=exclude_accounts,
        )
        return asdict(result)

    @app.get("/api/reconciliation")
    def reconciliation(
        account_id: str | None = None,
        account_ids: list[str] | None = Query(default=None),
        exclude_accounts: bool = False,
        as_of: date | None = None,
    ):
        requested_account_ids = list(account_ids or [])
        if account_id:
            requested_account_ids.append(account_id)
        requested_account_ids = list(dict.fromkeys(requested_account_ids))
        issues = service.reconcile_accounts(
            account_ids=requested_account_ids,
            as_of=as_of,
            exclude_accounts=exclude_accounts,
        )
        return {
            "issues": [
                {**asdict(issue), "difference": issue.difference} for issue in issues
            ],
        }

    @app.post("/api/imports")
    async def import_trades(request: Request):
        """Import a canonical trades CSV sent as the raw request body
        (text/csv). Idempotent: re-posting the same file skips every row."""
        body = await request.body()
        try:
            text = body.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise HTTPException(status_code=400, detail="body must be UTF-8 CSV") from exc
        try:
            result = import_trades_text(text, store, source_file=request.headers.get("x-filename"))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return asdict(result)

    @app.post("/api/imports/dividends")
    async def import_dividends(request: Request):
        """Import a dividend-payments CSV sent as the raw request body
        (text/csv). Idempotent on (account_id, external_id)."""
        body = await request.body()
        try:
            text = body.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise HTTPException(status_code=400, detail="body must be UTF-8 CSV") from exc
        try:
            result = import_dividends_text(text, store, source_file=request.headers.get("x-filename"))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return asdict(result)

    return app
