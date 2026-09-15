"""Public Python operations for investment applications.

The application composition root injects a Store into these small services.
Callers receive the existing Ledger dictionaries: identifiers and exact amounts
remain strings, economic dates remain ISO dates, and failures remain LedgerError.
Book FX reference input retains its existing ``datetime.date`` contract.
Connections, replay state and persistence helpers are internal to Ledger.
"""

from .application.service import Service as _Service
from .application import queries as _queries, relationships as _relationships
from .application.results import investment_results as _investment_results
from .persistence.charges import ChargeReferences as _ChargeReferences
from .imports.service import Imports as _Imports
from .errors import LedgerError

__all__ = ["Commands", "Queries", "References", "Imports", "LedgerError"]


class Commands:
    """Atomic economic commands and editable provenance relationships."""

    def __init__(self, store):
        self._store = store
        self._service = _Service(store)

    def submit(self, kind, payload, request_key, *, preview=False):
        return self._service.submit(kind, payload, request_key, preview=preview)

    def submit_many(self, events, relationships, request_key, *, preview=False):
        return self._service.submit_many(
            events, relationships, request_key, preview=preview
        )

    def reverse(self, transaction_id, request_key, memo=None):
        return self._service.reverse(transaction_id, request_key, memo)

    def replace_related(self, transaction_id, transaction_ids, expected_version):
        return _relationships.replace(
            self._store, transaction_id, transaction_ids, expected_version
        )


class Queries:
    """Read-only ledger facts, balances and recognized investment results."""

    def __init__(self, store):
        self._store = store
        self._service = _Service(store)

    def configuration(self):
        return self._store.configuration()

    def balances(self, as_of=None, include_zero=False):
        return self._service.balances(as_of, include_zero)

    def transactions(
        self,
        as_of=None,
        limit=50,
        offset=0,
        account_id=None,
        transaction_type=None,
        date_from=None,
        currency=None,
        observable_id=None,
        status=None,
        date_to=None,
    ):
        return self._service.transactions(
            as_of,
            limit,
            offset,
            account_id,
            transaction_type,
            date_from,
            currency,
            observable_id,
            status,
            date_to,
        )

    def detail(self, transaction_id):
        return self._service.detail(transaction_id)

    def reversal_check(self, transaction_id):
        return self._service.reversal_check(transaction_id)

    def position(self, position_id, as_of=None):
        return _queries.position(self._store, position_id, as_of)

    def cash(self, account_id, currency, as_of=None):
        return _queries.cash(self._store, account_id, currency, as_of)

    def related(self, transaction_id):
        with self._store.read() as conn:
            return _relationships.related(conn, transaction_id)

    def investment_results(self, date_from=None, date_to=None, account_id=None):
        return _investment_results(self._store, date_from, date_to, account_id)


class References:
    """Account, scope, Book FX and charge reference operations."""

    def __init__(self, store):
        self._store = store
        self._charges = _ChargeReferences(store)

    def accounts(self):
        return self._store.accounts()

    def create_account(
        self,
        code,
        name,
        institution_type,
        country_or_region=None,
        position_scopes=None,
        external_account_numbers=None,
    ):
        return self._store.create_account(
            code,
            name,
            institution_type,
            country_or_region,
            position_scopes,
            external_account_numbers,
        )

    def position_scopes(self, account_id):
        return self._store.position_scopes(account_id)

    def external_account_references(self, account_id):
        return self._store.external_account_references(account_id)

    def import_references(self, document):
        return self._store.import_references(document)

    def book_fx(self, base, effective_date, *, observation_id=None):
        return self._store.book_fx(
            base, effective_date, observation_id=observation_id
        )

    def add_book_fx(self, base, effective_date, rate, source):
        return self._store.add_book_fx(base, effective_date, rate, source)

    def import_book_fx(self, rows):
        return self._store.import_book_fx(rows)

    def categories(self):
        return self._charges.categories()

    def create_category(self, code, display_name, ledger_account_code):
        return self._charges.create_category(code, display_name, ledger_account_code)

    def rename_category(self, key, display_name):
        return self._charges.rename_category(key, display_name)

    def mappings(self, financial_account_id=None, source_label_raw=None):
        return self._charges.mappings(financial_account_id, source_label_raw)

    def save_mapping(
        self,
        financial_account_id,
        source_label_raw,
        investment_charge_category_id,
        description=None,
        *,
        key=None,
    ):
        return self._charges.save_mapping(
            financial_account_id,
            source_label_raw,
            investment_charge_category_id,
            description,
            key=key,
        )

    def delete_mapping(self, key):
        return self._charges.delete_mapping(key)


class Imports:
    """Staging operations that reuse Ledger's atomic economic commands."""

    def __init__(self, store):
        self._imports = _Imports(store)

    def upload(self, filename, text):
        return self._imports.upload(filename, text)

    def list(self):
        return self._imports.list()

    def detail(self, batch):
        return self._imports.detail(batch)

    def map_row(self, row_id, mapping):
        return self._imports.map_row(row_id, mapping)

    def preview(self, batch):
        return self._imports.preview(batch)

    def canonicalize(self, batch):
        return self._imports.canonicalize(batch)
