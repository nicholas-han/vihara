"""Deterministic adapter for replay tests and offline DRY_RUN. Never touches OpenD."""
from dataclasses import replace
from decimal import Decimal
from .models import Deal, Order, Snapshot, UnknownResult, Unavailable


class FakeGateway:
    def __init__(self):
        self.orders = {}
        self.deals = {}
        self.requests = []
        self.cancels = []
        self.connected = True
        self.delay_cancel = False
        self.timeout_submit = False
        self.available = Decimal("1000000000")

    def submit(self, r):
        self.requests.append(r)
        o = Order(str(len(self.orders) + 1), r.intent, r.symbol, r.side, r.kind,
                  r.quantity, r.price, Decimal(0), "SUBMITTED", False)
        self.orders[o.id] = o
        if self.timeout_submit:
            raise UnknownResult("SUBMISSION_RESULT_UNKNOWN")
        return o

    def cancel(self, order_id):
        self.cancels.append(order_id)
        if not self.delay_cancel:
            self.finish(order_id, "CANCELLED_ALL")

    def finish(self, order_id, status, source="UNKNOWN"):
        self.orders[order_id] = replace(self.orders[order_id], status=status, terminal=True, cancellation_source=source)

    def fill(self, order_id, deal_id, qty, price="100", at="2026-09-10T15:00:00+08:00"):
        self.deals[deal_id] = Deal(deal_id, order_id, Decimal(str(qty)), Decimal(str(price)), at)
        o = self.orders[order_id]
        filled = sum((x.quantity for x in self.deals.values() if x.order_id == order_id), Decimal(0))
        done = filled == o.quantity
        self.orders[order_id] = replace(o, filled=filled, status="FILLED_ALL" if done else "FILLED_PART", terminal=done)

    def snapshot(self, day):
        if not self.connected:
            raise Unavailable("BROKER_UNAVAILABLE")
        return Snapshot(tuple(self.orders.values()), tuple(self.deals.values()))

    def drain(self):
        return Snapshot((), ())

    def capacity(self, symbol, side, kind, price):
        return self.available

    def healthy(self, symbol, now):
        return self.connected

    def close(self):
        pass
