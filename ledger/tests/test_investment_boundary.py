"""The unified ledger must operate without Portfolio Manager or the web stack."""

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
from ledger.investment.application.service import Service
from ledger.investment.validation import validate
store = Store(sys.argv[1], HoldingCatalog(sys.argv[2]))
store.initialize()
account = store.create_account('TEST', 'Test Account')['financial_account_id']
service = Service(store)
service.submit('CASH_TRANSFER', {'effective_date': '2026-09-01', 'currency': 'HKD', 'amount': '100', 'destination_account_id': account}, 'deposit')
assert service.balances()['cash'][0]['quantity'] == '100'
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
