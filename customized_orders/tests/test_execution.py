from dataclasses import replace
from decimal import Decimal
import sqlite3
import pytest
from plumber.models import Snapshot,Deal,UnknownResult
from customized_orders.engine import Engine
from conftest import limit,auction


def test_partial_cancel_race_and_full_auction(setup):
    e,g,t,s = setup
    pid = limit(setup)
    g.fill("1","d1",100)
    g.delay_cancel = True
    t.set("16:01:02")
    e.step(pid)
    g.fill("1","d2",100)
    e.step(pid)
    assert len(g.requests) == 1
    g.finish("1","CANCELLED_PART")
    e.step(pid)
    t.set("16:01:03")
    e.step(pid)
    assert g.requests[-1].quantity == 100
    g.fill("2","d3",100,price="105")
    e.step(pid)
    assert s.parent(pid)["state"] == "COMPLETED"
    assert s.parent(pid)["filled"] == "300"
    assert s.parent(pid)["average_price"] == str(Decimal(30500)/3/100)


def test_all_filled_no_conversion(setup):
    e,g,t,s = setup
    pid = limit(setup)
    g.fill("1","all",300)
    t.set("16:01:02")
    e.step(pid)
    assert s.parent(pid)["state"] == "COMPLETED"
    assert not g.cancels and len(g.requests) == 1


@pytest.mark.parametrize("filled,state",[(0,"UNFILLED"),(100,"PARTIALLY_FILLED"),(300,"COMPLETED")])
def test_close_outcomes(setup,filled,state):
    e,g,t,s = setup
    pid = limit(setup)
    auction(setup,pid)
    if filled:
        g.fill("2","auction",filled)
    if filled != 300:
        g.finish("2","CANCELLED_PART" if filled else "CANCELLED_ALL")
    t.set("16:10:01")
    e.step(pid)
    assert s.parent(pid)["state"] == state


def test_unknown_submission_created_is_recovered_once(setup):
    e,g,t,s = setup
    g.timeout_submit = True
    pid = limit(setup)
    auction(setup,pid)
    assert len(g.requests) == 2
    restarted = Engine(s,g,e.settings,e.calendar,t)
    restarted.step(pid)
    assert len(g.requests) == 2
    assert s.parent(pid)["state"] == "AUCTION_WORKING"


def test_unknown_submission_absent_never_retried(setup):
    e,g,t,s = setup
    def submit(r):
        g.requests.append(r)
        raise UnknownResult("UNKNOWN")
    g.submit = submit
    pid = limit(setup)
    e.step(pid)
    assert s.parent(pid)["state"] == "MANUAL_REVIEW"
    assert len(g.requests) == 1


def test_cancel_timeout_never_submits_until_terminal(setup):
    e,g,t,s = setup
    pid = limit(setup)
    g.delay_cancel = True
    auction(setup,pid)
    assert len(g.requests) == 1
    t.set("16:05:30")
    e.step(pid)
    assert s.parent(pid)["state"] == "MANUAL_REVIEW"
    assert len(g.cancels) == 1


def test_slow_risk_query_crosses_deadline(setup):
    e,g,t,s = setup
    pid = limit(setup)
    t.set("16:01:02")
    e.step(pid); e.step(pid)
    t.set("16:05:29")
    def capacity(*_):
        t.set("16:05:31")
        return Decimal(999999)
    g.capacity = capacity
    e.step(pid)
    assert len(g.requests) == 1
    assert s.parent(pid)["reason"] == "SUBMISSION_DEADLINE"


def test_quiet_period_resets_after_restart(setup):
    e,g,t,s = setup
    pid = limit(setup)
    t.set("16:01:02")
    e.step(pid); e.step(pid)
    t.set("16:01:20")
    restarted = Engine(s,g,e.settings,e.calendar,t)
    restarted.step(pid)
    assert len(g.requests) == 1
    t.set("16:01:21")
    restarted.step(pid)
    assert len(g.requests) == 2


def test_duplicates_and_conflicting_deal(setup):
    e,g,t,s = setup
    pid = limit(setup)
    g.fill("1","same",100)
    e.step(pid); e.step(pid)
    assert s.parent(pid)["filled"] == "100"
    g.deals["same"] = replace(g.deals["same"],price=Decimal(101))
    e.step(pid)
    assert s.parent(pid)["reason"] == "EXECUTION_CONFLICT"


def test_query_skew_retries_then_converges(setup):
    e,g,t,s = setup
    pid = limit(setup)
    g.orders["1"] = replace(g.orders["1"],filled=Decimal(100))
    e.step(pid)
    assert s.parent(pid)["state"] == "LIMIT_WORKING"
    g.fill("1","arrived",100)
    e.step(pid)
    assert s.parent(pid)["filled"] == "100"


def test_external_modification_and_overfill_fail_closed(setup):
    e,g,t,s = setup
    pid = limit(setup)
    g.orders["1"] = replace(g.orders["1"],quantity=Decimal(500))
    e.step(pid)
    assert s.parent(pid)["reason"] == "EXTERNAL_ORDER_MODIFICATION"


def test_duplicate_intent_order_detected(setup):
    e,g,t,s = setup
    pid = limit(setup)
    g.orders["other"] = replace(g.orders["1"],id="other")
    e.step(pid)
    assert s.parent(pid)["state"] == "MANUAL_REVIEW"


def test_database_constraints(setup):
    e,g,t,s = setup
    pid = limit(setup)
    with pytest.raises(sqlite3.IntegrityError):
        e.create("HK.00700","BUY",100,100,"2026-09-10")
    auction(setup,pid)
    with pytest.raises(sqlite3.IntegrityError),s.tx() as db:
        db.execute("INSERT INTO children(id,parent,role,intent,quantity,status) VALUES ('extra',?,'AUCTION','extra','100','SUBMITTING')",(pid,))


