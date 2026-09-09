"""SDK-shaped behavior tests; no Futu import or live connection is needed."""
from datetime import datetime
from types import SimpleNamespace as NS
from zoneinfo import ZoneInfo

import pytest

import plumber.futu as futu_module
from plumber.futu import FutuGateway


class Frame:
    def __init__(self, rows):
        self.rows = rows
    def to_dict(self, orient):
        return self.rows


def make_gateway():
    gateway = FutuGateway.__new__(FutuGateway)
    gateway.sdk = NS(RET_OK=0, TrdEnv=NS(REAL='REAL'),
                     OrderType=NS(NORMAL='NORMAL', AUCTION='AUCTION', AUCTION_LIMIT='AUCTION_LIMIT'),
                     MarketState=NS(MORNING='MORNING', AFTERNOON='AFTERNOON', HK_CAS='HK_CAS'))
    gateway._connection = NS(account_id=123456789)
    gateway.lots = {'HK.00700': 100}
    return gateway


@pytest.mark.parametrize('trade,quote,expected', [(True, True, True), (False, True, False), (True, False, False), ('0', True, False), (None, True, False)])
def test_sdk_boolean_login_status(trade, quote, expected):
    gateway = make_gateway()
    now = datetime(2026, 9, 10, 10, tzinfo=ZoneInfo('Asia/Hong_Kong'))
    gateway.quote = NS(
        get_global_state=lambda: (0, {'trd_logined': trade, 'qot_logined': quote, 'timestamp': str(int(now.timestamp()))}),
        get_market_state=lambda **_: (0, Frame([{'market_state': 'MORNING'}])),
        get_market_snapshot=lambda **_: (0, Frame([{'suspension': False, 'lot_size': 100}])),
    )
    assert gateway.healthy('HK.00700', now) is expected


def test_current_day_query_includes_orders_created_during_the_session(monkeypatch):
    gateway = make_gateway()
    now = datetime(2026, 9, 10, 15, tzinfo=ZoneInfo('Asia/Hong_Kong'))
    class Frozen:
        @staticmethod
        def now(tz):
            return now
    monkeypatch.setattr(futu_module, 'datetime', Frozen)
    order = {'order_id': 'today', 'remark': 'lwm:i', 'code': 'HK.00700', 'trd_side': 'BUY',
             'order_type': 'NORMAL', 'qty': 100, 'price': 100, 'dealt_qty': 0, 'order_status': 'SUBMITTED'}
    def query(*, start, end, refresh_cache, **kwargs):
        assert refresh_cache is True
        # Pinned SDK normalizes a date-only end to midnight, excluding this order.
        created = datetime(2026, 9, 10, 14)
        rows = [order] if datetime.fromisoformat(start) <= created <= datetime.fromisoformat(end) else []
        return 0, Frame(rows)
    gateway.trade = NS(order_list_query=query, deal_list_query=lambda **_: (0, Frame([])))
    snapshot = gateway.snapshot('2026-09-10')
    assert [order.id for order in snapshot.orders] == ['today']


@pytest.mark.parametrize('remark', [None, float('nan'), '', 'N/A'])
def test_absent_sdk_remark_is_optional(remark):
    gateway = make_gateway()
    row = {'order_id': 'known', 'remark': remark, 'code': 'HK.00700', 'trd_side': 'BUY',
           'order_type': 'NORMAL', 'qty': 100, 'price': 100, 'dealt_qty': 0, 'order_status': 'SUBMITTED'}
    order = gateway._order(row)
    assert order.id == 'known'
    assert order.intent == ''
