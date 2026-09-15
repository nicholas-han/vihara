"""The unified ledger must operate without Portfolio Manager or the web stack."""

import ast
import inspect
import os
from pathlib import Path
import subprocess
import sys


def test_investment_ledger_runs_without_portfolio_or_fastapi(tmp_path):
    root = Path(__file__).resolve().parents[2]
    script = """
import importlib.abc
import sys
class Boundary(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'portfolio_manager', 'fastapi'}:
            raise AssertionError('Forbidden dependency: ' + fullname)
sys.meta_path.insert(0, Boundary())
from instrument_manager.holding_catalog import HoldingCatalog
from ledger.investment.persistence.store import Store
from ledger.investment.api import Commands, Queries, References, Imports
from ledger.investment.validation import validate
store = Store(sys.argv[1], HoldingCatalog(sys.argv[2]))
store.initialize()
account = References(store).create_account('TEST', 'Test Account', institution_type='BROKER-DEALER')['financial_account_id']
commands, queries = Commands(store), Queries(store)
payload = {'effective_date': '2026-09-01', 'currency': 'HKD', 'amount': '100', 'destination_account_id': account}
commands.submit('CASH_TRANSFER', payload, 'deposit', preview=True)
assert queries.configuration()['transaction_count'] == 0
commands.submit('CASH_TRANSFER', payload, 'deposit')
assert commands.submit('CASH_TRANSFER', payload, 'deposit')['replayed']
assert queries.balances()['cash'][0]['quantity'] == '100'
assert Imports(store).list()['rows'] == []
validate(store)
assert 'portfolio_manager' not in sys.modules
"""
    env = {
        **os.environ,
        "PYTHONPATH": os.pathsep.join(
            str(root / p) for p in ("ledger", "instrument_manager")
        ),
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    subprocess.run(
        [
            sys.executable,
            "-B",
            "-c",
            script,
            str(tmp_path / "ledger.sqlite3"),
            str(root / "instrument_manager/instrument_manager/seeds/holdings"),
        ],
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )


def test_public_operations_do_not_accept_connections_or_unbounded_options():
    from ledger.investment.api import Commands, Queries, References, Imports

    for service in (Commands, Queries, References, Imports):
        for name, method in inspect.getmembers(service, inspect.isfunction):
            if name.startswith("_"):
                continue
            parameters = inspect.signature(method).parameters
            assert not {"connection", "conn", "store"} & parameters.keys(), name
            assert all(
                p.kind != inspect.Parameter.VAR_KEYWORD
                for p in parameters.values()
            ), name


def test_holdings_routes_use_public_services_after_startup_composition():
    root = Path(__file__).resolve().parents[2]
    module = ast.parse(
        (root / "portfolio_manager/portfolio_manager/holdings/api.py").read_text()
    )
    create_app = next(
        n for n in module.body if isinstance(n, ast.FunctionDef) and n.name == "create_app"
    )
    handlers = [
        n for n in create_app.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]
    assert handlers
    for handler in handlers:
        for node in ast.walk(handler):
            if isinstance(node, ast.Name):
                assert node.id not in {"store", "conn", "connection"}, handler.name
            if isinstance(node, ast.ImportFrom) and node.module:
                assert not node.module.startswith(
                    ("ledger.investment.application", "ledger.investment.persistence", "ledger.investment.imports")
                ), handler.name
