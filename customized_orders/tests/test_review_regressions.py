"""Regression cases for the seven pre-PR review findings. No real broker access."""
from dataclasses import replace
from decimal import Decimal

import pytest

from conftest import limit
from customized_orders.engine import Engine
from customized_orders.runtime import run
from plumber.models import Deal, Snapshot


def reconciling(setup):
    e, g, t, s = setup
    pid = limit(setup)
    t.set('16:01:02')
    e.step(pid)
    e.step(pid)
    assert s.parent(pid)['state'] == 'RECONCILING'
    return pid


def late_deal():
    return Deal('late', '1', Decimal(100), Decimal(100), '2026-09-10T16:00:00+08:00')


def test_push_query_disagreement_blocks_then_converges_to_correct_remainder(setup):
    e, g, t, s = setup
    pid = reconciling(setup)
    event = late_deal()
    e.observe(Snapshot((), (event,)))
    e.step(pid)
    assert len(g.requests) == 1
    assert s.parent(pid)['reason'] == 'FILLED_QUANTITY_CONFLICT'
    g.fill('1', event.id, event.quantity, at=event.at)
    g.finish('1', 'CANCELLED_PART')
    e.step(pid)
    t.set('16:01:03')
    e.step(pid)
    assert len(g.requests) == 2
    assert g.requests[-1].quantity == 200


def test_persisted_push_blocks_stale_snapshots_after_restart(setup):
    e, g, t, s = setup
    pid = reconciling(setup)
    e.observe(Snapshot((), (late_deal(),)))
    restored = Engine(s, g, e.settings, e.calendar, t)
    for stamp in ('16:01:03', '16:01:10', '16:01:20'):
        t.set(stamp)
        restored.step(pid)
    assert len(g.requests) == 1
    assert s.parent(pid)['state'] == 'MANUAL_REVIEW'


def test_order_push_cumulative_fill_cannot_be_ignored(setup):
    e, g, t, s = setup
    pid = reconciling(setup)
    e.observe(Snapshot((replace(g.orders['1'], filled=Decimal(100)),), ()))
    e.step(pid)
    assert s.parent(pid)['reason'] == 'FILLED_QUANTITY_CONFLICT'
    assert len(g.requests) == 1


def test_deal_push_before_response_id_is_linked_by_correlated_order_push(setup):
    e, g, t, s = setup
    pid = reconciling(setup)
    with s.tx() as db:
        db.execute('UPDATE children SET broker_id=NULL WHERE parent=?', (pid,))
    # Separate drains simulate a process boundary between the two push types.
    e.observe(Snapshot((g.orders['1'],), ()))
    e.observe(Snapshot((), (late_deal(),)))
    assert s.db.execute('SELECT count(*) FROM events').fetchone()[0] == 2
    e.step(pid)
    assert s.parent(pid)['reason'] == 'FILLED_QUANTITY_CONFLICT'
    assert len(g.requests) == 1


def test_push_during_preflight_defers_submission_and_restarts_reconciliation(setup):
    e, g, t, s = setup
    pid = reconciling(setup)
    t.set('16:01:03')
    g.drain = lambda: Snapshot((), (late_deal(),))
    e.step(pid)
    assert len(g.requests) == 1
    assert s.parent(pid)['quiet_since'] is None
    assert not any(c['role'] == 'AUCTION' for c in s.children(pid))


def test_health_failure_after_transition_is_retryable_without_state_rollback(setup):
    e, g, t, s = setup
    pid = limit(setup)
    t.set('16:01:02')
    g.healthy = lambda *_: False
    e.step(pid)
    assert s.parent(pid)['state'] == 'TRANSITION_DUE'
    assert s.parent(pid)['reason'] == 'BROKER_UNAVAILABLE'
    assert not g.cancels
    g.healthy = lambda *_: True
    e.step(pid)
    assert g.cancels == ['1']
    assert s.parent(pid)['state'] == 'CANCEL_REQUESTED'


