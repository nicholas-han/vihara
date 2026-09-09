"""Local Holdings API; canonical writes pass through atomic application commands."""

from dataclasses import asdict
from datetime import date
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, StrictStr

from instrument_manager.holding_catalog import HoldingCatalog, CatalogError
from .config import Settings
from ledger.investment.errors import LedgerError
from ledger.investment.persistence.store import Store
from ledger.investment.application.service import Service
from .analysis import HoldingsService


class ScopeInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scope_code: StrictStr
    display_name: StrictStr
    tax_scheme_id: StrictStr | None = None


class AccountInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    account_code: StrictStr
    display_name: StrictStr
    institution_type: Literal["BANK", "BROKER-DEALER", "INSURER"]
    country_or_region: StrictStr | None = None
    position_scopes: list[ScopeInput] | None = None
    external_account_numbers: list[StrictStr] = []


class ImportInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    filename: StrictStr
    csv_text: StrictStr


class ImportMapping(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mapping: dict[str, StrictStr]


class ReversalInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_key: StrictStr
    memo: StrictStr | None = None


class FeeInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    fee_type: StrictStr
    amount: StrictStr


class TradeInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    effective_date: StrictStr
    account_id: StrictStr
    position_scope_id: StrictStr
    product_id: StrictStr
    listing_id: StrictStr | None = None
    side: StrictStr
    quantity: StrictStr
    price: StrictStr
    trade_date: StrictStr | None = None
    trade_time: StrictStr | None = None
    scheduled_settlement_date: StrictStr | None = None
    fees: list[FeeInput] = []
    memo: StrictStr | None = None
    request_key: StrictStr


class FXInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    effective_date: StrictStr
    account_id: StrictStr
    sell_currency: StrictStr
    sell_amount: StrictStr
    buy_currency: StrictStr
    buy_amount: StrictStr
    memo: StrictStr | None = None
    request_key: StrictStr


class DividendInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    effective_date: StrictStr
    account_id: StrictStr
    observable_id: StrictStr
    currency: StrictStr
    amount: StrictStr
    memo: StrictStr | None = None
    request_key: StrictStr


class CashInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    effective_date: StrictStr
    currency: StrictStr
    amount: StrictStr
    source_account_id: StrictStr | None = None
    destination_account_id: StrictStr | None = None
    memo: StrictStr | None = None
    request_key: StrictStr


def create_app(settings: Settings | None = None):
    settings = settings or Settings.from_env()
    catalog = HoldingCatalog(settings.instruments_dir)
    store = Store(settings.db_path, catalog)
    store.configuration()  # Never silently initialize, replace or seed a running database.
    service = Service(store)
    analysis = HoldingsService(store)
    app = FastAPI(title="Portfolio Holdings", version="0.1.0")
    static_dir = Path(__file__).with_name("web")
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

    @app.exception_handler(LedgerError)
    async def domain_error(request: Request, exc: LedgerError):
        status = (
            500
            if exc.code == "INTEGRITY_ERROR"
            else 404 if exc.code == "REFERENCE_NOT_FOUND" else 422
        )
        if exc.code in (
            "INSUFFICIENT_CASH",
            "INSUFFICIENT_POSITION",
            "REVERSAL_DEPENDENCY",
        ) or exc.reason in (
            "DUPLICATE_ACCOUNT",
            "IDEMPOTENCY_CONFLICT",
            "BACKDATED_EFFECT_CHANGE",
        ):
            status = 409
        return JSONResponse(status_code=status, content={"error": exc.as_dict()})

    @app.exception_handler(CatalogError)
    async def catalog_error(request: Request, exc: CatalogError):
        return JSONResponse(
            status_code=422,
            content={"error": LedgerError("REFERENCE_NOT_FOUND", str(exc)).as_dict()},
        )

    @app.exception_handler(RequestValidationError)
    async def input_error(request: Request, exc: RequestValidationError):
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "VALIDATION_ERROR",
                    "message": "Invalid input fields or date format.",
                    "field_errors": {
                        ".".join(map(str, e["loc"])): e["msg"] for e in exc.errors()
                    },
                    "related_transaction_ids": [],
                    "reason": None,
                }
            },
        )

    @app.get("/")
    def index():
        return FileResponse(static_dir / "index.html")

    @app.get("/api/configuration")
    def configuration():
        return store.configuration()

    @app.get("/api/accounts")
    def accounts():
        return store.accounts()

    @app.post("/api/accounts", status_code=201)
    def create_account(payload: AccountInput):
        return store.create_account(
            payload.account_code,
            payload.display_name,
            payload.institution_type,
            payload.country_or_region,
            (
                [s.model_dump() for s in payload.position_scopes]
                if payload.position_scopes is not None
                else None
            ),
            payload.external_account_numbers,
        )

    @app.get("/api/accounts/{account_id}/position-scopes")
    def position_scopes(account_id: int):
        return store.position_scopes(account_id)

    @app.get("/api/accounts/{account_id}/external-account-references")
    def external_account_references(account_id: int):
        return store.external_account_references(account_id)

    @app.get("/api/instruments/search")
    def search(q: str = Query(default="", max_length=200)):
        return {"rows": catalog.search(q)}

    @app.get("/api/instruments/resolve")
    def resolve(
        scheme: str,
        identifier: str,
        as_of: date,
        authority: str | None = None,
        venue_id: str | None = None,
        venue_segment: str | None = None,
    ):
        return catalog.resolve(
            scheme,
            identifier,
            as_of,
            authority=authority,
            venue_id=venue_id,
            venue_segment=venue_segment,
        )

    @app.get("/api/instruments/{product_id}")
    def instrument_detail(product_id: str, listing_id: str | None = None):
        product = catalog.holding(product_id, listing_id)
        return {
            **asdict(product),
            "holding_leg": catalog.holding_legs[product_id],
            "observable": asdict(catalog.observables[product.asset_observable_id]),
            "quote_observable": asdict(
                catalog.observables[product.quote_observable_id]
            ),
            "listings": [
                asdict(l)
                for l in catalog.listings.values()
                if l.product_id == product_id
            ],
            "identifiers": [
                asdict(i)
                for i in catalog.identifiers
                if (i.target_type == "PRODUCT" and i.target_id == product_id)
                or (
                    i.target_type == "OBSERVABLE"
                    and i.target_id == product.asset_observable_id
                )
                or (
                    i.target_type == "LISTING"
                    and catalog.listings[i.target_id].product_id == product_id
                )
            ],
        }

    @app.get("/api/book-fx")
    def book_fx(base_currency: str, effective_date: date):
        return store.book_fx(base_currency, effective_date)

    @app.post("/api/transactions/cash-transfers", status_code=201)
    def cash_transfer(payload: CashInput):
        return service.submit(
            "CASH_TRANSFER",
            payload.model_dump(exclude={"request_key"}),
            payload.request_key,
        )

    @app.post("/api/transactions/trades", status_code=201)
    def trade(payload: TradeInput):
        return service.submit(
            "TRADE", payload.model_dump(exclude={"request_key"}), payload.request_key
        )

    @app.post("/api/transactions/fx-conversions", status_code=201)
    def fx_conversion(payload: FXInput):
        return service.submit(
            "FX_CONVERSION",
            payload.model_dump(exclude={"request_key"}),
            payload.request_key,
        )

    @app.post("/api/transactions/dividends", status_code=201)
    def dividend(payload: DividendInput):
        return service.submit(
            "DIVIDEND_RECEIPT",
            payload.model_dump(exclude={"request_key"}),
            payload.request_key,
        )

    @app.get("/api/observables")
    def observables():
        return {
            "rows": [
                asdict(o)
                for o in catalog.observables.values()
                if o.kind == "TRANSFERABLE" and o.asset_class in ("EQUITY", "CRYPTO")
            ]
        }

    @app.post("/api/transaction-previews")
    def preview(payload: CashInput | TradeInput | FXInput | DividendInput):
        return service.submit(
            (
                "TRADE"
                if isinstance(payload, TradeInput)
                else (
                    "FX_CONVERSION"
                    if isinstance(payload, FXInput)
                    else (
                        "DIVIDEND_RECEIPT"
                        if isinstance(payload, DividendInput)
                        else "CASH_TRANSFER"
                    )
                )
            ),
            payload.model_dump(exclude={"request_key"}),
            payload.request_key,
            preview=True,
        )

    @app.get("/api/holdings")
    def holdings(as_of: date | None = None, include_zero: bool = False):
        return analysis.holdings(as_of.isoformat() if as_of else None, include_zero)

    @app.get("/api/transactions")
    def transactions(
        as_of: date | None = None,
        limit: int = Query(50, ge=1, le=200),
        offset: int = Query(0, ge=0),
        account_id: int | None = None,
        transaction_type: str | None = None,
        date_from: date | None = None,
        currency: str | None = None,
        observable_id: str | None = None,
        status: Literal["ACTIVE", "REVERSED"] | None = None,
        date_to: date | None = None,
    ):
        return service.transactions(
            as_of.isoformat() if as_of else None,
            limit,
            offset,
            account_id,
            transaction_type,
            date_from.isoformat() if date_from else None,
            currency,
            observable_id,
            status,
            date_to.isoformat() if date_to else None,
        )

    @app.get("/api/transactions/{transaction_id}")
    def transaction_detail(transaction_id: int):
        return service.detail(transaction_id)

    @app.get("/api/transactions/{transaction_id}/reversal-check")
    def reversal_check(transaction_id: int):
        return service.reversal_check(transaction_id)

    @app.post("/api/transactions/{transaction_id}/reversal", status_code=201)
    def reverse(transaction_id: int, payload: ReversalInput):
        return service.reverse(transaction_id, payload.request_key, payload.memo)

    @app.get("/api/holdings/{position_id}")
    def position_detail(position_id: int, as_of: date | None = None):
        from ledger.investment.application.queries import position

        return position(store, position_id, as_of.isoformat() if as_of else None)

    @app.get("/api/cash/{account_id}/{currency}")
    def cash_detail(account_id: int, currency: str, as_of: date | None = None):
        from ledger.investment.application.queries import cash

        return cash(store, account_id, currency, as_of.isoformat() if as_of else None)

    from ledger.investment.imports.service import Imports

    imports = Imports(store)

    @app.get("/api/imports")
    def import_batches():
        return imports.list()

    @app.post("/api/imports", status_code=201)
    def import_upload(payload: ImportInput):
        return imports.upload(payload.filename, payload.csv_text)

    @app.get("/api/imports/{batch_id}")
    def import_detail(batch_id: int):
        return imports.detail(batch_id)

    @app.patch("/api/import-rows/{row_id}")
    def import_map(row_id: int, payload: ImportMapping):
        imports.map_row(row_id, payload.mapping)
        return {"row_id": str(row_id)}

    @app.post("/api/imports/{batch_id}/preview")
    def import_preview(batch_id: int):
        return imports.preview(batch_id)

    @app.post("/api/imports/{batch_id}/canonicalize")
    def import_commit(batch_id: int):
        return imports.canonicalize(batch_id)

    return app