def test_user_cancel_and_acknowledge(setup):
    e,g,t,s = setup
    pid = limit(setup)
    s.command(pid,"cancel")
    e.commands(); e.step(pid); e.step(pid)
    assert s.parent(pid)["state"] == "CANCELLED_BY_USER"
    previous = (len(g.requests),len(g.cancels))
    s.command(pid,"acknowledge","Checked in broker app")
    e.commands()
    assert previous == (len(g.requests),len(g.cancels))


def test_no_cancel_period_reports_pending_not_success(setup):
    e,g,t,s = setup
    pid = limit(setup)
    auction(setup,pid)
    t.set("16:06:00")
    s.command(pid,"cancel")
    e.commands(); e.step(pid)
    assert s.parent(pid)["reason"] == "CANNOT_CANCEL_CONTINUE_TRACKING"
    assert s.parent(pid)["state"] != "CANCELLED_BY_USER"
    assert len(g.cancels) == 1


def test_disconnected_at_deadline(setup):
    e,g,t,s = setup
    pid = limit(setup)
    g.connected = False
    t.set("16:05:30")
    e.step(pid)
    assert s.parent(pid)["state"] == "MANUAL_REVIEW"
    assert len(g.requests) == 1


@pytest.mark.parametrize("field,value",[("lot_size",200),("cas",False),("verified_for","2020-01-01"),("tick_size","0.3")])
def test_pretrade_validation(setup,field,value):
    e,g,t,s = setup
    e.settings.instruments["HK.00700"][field] = value
    with pytest.raises(ValueError):
        e.create("HK.00700","BUY",100,100,"2026-09-10")
    assert not g.requests


def test_sell_capacity_rechecked_at_conversion(setup):
    e,g,t,s = setup
    pid = e.create("HK.00700","SELL",300,100,"2026-09-10")
    e.step(pid);e.step(pid)
    t.set("16:01:02");e.step(pid);e.step(pid)
    g.available = Decimal(0)
    t.set("16:01:03");e.step(pid)
    assert len(g.requests) == 1 and s.parent(pid)["state"] == "MANUAL_REVIEW"

@pytest.mark.parametrize('source,state', [('UNKNOWN','MANUAL_REVIEW'),('EXCHANGE','AUCTION_SUBMITTING')])
def test_unrequested_cancellation_requires_provenance(setup,source,state):
    e,g,t,s=setup
    pid=limit(setup)
    t.set('16:01:02')
    g.finish('1','CANCELLED_ALL',source=source)
    e.step(pid)
    t.set('16:01:03');e.step(pid)
    assert s.parent(pid)['state'] == state


def test_push_evidence_deduplicates_and_resets_quiet_period(setup):
    e,g,t,s=setup
    pid=limit(setup)
    t.set('16:01:02');e.step(pid);e.step(pid)
    snap=g.snapshot('2026-09-10')
    e.observe(snap);e.observe(snap)
    assert s.db.execute('SELECT count(*) FROM events').fetchone()[0] == 1
    assert s.parent(pid)['quiet_since'] is None


def test_manual_review_keeps_tracking_without_new_orders(setup):
    e,g,t,s=setup
    pid=limit(setup)
    e.manual(pid,'TEST_UNCERTAINTY')
    g.fill('1','late',100)
    e.step(pid)
    assert s.parent(pid)['filled'] == '100'
    assert s.parent(pid)['state'] == 'MANUAL_REVIEW'
    assert len(g.requests) == 1


def test_terminal_state_cannot_be_rearmed(setup):
    e,g,t,s=setup
    pid=limit(setup)
    g.fill('1','full',300)
    e.step(pid)
    with pytest.raises(ValueError):
        e.state(pid,'LIMIT_WORKING','INVALID')
    assert s.parent(pid)['state'] == 'COMPLETED'


def test_late_cancel_does_not_relabel_auction_expiry_as_cancellation_success(setup):
    e,g,t,s=setup
    pid=limit(setup);auction(setup,pid)
    t.set('16:06:01');s.command(pid,'cancel');e.commands();e.step(pid)
    g.fill('2','auction-partial',100)
    g.finish('2','CANCELLED_PART')
    t.set('16:10:01');e.step(pid)
    assert s.parent(pid)['state'] == 'PARTIALLY_FILLED'


@pytest.mark.parametrize('phase',['ARMED','LIMIT_WORKING','CANCEL_REQUESTED','RECONCILING','AUCTION_SUBMITTING','AUCTION_WORKING'])
def test_restart_at_each_external_effect_boundary(setup,phase):
    e,g,t,s=setup
    pid=e.create('HK.00700','BUY',300,100,'2026-09-10')
    if phase != 'ARMED':
        e.step(pid);e.step(pid)
    if phase in {'CANCEL_REQUESTED','RECONCILING','AUCTION_SUBMITTING','AUCTION_WORKING'}:
        t.set('16:01:02');e.step(pid)
    if phase in {'RECONCILING','AUCTION_SUBMITTING','AUCTION_WORKING'}:
        e.step(pid)
    if phase in {'AUCTION_SUBMITTING','AUCTION_WORKING'}:
        t.set('16:01:03');e.step(pid)
    if phase == 'AUCTION_WORKING':e.step(pid)
    assert s.parent(pid)['state'] == phase
    before=len(g.requests)
    restarted=Engine(s,g,e.settings,e.calendar,t)
    restarted.step(pid)
    assert len(g.requests) == before + (1 if phase == 'ARMED' else 0)
