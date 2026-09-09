from datetime import datetime
from decimal import Decimal
from queue import SimpleQueue
from types import SimpleNamespace as NS
import pytest
from plumber.futu import FutuGateway
from plumber.models import Request,UnknownResult,Unavailable


class Frame:
    def __init__(self,rows): self.rows=rows
    def to_dict(self,orient): return self.rows


def gateway():
    g=FutuGateway.__new__(FutuGateway)
    g.sdk=NS(RET_OK=0,TrdEnv=NS(REAL="REAL"),OrderType=NS(NORMAL="NORMAL",AUCTION="AUCTION",AUCTION_LIMIT="AUCTION_LIMIT"),TrdSide=NS(BUY="BUY",SELL="SELL"),TimeInForce=NS(DAY="DAY"),ModifyOrderOp=NS(CANCEL="CANCEL"))
    g._connection=NS(account_id=123456789)
    g.allow_trading=True
    g.events=SimpleQueue()
    return g


def row(**kwargs):
    return dict(order_id="o1",remark="lwm:test",code="HK.00700",trd_side="BUY",order_type="AUCTION",qty=100.0,price=0.0,dealt_qty=0.0,order_status="SUBMITTED",**kwargs)


def test_auction_placeholder_explicit_account_and_exact_boundary():
    g=gateway(); calls=[]
    def place(**kw):
        calls.append(kw)
        return 0,Frame([row()])
    g.trade=NS(place_order=place)
    o=g.submit(Request("lwm:test","HK.00700","BUY","AUCTION",Decimal(100),None))
    assert calls[0]["price"] == 0 and calls[0]["acc_id"] == 123456789
    assert calls[0]["remark"] == "lwm:test" and calls[0]["adjust_limit"] == 0
    assert o.price is None and isinstance(o.quantity,Decimal)
    assert "123456789" not in repr(o)


def test_sdk_secret_errors_are_never_exposed():
    g=gateway()
    def place(**_): raise RuntimeError("password=secret account=123456789")
    g.trade=NS(place_order=place)
    with pytest.raises(UnknownResult) as caught:
        g.submit(Request("lwm:test","HK.00700","BUY","LIMIT",Decimal(100),Decimal(100)))
    assert str(caught.value) == "SUBMISSION_RESULT_UNKNOWN"
    assert caught.value.__suppress_context__


def test_reader_never_mutates_and_capacity_is_not_margin_or_short():
    g=gateway();g.allow_trading=False
    with pytest.raises(Unavailable):
        g.submit(Request("i","HK.00700","BUY","LIMIT",Decimal(100),Decimal(100)))
    with pytest.raises(Unavailable): g.cancel("x")
    g.trade=NS(acctradinginfo_query=lambda **_: (0,Frame([{"max_cash_buy":100,"max_cash_and_margin_buy":900,"max_position_sell":200,"max_sell_short":800}])))
    assert g.capacity("HK.00700","BUY","AUCTION",Decimal(100)) == 100
    assert g.capacity("HK.00700","SELL","AUCTION",Decimal(100)) == 200


def test_corrected_execution_fails_closed():
    g=gateway()
    with pytest.raises(Unavailable):
        g._deal({"status":"CHANGED"})


def test_push_filters_protobuf_account_not_missing_dataframe_column():
    g=gateway()
    class Handler:
        def on_recv_rsp(self,pb): return 0,Frame([row(trd_env="REAL")])
    g.sdk.TradeOrderHandlerBase=Handler
    g.sdk.TradeDealHandlerBase=Handler
    handlers=[]
    g.trade=NS(set_handler=handlers.append)
    g._handlers()
    handlers[0].on_recv_rsp(NS(s2c=NS(header=NS(accID=999))))
    assert not g.drain().orders
    handlers[0].on_recv_rsp(NS(s2c=NS(header=NS(accID=123456789))))
    assert len(g.drain().orders) == 1


def test_id_only_submission_response_preserves_identity_without_assuming_acceptance():
    g=gateway()
    g.trade=NS(place_order=lambda **_: (0,Frame([{'order_id':'known-id'}])))
    o=g.submit(Request('i','HK.00700','BUY','LIMIT',Decimal(100),Decimal(100)))
    assert o.id == 'known-id' and o.status == 'SUBMITTING' and not o.terminal


@pytest.mark.parametrize('transport',[False,True])
def test_push_errors_classify_transport_and_scoped_evidence(transport):
    from plumber.models import PushEvidenceError
    g=gateway()
    class Handler:
        def on_recv_rsp(self,pb):
            data=row(trd_env='REAL');data['qty']='invalid'
            return (1 if transport else 0),Frame([data])
    g.sdk.TradeOrderHandlerBase=Handler;g.sdk.TradeDealHandlerBase=Handler
    handlers=[];g.trade=NS(set_handler=handlers.append);g._handlers()
    handlers[0].on_recv_rsp(NS(s2c=NS(header=NS(accID=123456789))))
    with pytest.raises(Unavailable) as error:g.drain()
    assert isinstance(error.value,PushEvidenceError) is (not transport)
    if not transport:assert error.value.order_id=='o1'
