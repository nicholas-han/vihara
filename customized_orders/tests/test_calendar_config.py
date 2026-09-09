from datetime import datetime
from pathlib import Path
import os
import json
import pytest
from customized_orders.calendar import HKT
from customized_orders.config import load,private_file,ConfigError,Connection
from customized_orders.runtime import worker_lock,PaperGateway
from plumber.models import Request
from decimal import Decimal


def test_half_day_and_non_local_timezone(setup):
    e,g,t,s = setup
    e.calendar.records["2026-09-10"]["session_type"] = "HALF_DAY"
    session = e.calendar.session("2026-09-10")
    assert session.transition.hour == 12
    assert session.continuous(datetime.fromisoformat("2026-09-10T02:00:00+00:00"))
    assert not session.continuous(datetime.fromisoformat("2026-09-10T05:00:00+00:00"))


@pytest.mark.parametrize("change",[{"session_type":"CLOSED"},{"valid_until":"2026-01-01"},{"submission_deadline":"16:06:00"},{"verified_at":"2026-09-09T00:00:00"}])
def test_calendar_rejects_missing_or_invalid(setup,change):
    e,*_ = setup
    e.calendar.records["2026-09-10"].update(change)
    with pytest.raises(ValueError):
        e.calendar.session("2026-09-10")


def test_private_file_permissions_symlink_and_git(tmp_path):
    p = tmp_path / "private.toml"
    p.write_text("not-a-secret")
    p.chmod(0o644)
    with pytest.raises(ConfigError):
        private_file(p)
    p.chmod(0o600)
    assert private_file(p) == p.resolve()
    link = tmp_path / "linked.toml"
    link.symlink_to(p)
    with pytest.raises(ConfigError):
        private_file(link)
    (tmp_path / ".git").write_text("gitdir: elsewhere")
    with pytest.raises(ConfigError):
        private_file(p)


def test_connection_repr_never_contains_account_or_secret():
    c = Connection("localhost",11111,987654321,"SENSITIVE_ENV_NAME")
    assert "987654321" not in repr(c) and "SENSITIVE_ENV_NAME" not in repr(c)


def test_worker_lock_excludes_second_worker(tmp_path):
    with worker_lock(tmp_path / "lock"):
        with pytest.raises(ValueError),worker_lock(tmp_path / "lock"):
            pass


def test_paper_broker_survives_restart(tmp_path):
    p = tmp_path / "paper.json"
    g = PaperGateway(p)
    r = Request("intent","HK.00700","BUY","LIMIT",Decimal(100),Decimal(100))
    o = g.submit(r)
    restored = PaperGateway(p)
    assert restored.orders[o.id] == o
    restored.cancel(o.id)
    assert PaperGateway(p).orders[o.id].terminal
    assert p.stat().st_mode & 0o077 == 0