@pytest.mark.parametrize('remark', ['', 'unexpected-nonempty-remark'])
def test_save_broker_identity_before_handling_optional_remark(setup, remark):
    e, g, t, s = setup
    submit = g.submit
    def without_remark(request):
        order = replace(submit(request), intent=remark)
        g.orders[order.id] = order
        return order
    g.submit = without_remark
    pid = e.create('HK.00700', 'BUY', 300, 100, '2026-09-10')
    e.step(pid)
    assert s.children(pid)[0]['broker_id'] == '1'
    e.step(pid)
    if not remark:
        assert s.parent(pid)['state'] == 'LIMIT_WORKING'
    else:
        assert s.parent(pid)['state'] == 'MANUAL_REVIEW'
    s.command(pid, 'cancel')
    e.commands()
    e.step(pid)
    e.step(pid)
    assert s.parent(pid)['state'] == 'CANCELLED_BY_USER'
    assert g.cancels == ['1']


@pytest.mark.parametrize('changes', [{'price': Decimal(101)}, {'quantity': Decimal(500)}])
def test_explicit_cancel_of_externally_modified_order_keeps_automatic_conversion_disabled(setup, changes):
    e, g, t, s = setup
    pid = limit(setup)
    g.orders['1'] = replace(g.orders['1'], **changes)
    e.step(pid)
    assert s.parent(pid)['state'] == 'MANUAL_REVIEW'
    assert not g.cancels
    s.command(pid, 'cancel')
    e.commands()
    e.step(pid)
    assert g.cancels == ['1']
    e.step(pid)
    assert s.parent(pid)['state'] == 'CANCELLED_BY_USER'
    t.set('16:01:03')
    e.step(pid)
    assert len(g.requests) == 1


def test_explicit_cancel_still_withdraws_overfilled_modified_order(setup):
    e, g, t, s = setup
    pid = limit(setup)
    g.orders['1'] = replace(g.orders['1'], quantity=Decimal(500))
    g.fill('1', 'overfill', 400)
    s.command(pid, 'cancel')
    e.commands()
    e.step(pid)
    assert g.cancels == ['1']
    e.step(pid)
    assert s.parent(pid)['state'] == 'MANUAL_REVIEW'
    assert len(g.requests) == 1


def test_user_cancel_never_targets_an_unidentified_replacement_order(setup):
    e, g, t, s = setup
    pid = limit(setup)
    original = g.orders.pop('1')
    g.orders['other'] = replace(original, id='other', intent='unrelated')
    s.command(pid, 'cancel')
    e.commands()
    e.step(pid)
    assert not g.cancels
    assert s.parent(pid)['state'] == 'MANUAL_REVIEW'


def test_missing_historical_calendar_isolated_while_other_parent_and_monitoring_progress(setup):
    e, g, t, s = setup
    e.calendar.records['2026-09-09'] = dict(e.calendar.records['2026-09-10'])
    e.settings.instruments['HK.00700']['verified_for'] = '2026-09-09'
    t.set('10:00:00', day='2026-09-09')
    old = e.create('HK.00700', 'BUY', 300, 100, '2026-09-09')
    e.step(old)
    e.step(old)
    g.fill('1', 'old-fill', 100)
    del e.calendar.records['2026-09-09']
    e.settings.instruments['HK.00700']['verified_for'] = '2026-09-10'
    t.set('10:00:00')
    new = e.create('HK.00700', 'SELL', 300, 100, '2026-09-10')
    assert run(e, once=True) == 2  # Alert for the old order, not a worker crash.
    assert s.parent(old)['reason'] == 'CALENDAR_UNAVAILABLE'
    assert s.parent(old)['filled'] == '100'
    assert s.children(new)[0]['broker_id'] == '2'
    assert run(e, once=True) == 2
    assert s.parent(new)['state'] == 'LIMIT_WORKING'
    assert len(g.requests) == 2
