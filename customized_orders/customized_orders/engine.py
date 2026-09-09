"""Durable serial orchestration. Commit intent before every broker mutation."""
from datetime import datetime, timedelta
from dataclasses import asdict
import hashlib
from decimal import Decimal
import json
import re
import uuid
from plumber.models import Request, Snapshot, Unavailable, UnknownResult, decimal
from .calendar import HKT
from .store import TERMINAL


class EvidenceError(ValueError):
    pass


class Engine:
    def __init__(self, store, gateway, settings, calendar, now, quiet_seconds=1, recover=True):
        if quiet_seconds < 0:
            raise ValueError("Invalid reconciliation quiet period")
        self.store, self.gateway, self.settings, self.calendar = store, gateway, settings, calendar
        self.now, self.quiet = now, timedelta(seconds=quiet_seconds)
        self.cycle_snapshots = None
        self.store.bind(settings.alias, settings.mode)
        # A restart cannot inherit an unobserved quiet period.
        if recover:
            with store.tx() as db:
                db.execute("UPDATE parents SET quiet_since=NULL,signature=NULL WHERE active=1")

    def time(self):
        n = self.now()
        if n.tzinfo is None:
            raise ValueError("Clock must be timezone-aware")
        return n.astimezone(HKT)

    def risk(self, p, role):
        cfg = self.settings
        if not re.fullmatch(r"HK\.[0-9]{5}", p["symbol"]) or p["side"] not in {"BUY", "SELL"}:
            raise ValueError("Unsupported symbol or side")
        info = cfg.instruments.get(p["symbol"], {})
        if info.get("cas") is not True or info.get("verified_for") != p["day"] or not info.get("source"):
            raise ValueError("CAS eligibility or instrument evidence unavailable for trade date")
        lot = decimal(info.get("lot_size", 0))
        qty = decimal(p["quantity"]) - (decimal(p.get("filled", "0")) if role == "AUCTION" else 0)
        price = decimal(p["price"])
        tick = decimal(info.get("tick_size", 0))
        if lot <= 0 or lot != lot.to_integral_value() or qty <= 0 or qty % lot or qty > cfg.max_quantity:
            raise ValueError("Quantity violates lot size or configured limit")
        if tick <= 0 or price <= 0 or price % tick:
            raise ValueError("Invalid limit price tick")
        if not decimal(info.get("tick_lower", "0")) <= price <= decimal(info.get("tick_upper", "0")):
            raise ValueError("Price outside verified tick band")
        auction_estimate = decimal(info.get("auction_risk_price", 0))
        if auction_estimate <= 0:
            raise ValueError("A verified conservative auction risk price is required")
        estimate = max(price, auction_estimate)
        if estimate <= 0 or qty * estimate > cfg.max_notional:
            raise ValueError("Notional exceeds configured limit")
        if not self.gateway.healthy(p["symbol"], self.time()):
            raise Unavailable("MARKET_OR_CLOCK_UNVERIFIED")
        if self.gateway.capacity(p["symbol"], p["side"], role, estimate) < qty:
            raise ValueError("Insufficient available buying power or sellable position")
        return qty

    def create(self, symbol, side, quantity, price, day):
        p = dict(id=uuid.uuid4().hex, alias=self.settings.alias, mode=self.settings.mode,
                 symbol=symbol, side=side, quantity=str(decimal(quantity)), price=str(decimal(price)), day=day)
        if not self.calendar.session(day).continuous(self.time()):
            raise ValueError("Create is allowed only during the requested day's continuous session")
        self.risk(p, "LIMIT")
        with self.store.tx() as db:
            db.execute("INSERT INTO parents(id,alias,mode,symbol,side,quantity,price,day,state) VALUES (:id,:alias,:mode,:symbol,:side,:quantity,:price,:day,'ARMED')", p)
            db.execute("INSERT INTO transitions(parent,previous,next,reason,at) VALUES (?,'DRAFT','ARMED','USER_CONFIRMED',?)", (p["id"], self.time().isoformat()))
        return p["id"]

    def state(self, pid, state, reason):
        with self.store.tx() as db:
            self.store.change(db, pid, state, reason, self.time().isoformat())

    def manual(self, pid, reason):
        self.state(pid, "MANUAL_REVIEW", reason)

    def ingest(self, pid, snap, *, for_cancel=False):
        """Authoritative snapshots must agree with the append-only deduplicated deals."""
        p = self.store.parent(pid)
        children = self.store.children(pid)
        seen_ids = set()
        with self.store.tx() as db:
            push_evidence = [json.loads(r[0]) for r in db.execute(
                "SELECT payload FROM events WHERE parent=?", (pid,)
            )]
            for c in children:
                matches = [o for o in snap.orders if o.id == c["broker_id"] or o.intent == c["intent"]]
                unique = {o.id: o for o in matches}
                if len(unique) != 1:
                    raise EvidenceError("ORDER_IDENTITY_UNCERTAIN")
                o = next(iter(unique.values()))
                if c["broker_id"] and c["broker_id"] != o.id:
                    raise EvidenceError("DUPLICATE_CHILD_ORDER")
                if o.id in seen_ids:
                    raise EvidenceError("DUPLICATE_CHILD_ORDER")
                seen_ids.add(o.id)
                # Cancellation is risk-reducing: known identity remains mandatory,
                # but a user's price/quantity edit must not prevent explicit withdrawal.
                if o.symbol != p["symbol"] or o.side != p["side"]:
                    raise EvidenceError("EXTERNAL_ORDER_MODIFICATION")
                if not for_cancel:
                    allowed_kind = {c["role"]}
                    if c["role"] == "LIMIT" and self.time() >= self.calendar.session(p["day"]).cas_start:
                        allowed_kind.add("AUCTION_LIMIT")
                    if (o.kind not in allowed_kind or o.quantity != decimal(c["quantity"])
                        or (c["role"] == "LIMIT" and o.price != decimal(c["price"]))):
                        raise EvidenceError("EXTERNAL_ORDER_MODIFICATION")
                self.check_push_evidence(o, snap, push_evidence)
                if decimal(c["filled"]) > o.filled or (c["terminal"] and not o.terminal):
                    raise EvidenceError("ORDER_STATUS_REGRESSION")
                for d in snap.deals:
                    if d.order_id != o.id:
                        continue
                    if d.quantity <= 0 or d.price <= 0:
                        raise EvidenceError("INVALID_EXECUTION")
                    old = db.execute("SELECT child,quantity,price,at FROM executions WHERE parent=? AND deal_id=?", (pid,d.id)).fetchone()
                    values = (c["id"],str(d.quantity),str(d.price),d.at)
                    if old and (old[0] != values[0] or decimal(old[1]) != d.quantity or decimal(old[2]) != d.price or old[3] != d.at):
                        raise EvidenceError("EXECUTION_CONFLICT")
                    db.execute("INSERT OR IGNORE INTO executions VALUES (?,?,?,?,?,?)", (pid,d.id,*values))
                dealt = sum((decimal(r[0]) for r in db.execute("SELECT quantity FROM executions WHERE child=?", (c["id"],))), Decimal(0))
                if dealt != o.filled or dealt < 0 or dealt > o.quantity:
                    raise EvidenceError("FILLED_QUANTITY_CONFLICT")
                db.execute("UPDATE children SET broker_id=?,status=?,terminal=?,filled=?,cancellation_source=? WHERE id=?", (o.id,o.status,int(o.terminal),str(o.filled),o.cancellation_source,c["id"]))
            executions = list(db.execute("SELECT quantity,price FROM executions WHERE parent=?", (pid,)))
            total = sum((decimal(r[0]) for r in executions), Decimal(0))
            if total < 0 or total > decimal(p["quantity"]):
                raise EvidenceError("OVERFILL")
            cost = sum((decimal(r[0])*decimal(r[1]) for r in executions), Decimal(0))
            db.execute("UPDATE parents SET filled=?,average_price=?,last_reconciled=? WHERE id=?", (str(total),str(cost/total) if total else None,self.time().isoformat(),pid))
        return self.store.parent(pid)

    @staticmethod
    def check_push_evidence(order, snapshot, evidence):
        """A quiet interval cannot override a known disagreement with a push."""
        queried = {d.id: d for d in snapshot.deals if d.order_id == order.id}
        for event in evidence:
            if event.get("order_id") == order.id:
                deal = queried.get(event["id"])
                if deal is None:
                    raise EvidenceError("FILLED_QUANTITY_CONFLICT")
                if (decimal(event["quantity"]) != deal.quantity
                    or decimal(event["price"]) != deal.price or event["at"] != deal.at):
                    raise EvidenceError("EXECUTION_CONFLICT")
            elif "intent" in event and event["id"] == order.id:
                if decimal(event["filled"]) > order.filled:
                    raise EvidenceError("FILLED_QUANTITY_CONFLICT")
                if event["terminal"] and not order.terminal:
                    raise EvidenceError("ORDER_STATUS_REGRESSION")

    def snapshot(self, day):
        if self.cycle_snapshots is None:
            return self.gateway.snapshot(day)
        if day not in self.cycle_snapshots:
            self.cycle_snapshots[day] = self.gateway.snapshot(day)
        return self.cycle_snapshots[day]

    def reconcile(self, pid, *, for_cancel=False):
        p = self.store.parent(pid)
        return self.ingest(pid, self.snapshot(p["day"]), for_cancel=for_cancel)

    def observe(self, events):
        """Keep normalized push evidence for tracked children only; dedupe atomically."""
        for event in (*events.orders,*events.deals):
            order_id = getattr(event,"order_id",None) or event.id
            intent = getattr(event,"intent","")
            c = self.store.db.execute("SELECT * FROM children WHERE broker_id=? OR intent=?",(order_id,intent)).fetchone()
            if c is None and hasattr(event, "order_id"):
                # A deal push may precede saving the synchronous response ID. A
                # previously correlated order push still identifies that child.
                c = self.store.db.execute(
                    "SELECT children.* FROM children JOIN events ON events.parent=children.parent "
                    "WHERE json_extract(events.payload,'$.id')=? "
                    "AND json_extract(events.payload,'$.intent')=children.intent",
                    (order_id,),
                ).fetchone()
            if c is None:
                continue
            safe_event = asdict(event)
            if "intent" in safe_event:
                safe_event["intent"] = c["intent"]
            payload = json.dumps(safe_event,default=str,sort_keys=True)
            fingerprint = hashlib.sha256(payload.encode()).hexdigest()
            with self.store.tx() as db:
                added = db.execute("INSERT OR IGNORE INTO events VALUES (?,?,?,?)",(fingerprint,c["parent"],payload,self.time().isoformat())).rowcount
                if added:
                    db.execute("UPDATE parents SET quiet_since=NULL,signature=NULL WHERE id=?",(c["parent"],))
            # ingest() checks these durable observations against every snapshot.

    def submit(self, pid, role):
        p = self.store.parent(pid)
        qty = self.risk(p, role)
        if role == "AUCTION":
            # Network preflight may deliver new pushes after the cycle snapshot.
            self.observe(self.gateway.drain())
            if self.store.parent(pid)["quiet_since"] is None:
                return
        session = self.calendar.session(p["day"])
        # Re-read the clock after potentially slow network validation.
        now = self.time()
        if role == "AUCTION" and not session.transition <= now < session.deadline:
            self.manual(pid, "SUBMISSION_DEADLINE")
            return
        if role == "LIMIT" and not session.continuous(now):
            self.state(pid, "FAILED", "CONTINUOUS_SESSION_ENDED")
            return
        intent = "lwm:" + uuid.uuid4().hex
        child = uuid.uuid4().hex
        price = decimal(p["price"]) if role == "LIMIT" else None
        with self.store.tx() as db:
            db.execute("INSERT INTO children(id,parent,role,intent,quantity,price,status) VALUES (?,?,?,?,?,?,'SUBMITTING')", (child,pid,role,intent,str(qty),str(price) if price is not None else None))
            self.store.change(db,pid,"AUCTION_SUBMITTING" if role == "AUCTION" else "ARMED","INTENT_PERSISTED",now.isoformat())
        # Recheck immediately before the external side effect, including transaction latency.
        if role == "AUCTION" and self.time() >= session.deadline:
            self.manual(pid, "SUBMISSION_DEADLINE")
            return
        try:
            o = self.gateway.submit(Request(intent,p["symbol"],p["side"],role,qty,price))
        except (Unavailable, UnknownResult):
            return  # Intent remains durable; next tick queries, never resubmits.
        if not o.id:
            self.manual(pid,"SUBMISSION_RESULT_UNKNOWN")
            return
        with self.store.tx() as db:
            db.execute("UPDATE children SET broker_id=? WHERE id=?", (o.id,child))
        if o.intent and o.intent != intent:
            self.manual(pid, "SUBMISSION_REMARK_MISMATCH")
        # An absent remark does not invalidate a known broker-assigned ID.
        # A successful return is not enough: validate broker state on the next snapshot.

    def request_cancel(self, pid, c):
        c = next(child for child in self.store.children(pid) if child["id"] == c["id"])
        if c["cancel_phase"] in {"ATTEMPTING", "UNKNOWN"}:
            self.manual(pid, "CANCELLATION_RESULT_UNKNOWN_CHECK_BROKER")
            return
        if c["cancel_phase"] == "ACKNOWLEDGED":
            return
        if c["cancel_phase"] == "NONE":
            with self.store.tx() as db:
                db.execute("UPDATE children SET cancel_sent=1,cancel_phase='INTENT' WHERE id=?", (c["id"],))
                self.store.change(db,pid,"CANCEL_REQUESTED","CANCEL_INTENT_PERSISTED",self.time().isoformat())
        # INTENT is definitely pre-call and can resume. Once ATTEMPTING commits,
        # a crash has an ambiguous outcome; never infer that a working order means
        # the broker did not receive the request.
        with self.store.tx() as db:
            db.execute("UPDATE children SET cancel_phase='ATTEMPTING' WHERE id=?", (c["id"],))
        try:
            self.gateway.cancel(c["broker_id"])
        except Unavailable:
            with self.store.tx() as db:
                db.execute("UPDATE children SET cancel_phase='UNKNOWN' WHERE id=?", (c["id"],))
            self.manual(pid, "CANCELLATION_RESULT_UNKNOWN_CHECK_BROKER")
        else:
            with self.store.tx() as db:
                db.execute("UPDATE children SET cancel_phase='ACKNOWLEDGED' WHERE id=?", (c["id"],))

    def step(self, pid):
        p = self.store.parent(pid)
        if p["state"] in TERMINAL:
            return
        try:
            self._step(pid)
        except EvidenceError as exc:
            # Transient query/push skew can converge; no mutations during conflict.
            reason = str(exc)
            if reason in {"FILLED_QUANTITY_CONFLICT", "ORDER_STATUS_REGRESSION"}:
                with self.store.tx() as db:
                    db.execute("UPDATE parents SET quiet_since=NULL,signature=NULL WHERE id=?", (pid,))
                session = self.calendar.session(p["day"])
                if self.time() < session.deadline and p["reason"] != reason:
                    self.state(pid,self.store.parent(pid)["state"],reason)
                    return
            self.manual(pid,reason)
        except Unavailable:
            with self.store.tx() as db:
                db.execute("UPDATE parents SET quiet_since=NULL,signature=NULL WHERE id=?", (pid,))
            session = self.calendar.session(p["day"])
            if self.time() >= session.deadline:
                self.manual(pid,"BROKER_UNAVAILABLE_AT_DEADLINE")
            else:
                self.state(pid,self.store.parent(pid)["state"],"BROKER_UNAVAILABLE")
        except ValueError:
            self.manual(pid,"VALIDATION_OR_RISK_FAILED")

    def _step(self, pid):
        p = self.store.parent(pid)
        session = self.calendar.session(p["day"])
        children = self.store.children(pid)
        if not children:
            if p["cancel_user"]:
                self.state(pid,"CANCELLED_BY_USER","NO_CHILD_SUBMITTED")
            elif p["state"] == "MANUAL_REVIEW":
                return
            elif p["state"] == "ARMED":
                self.submit(pid,"LIMIT")
            return
        if p["cancel_user"]:
            self.cancel_user(pid, session, children)
            return
        p = self.reconcile(pid)
        children = self.store.children(pid)
        if p["state"] == "MANUAL_REVIEW" and not p["cancel_user"]:
            return  # Continue evidence collection without automatic trading actions.
        now = self.time()
        all_terminal = all(c["terminal"] for c in children)
        remaining = decimal(p["quantity"]) - decimal(p["filled"])
        if remaining == 0 and all_terminal:
            self.state(pid,"COMPLETED","TARGET_FILLED")
            return
        auction = next((c for c in children if c["role"] == "AUCTION"),None)
        if auction:
            if auction["status"] in {"FAILED", "SUBMIT_FAILED", "DISABLED", "DELETED"}:
                self.manual(pid,"AUCTION_REJECTED_OR_INVALID")
            elif now >= session.close and all_terminal:
                self.finish(pid,p)
            elif now >= session.close + timedelta(minutes=5) and not all_terminal:
                self.manual(pid,"CLOSING_ORDER_NOT_TERMINAL")
            else:
                self.state(pid,"AUCTION_WORKING","UNIQUE_AUCTION_CONFIRMED")
            return
        c = children[0]
        if now < session.transition:
            if c["terminal"]:
                self.manual(pid,"LIMIT_STOPPED_BEFORE_TRANSITION")
            else:
                self.state(pid,"LIMIT_WORKING","LIMIT_CONFIRMED")
            return
        if now >= session.deadline:
            self.manual(pid,"SUBMISSION_DEADLINE")
            return
        if p["state"] in {"ARMED","LIMIT_WORKING"}:
            self.state(pid,"TRANSITION_DUE","CONVERSION_WINDOW_OPEN")
        if not c["terminal"]:
            if not self.gateway.healthy(p["symbol"],now):
                raise Unavailable("MARKET_UNVERIFIED")
            self.request_cancel(pid,c)
            return
        if c["status"] not in {"CANCELLED_ALL", "CANCELLED_PART", "FILLED_ALL"}:
            self.manual(pid,"LIMIT_REJECTED_OR_INVALID")
            return
        if not c["cancel_sent"] and c["status"].startswith("CANCELLED") and c["cancellation_source"] != "EXCHANGE":
            self.manual(pid,"UNATTRIBUTED_CANCELLATION")
            return
        signature = json.dumps([(x["broker_id"],x["status"],x["filled"]) for x in children])
        if p["signature"] != signature or p["quiet_since"] is None:
            with self.store.tx() as db:
                db.execute("UPDATE parents SET signature=?,quiet_since=? WHERE id=?", (signature,now.isoformat(),pid))
                self.store.change(db,pid,"RECONCILING","TERMINAL_SNAPSHOT",now.isoformat())
            return
        if now - datetime.fromisoformat(p["quiet_since"]) < self.quiet:
            return
        self.submit(pid,"AUCTION")

    def cancel_user(self, pid, session, children):
        """Explicit withdrawal is gated by identity and phase, not original terms."""
        p = self.store.parent(pid)
        snap = self.snapshot(p["day"])
        matched = []
        used_ids = set()
        for child in children:
            orders = {o.id: o for o in snap.orders
                      if o.id == child["broker_id"] or o.intent == child["intent"]}
            if len(orders) != 1:
                raise EvidenceError("ORDER_IDENTITY_UNCERTAIN")
            order = next(iter(orders.values()))
            if (order.id in used_ids or (child["broker_id"] and order.id != child["broker_id"])
                or order.symbol != p["symbol"] or order.side != p["side"]):
                raise EvidenceError("ORDER_IDENTITY_UNCERTAIN")
            used_ids.add(order.id)
            with self.store.tx() as db:
                db.execute("UPDATE children SET broker_id=? WHERE id=?", (order.id, child["id"]))
            matched.append(({**child, "broker_id": order.id}, order))

        evidence_error = None
        try:
            p = self.ingest(pid, snap, for_cancel=True)
        except EvidenceError as exc:
            # Even an overfill or incomplete deal stream must not prevent a
            # user from withdrawing the identified remainder. Do not claim a
            # final outcome until financial evidence converges.
            evidence_error = str(exc)

        now = self.time()
        working = [(c, o) for c, o in matched if not o.terminal]
        if working:
            if now >= session.no_cancel:
                if now >= session.close + timedelta(minutes=5):
                    self.manual(pid, "CLOSING_ORDER_NOT_TERMINAL")
                else:
                    self.state(pid, self.store.parent(pid)["state"], "CANNOT_CANCEL_CONTINUE_TRACKING")
            else:
                for child, _ in working:
                    self.request_cancel(pid, child)
            if evidence_error:
                self.manual(pid, evidence_error)
            return
        if evidence_error:
            self.manual(pid, evidence_error)
            return
        if p["state"] == "MANUAL_REVIEW":
            self.state(pid, "CANCEL_REQUESTED", "USER_CANCEL_RECONCILED")
        if decimal(p["filled"]) == decimal(p["quantity"]):
            self.state(pid, "COMPLETED", "TARGET_FILLED")
        elif now >= session.no_cancel and not children[-1]["cancel_sent"]:
            if now >= session.close:
                self.finish(pid, p)
            else:
                self.manual(pid, "ORDER_STOPPED_WITHOUT_CONFIRMED_USER_CANCEL")
        else:
            self.state(pid, "CANCELLED_BY_USER", "ALL_CHILDREN_STOPPED")

    def finish(self,pid,p):
        filled = decimal(p["filled"])
        self.state(pid,"PARTIALLY_FILLED" if filled else "UNFILLED","CLOSE_RECONCILED")

    def commands(self):
        read_only = set()
        for cmd in self.store.db.execute("SELECT * FROM commands WHERE done=0 ORDER BY rowid").fetchall():
            pid = cmd["parent"]
            if cmd["action"] == "reconcile":
                try:
                    self.reconcile(pid)
                except (ValueError, Unavailable):
                    read_only.add(pid)
                    self.manual(pid,"RECONCILIATION_UNCERTAIN")
            with self.store.tx() as db:
                if cmd["action"] == "cancel":
                    db.execute("UPDATE parents SET cancel_user=1 WHERE id=?", (pid,))
                elif cmd["action"] == "acknowledge":
                    db.execute("UPDATE parents SET acknowledged=? WHERE id=?", (cmd["payload"],pid))
                db.execute("UPDATE commands SET done=1 WHERE id=?", (cmd["id"],))
        return read_only
