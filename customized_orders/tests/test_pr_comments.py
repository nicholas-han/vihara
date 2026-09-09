"""Regression coverage for PR #15 review feedback; no real broker connections."""
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from decimal import Decimal
import json
import pytest
from conftest import limit
from customized_orders import cli
from customized_orders.config import Connection
from customized_orders.engine import Engine
from customized_orders.runtime import run, live_account_lock
from customized_orders.store import Store
from plumber.models import PushEvidenceError, Unavailable


def test_cancel_intent_pre_attempt_crash_resumes(setup, monkeypatch):
    e,g,t,s=setup;pid=limit(setup);t.set('16:01:02')
    original=s.tx
    @contextmanager
    def crash_after_intent():
        with original() as db:
            yield db
        if s.children(pid)[0]['cancel_phase']=='INTENT':
            raise SystemExit('crash before attempt')
    monkeypatch.setattr(s,'tx',crash_after_intent)
    with pytest.raises(SystemExit):e.step(pid)
    assert not g.cancels
    monkeypatch.setattr(s,'tx',original)
    restarted=Engine(s,g,e.settings,e.calendar,t);restarted.step(pid)
    assert g.cancels==['1']
    assert s.children(pid)[0]['cancel_phase']=='ACKNOWLEDGED'


def test_ambiguous_cancel_crash_does_not_retry(setup, monkeypatch):
    e,g,t,s=setup;pid=limit(setup);t.set('16:01:02');original=g.cancel
    def crash(oid):raise SystemExit('unknown call outcome')
    monkeypatch.setattr(g,'cancel',crash)
    with pytest.raises(SystemExit):e.step(pid)
    monkeypatch.setattr(g,'cancel',original)
    Engine(s,g,e.settings,e.calendar,t).step(pid)
    assert not g.cancels
    assert s.parent(pid)['reason']=='CANCELLATION_RESULT_UNKNOWN_CHECK_BROKER'


def test_legacy_cancel_marker_migrates_conservatively(setup):
    e,g,t,s=setup;pid=limit(setup)
    with s.tx() as db:
        db.execute('UPDATE children SET cancel_sent=1')
        db.execute('ALTER TABLE children DROP COLUMN cancel_phase')
    reopened=Store(s.path)
    try:assert reopened.children(pid)[0]['cancel_phase']=='UNKNOWN'
    finally:reopened.close()


def test_live_lock_shared_across_config_aliases_and_state_dirs(setup,tmp_path,monkeypatch):
    e,_,_,_=setup
    monkeypatch.setattr(Path,'home',classmethod(lambda cls:tmp_path))
    a=replace(e.settings,mode='LIVE',connection=Connection('127.0.0.1',11111,123456789))
    b=replace(a,alias='second',state_dir=tmp_path/'other',connection=Connection('localhost',22222,123456789))
    with live_account_lock(a):
        with pytest.raises(ValueError,match='already running'):
            with live_account_lock(b):pass
        with live_account_lock(replace(b,connection=Connection('localhost',22222,987654321))):pass
    with live_account_lock(b):pass
    files=list((tmp_path/'.local/state/vihara/account-locks').iterdir())
    assert all('123456789' not in p.name and b'123456789' not in p.read_bytes() for p in files)
    assert all(p.stat().st_mode & 0o077 == 0 for p in files)


def test_status_without_calendar_keeps_durable_details(setup,monkeypatch,capsys):
    e,g,t,s=setup;pid=limit(setup);e.manual(pid,'CALENDAR_UNAVAILABLE');e.calendar.records.clear()
    monkeypatch.setattr(cli,'load',lambda *a:e.settings)
    monkeypatch.setattr(cli.Calendar,'load',lambda *a:e.calendar)
    monkeypatch.setattr(cli,'Store',lambda *a:s)
    monkeypatch.setattr(s,'close',lambda:None)
    assert cli.main(['status',pid])==2
    data=json.loads(capsys.readouterr().out)
    assert data['state']=='MANUAL_REVIEW' and data['children'][0]['broker_id']=='1'
    assert data['conversion_window_hkt'] is None and data['calendar_warning']=='CALENDAR_UNAVAILABLE'


