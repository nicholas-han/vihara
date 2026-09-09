"""Futu SDK adapter. Credentials are injected, never loaded or persisted here."""
from datetime import datetime
from decimal import Decimal
from importlib.metadata import version
import inspect
import logging
import os
from queue import SimpleQueue, Empty
from zoneinfo import ZoneInfo
from .models import Deal, Order, Snapshot, Unavailable, UnknownResult, PushEvidenceError, decimal

HKT = ZoneInfo("Asia/Hong_Kong")
TERMINAL = {"FILLED_ALL", "CANCELLED_PART", "CANCELLED_ALL", "SUBMIT_FAILED", "FAILED", "DISABLED", "DELETED"}


class FutuGateway:
    def __init__(self, connection, *, allow_trading=False, sdk_version="10.10.7008", lots=None):
        # Suppress SDK raw diagnostic payloads before a connection exists.
        for name in ("FTFileLog", "FTConsoleLog"):
            logging.getLogger(name).disabled = True
        import futu
        if version("futu-api") != sdk_version or sdk_version != "10.10.7008":
            raise Unavailable("UNVERIFIED_SDK_VERSION")
        required = {"place_order": {"remark", "acc_id", "time_in_force"},
                    "order_list_query": {"refresh_cache", "acc_id"},
                    "deal_list_query": {"refresh_cache", "acc_id"},
                    "history_order_list_query": {"start", "end", "acc_id"},
                    "history_deal_list_query": {"start", "end", "acc_id"},
                    "acctradinginfo_query": {"order_type", "price", "acc_id"}}
        for method, args in required.items():
            if not args <= set(inspect.signature(getattr(futu.OpenSecTradeContext,method)).parameters):
                raise Unavailable("UNVERIFIED_SDK_SIGNATURE")
        for status in TERMINAL:
            if not hasattr(futu.OrderStatus,status):
                raise Unavailable("UNVERIFIED_ORDER_STATUS")
        # Remote unencrypted OpenD is deliberately outside this local MVP.
        if connection.host not in {"127.0.0.1", "localhost", "::1"}:
            raise Unavailable("LOCAL_OPEND_REQUIRED")
        self.sdk, self._connection = futu, connection
        self.allow_trading, self.lots = allow_trading, lots or {}
        self.events = SimpleQueue()
        self.trade = self.quote = None
        futu.SysConfig.enable_console_log(False)
        try:
            self.trade = futu.OpenSecTradeContext(filter_trdmarket=futu.TrdMarket.HK,host=connection.host,port=connection.port)
            self.quote = futu.OpenQuoteContext(host=connection.host,port=connection.port)
            accounts = self._call(self.trade.get_acc_list)
            matches = [a for a in accounts.to_dict("records") if int(a["acc_id"]) == connection.account_id]
            if len(matches) != 1 or matches[0]["trd_env"] != futu.TrdEnv.REAL or futu.TrdMarket.HK not in matches[0]["trdmarket_auth"]:
                raise Unavailable("ACCOUNT_OR_MARKET_PERMISSION_MISMATCH")
            self._handlers()
            if allow_trading and connection.unlock_env:
                password = os.environ.get(connection.unlock_env)
                if not password:
                    raise Unavailable("UNLOCK_SECRET_UNAVAILABLE")
                try:
                    self._call(self.trade.unlock_trade, password=password)
                finally:
                    password = None
        except Exception:
            self.close()
            raise Unavailable("FUTU_STARTUP_FAILED_CHECK_PRIVATE_CONFIGURATION") from None

    def _args(self):
        return dict(acc_id=self._connection.account_id,trd_env=self.sdk.TrdEnv.REAL)

    def _call(self, fn, **kwargs):
        try:
            ret, data = fn(**kwargs)
            if ret != self.sdk.RET_OK:
                raise Unavailable("FUTU_REQUEST_FAILED")
            return data
        except Exception:
            # Never interpolate SDK exceptions: they may contain account IDs/passwords.
            raise Unavailable("FUTU_REQUEST_FAILED") from None

    def _order(self, r):
        kind = {self.sdk.OrderType.NORMAL:"LIMIT",self.sdk.OrderType.AUCTION:"AUCTION",self.sdk.OrderType.AUCTION_LIMIT:"AUCTION_LIMIT"}.get(r["order_type"],"UNKNOWN")
        status = str(r["order_status"])
        remark = str(r.get("remark", ""))
        if remark in {"None", "nan", "N/A"}:
            remark = ""
        return Order(str(r["order_id"]),remark,str(r["code"]),str(r["trd_side"]),kind,
                     decimal(r["qty"]),None if kind == "AUCTION" else decimal(r["price"]),decimal(r["dealt_qty"]),status,status in TERMINAL)

    def _deal(self, r):
        if r.get("status", "OK") not in {"OK", "NORMAL", ""}:
            raise Unavailable("EXECUTION_CORRECTION_REQUIRES_REVIEW")
        at = datetime.fromisoformat(str(r["create_time"]))
        if at.tzinfo is None:
            at = at.replace(tzinfo=HKT)
        return Deal(str(r["deal_id"]),str(r["order_id"]),decimal(r["qty"]),decimal(r["price"]),at.isoformat())

    def _handlers(self):
        owner, sdk = self, self.sdk
        def collect(pb, data, parse):
            try:
                if int(pb.s2c.header.accID) != owner._connection.account_id:
                    return
                rows = data.to_dict("records")
            except Exception:
                owner.events.put(PushEvidenceError("INVALID_PUSH_HEADER"))
                return
            for row in rows:
                if row.get("trd_env") != sdk.TrdEnv.REAL:
                    continue
                try:
                    owner.events.put(parse(row))
                except Exception:
                    oid = row.get("order_id")
                    owner.events.put(PushEvidenceError("INVALID_PUSH_EVIDENCE", str(oid) if oid else None))

        class Orders(sdk.TradeOrderHandlerBase):
            def on_recv_rsp(self, pb):
                ret, data = super().on_recv_rsp(pb)
                if ret == sdk.RET_OK:
                    collect(pb, data, owner._order)
                else:
                    owner.events.put(Unavailable("ORDER_PUSH_FAILED"))
                return ret, data
        class Deals(sdk.TradeDealHandlerBase):
            def on_recv_rsp(self, pb):
                ret, data = super().on_recv_rsp(pb)
                if ret == sdk.RET_OK:
                    collect(pb, data, owner._deal)
                else:
                    owner.events.put(Unavailable("DEAL_PUSH_FAILED"))
                return ret, data
        self.trade.set_handler(Orders())
        self.trade.set_handler(Deals())

    def drain(self):
        # Preserve already-drained evidence when a later item reports an error.
        # The next clean drain returns it together with subsequent events.
        pending = getattr(self, "_pending_pushes", [])
        self._pending_pushes = pending
        while True:
            try:
                item = self.events.get_nowait()
            except Empty:
                break
            if isinstance(item, Exception):
                raise item
            pending.append(item)
        result = Snapshot(tuple(x for x in pending if isinstance(x, Order)),
                          tuple(x for x in pending if isinstance(x, Deal)))
        self._pending_pushes = []
        return result

    def snapshot(self, day):
        args = self._args()
        today = datetime.now(HKT).date().isoformat()
        if day == today:
            orders = self._call(self.trade.order_list_query,start=day + " 00:00:00",end=day + " 23:59:59",refresh_cache=True,**args)
            deals = self._call(self.trade.deal_list_query,refresh_cache=True,**args)
        else:
            orders = self._call(self.trade.history_order_list_query,start=day,end=day,**args)
            deals = self._call(self.trade.history_deal_list_query,start=day,end=day,**args)
        try:
            return Snapshot(tuple(self._order(r) for r in orders.to_dict("records")),tuple(self._deal(r) for r in deals.to_dict("records")))
        except Exception:
            raise Unavailable("INVALID_BROKER_EVIDENCE") from None

    def submit(self,r):
        if not self.allow_trading:
            raise Unavailable("TRADING_DISABLED")
        try:
            data = self._call(self.trade.place_order,price=float(r.price or 0),qty=float(r.quantity),code=r.symbol,
                              trd_side=getattr(self.sdk.TrdSide,r.side),order_type=self.sdk.OrderType.AUCTION if r.kind == "AUCTION" else self.sdk.OrderType.NORMAL,
                              remark=r.intent,time_in_force=self.sdk.TimeInForce.DAY,adjust_limit=0,**self._args())
            rows = data.to_dict("records")
            if len(rows) != 1:
                raise Unavailable("INVALID_SUBMISSION_RESPONSE")
            try:
                return self._order(rows[0])
            except (ValueError,KeyError,TypeError):
                # The SDK can return only an ID if its post-submit lookup is delayed.
                # Preserve that ID, but never infer fills or acceptance from this response.
                oid = rows[0].get("order_id")
                if oid is None or str(oid) in {"", "nan", "N/A"}:
                    raise Unavailable("INVALID_SUBMISSION_RESPONSE")
                return Order(str(oid),r.intent,r.symbol,r.side,r.kind,r.quantity,r.price,Decimal(0),"SUBMITTING",False)
        except Exception:
            raise UnknownResult("SUBMISSION_RESULT_UNKNOWN") from None

    def cancel(self,order_id):
        if not self.allow_trading:
            raise Unavailable("TRADING_DISABLED")
        try:
            self._call(self.trade.modify_order,modify_order_op=self.sdk.ModifyOrderOp.CANCEL,order_id=order_id,qty=0,price=0,**self._args())
        except Exception:
            raise UnknownResult("CANCELLATION_RESULT_UNKNOWN") from None

    def capacity(self,symbol,side,kind,price):
        data = self._call(self.trade.acctradinginfo_query,order_type=self.sdk.OrderType.AUCTION if kind == "AUCTION" else self.sdk.OrderType.NORMAL,
                          code=symbol,price=float(price),**self._args())
        try:
            rows = data.to_dict("records")
            if len(rows) != 1:
                raise ValueError()
            return decimal(rows[0]["max_cash_buy" if side == "BUY" else "max_position_sell"])
        except Exception:
            raise Unavailable("CAPACITY_UNVERIFIED") from None

    def healthy(self,symbol,now):
        state = self._call(self.quote.get_global_state)
        try:
            if state["trd_logined"] is not True or state["qot_logined"] is not True:
                return False
            if abs(decimal(state["timestamp"]) - decimal(now.timestamp())) > 5:
                return False
            rows = self._call(self.quote.get_market_state,code_list=[symbol]).to_dict("records")
            if len(rows) != 1 or rows[0]["market_state"] not in {self.sdk.MarketState.MORNING,self.sdk.MarketState.AFTERNOON,self.sdk.MarketState.HK_CAS}:
                return False
            if now.hour in {12,16} and 1 <= now.minute < 6 and rows[0]["market_state"] != self.sdk.MarketState.HK_CAS:
                return False
            snap = self._call(self.quote.get_market_snapshot,code_list=[symbol]).to_dict("records")
            return (len(snap) == 1 and snap[0]["suspension"] == False
                    and decimal(snap[0]["lot_size"]) == decimal(self.lots[symbol]))
        except (KeyError, ValueError, TypeError):
            return False

    def close(self):
        for ctx in (self.trade,self.quote):
            if ctx is not None:
                try:
                    ctx.close()
                except Exception:
                    pass