@pytest.mark.parametrize('kind,time',[('FULL_DAY','16:00:01'),('HALF_DAY','12:00:01')])
def test_carry_forward_before_conversion_window(setup,kind,time):
    e,g,t,s=setup;e.calendar.records['2026-09-10']['session_type']=kind
    pid=limit(setup);g.orders['1']=replace(g.orders['1'],kind='AUCTION_LIMIT');t.set(time);e.step(pid)
    assert s.parent(pid)['state']=='LIMIT_WORKING'
    t.set(time[:2]+':01:02');e.step(pid)
    assert g.cancels==['1']


def test_auction_limit_during_continuous_still_rejected(setup):
    e,g,t,s=setup;pid=limit(setup);g.orders['1']=replace(g.orders['1'],kind='AUCTION_LIMIT');e.step(pid)
    assert s.parent(pid)['reason']=='EXTERNAL_ORDER_MODIFICATION'


def test_childless_review_cancel_releases_conflict(setup):
    e,g,t,s=setup;pid=e.create('HK.00700','BUY',300,100,'2026-09-10');g.available=Decimal(0);e.step(pid)
    assert s.parent(pid)['state']=='MANUAL_REVIEW' and not s.children(pid)
    s.command(pid,'cancel');e.commands();e.step(pid)
    assert s.parent(pid)['state']=='CANCELLED_BY_USER' and not s.parent(pid)['active']
    g.available=Decimal(100000);assert e.create('HK.00700','BUY',300,100,'2026-09-10')!=pid


def test_reconcile_command_does_not_skip_deadline_cycle(setup):
    e,g,t,s=setup;pid=limit(setup);t.set('16:01:02');e.step(pid);e.step(pid)
    t.set('16:05:29');s.command(pid,'reconcile');run(e,once=True)
    assert len(g.requests)==2 and s.parent(pid)['state']=='AUCTION_SUBMITTING'


def test_transport_push_failure_recovers_after_restart_and_quiet_queries(setup,monkeypatch):
    e,g,t,s=setup;pid=limit(setup);original=g.drain
    def fail():raise Unavailable('transport')
    monkeypatch.setattr(g,'drain',fail);run(e,once=True)
    assert s.parent(pid)['state']!='MANUAL_REVIEW'
    monkeypatch.setattr(g,'drain',original)
    e=Engine(s,g,e.settings,e.calendar,t);t.set('16:01:02');run(e,once=True)
    assert not g.cancels
    t.set('16:01:03');run(e,once=True)
    assert g.cancels==['1']
    assert not s.db.execute('SELECT * FROM push_recovery').fetchall()


def test_malformed_push_isolated_to_known_order(setup,monkeypatch):
    e,g,t,s=setup;pid=limit(setup);other=e.create('HK.00700','SELL',300,100,'2026-09-10');e.step(other);e.step(other)
    original=g.drain
    def fail():raise PushEvidenceError('malformed','1')
    monkeypatch.setattr(g,'drain',fail);run(e,once=True)
    assert s.parent(pid)['state']=='MANUAL_REVIEW'
    assert s.parent(other)['state']=='LIMIT_WORKING'
    monkeypatch.setattr(g,'drain',original);t.set('16:01:02');run(e,once=True);t.set('16:01:03');run(e,once=True)
    assert g.cancels==['2'] and s.parent(pid)['state']=='MANUAL_REVIEW'


def test_persistent_push_outage_reaches_manual_at_deadline(setup,monkeypatch):
    e,g,t,s=setup;pid=limit(setup)
    def fail():raise Unavailable('transport')
    monkeypatch.setattr(g,'drain',fail);run(e,once=True)
    assert s.parent(pid)['reason']=='PUSH_STREAM_RECOVERING'
    t.set('16:05:30');assert run(e,once=True)==2
    assert s.parent(pid)['reason']=='PUSH_RECOVERY_DEADLINE' and not g.cancels


def test_push_recovery_requires_queries_to_converge(setup,monkeypatch):
    from plumber.models import Deal, Snapshot
    e,g,t,s=setup;pid=limit(setup);original=g.drain
    def fail():raise Unavailable('transport')
    monkeypatch.setattr(g,'drain',fail);run(e,once=True)
    monkeypatch.setattr(g,'drain',original)
    e.observe(Snapshot((),(Deal('late','1',Decimal(100),Decimal(100),t().isoformat()),)))
    t.set('16:01:02');run(e,once=True);t.set('16:01:03');run(e,once=True)
    assert not g.cancels and s.db.execute('SELECT * FROM push_recovery').fetchone()
