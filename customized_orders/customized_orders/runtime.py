"""Single account worker, private paper broker, and signal-driven wakeups."""
from contextlib import contextmanager
from dataclasses import asdict
from datetime import datetime
import fcntl
import json
import os
from pathlib import Path
import signal
import threading
from plumber.fake import FakeGateway
from plumber.models import Order, Deal, Snapshot, Unavailable, decimal
from .calendar import HKT


@contextmanager
def worker_lock(path):
    with open(path, "a+") as handle:
        os.chmod(path, 0o600)
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError("An execution worker is already running for this account and mode") from None
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


class PaperGateway(FakeGateway):
    """Private independent broker journal models process restarts without real trading."""
    def __init__(self,path,clock=lambda: datetime.now(HKT)):
        super().__init__()
        self.path, self.clock = Path(path), clock
        if self.path.is_symlink():
            raise ValueError("Paper journal must not be a symlink")
        if self.path.exists():
            data = json.loads(self.path.read_text())
            for r in data["orders"]:
                for k in ("quantity", "filled"):
                    r[k] = decimal(r[k])
                if r["price"] is not None:
                    r["price"] = decimal(r["price"])
                o = Order(**r)
                self.orders[o.id] = o
            for r in data["deals"]:
                r["quantity"],r["price"] = decimal(r["quantity"]),decimal(r["price"])
                d = Deal(**r)
                self.deals[d.id] = d

    def save(self):
        temporary = self.path.with_suffix(".tmp")
        fd = os.open(temporary,os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW,0o600)
        with os.fdopen(fd,"w") as f:
            json.dump({"orders":[asdict(o) for o in self.orders.values()],"deals":[asdict(d) for d in self.deals.values()]},f,default=str)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temporary,self.path)
        directory = os.open(self.path.parent,os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)

    def submit(self,r):
        result = super().submit(r)
        self.save()
        return result

    def cancel(self,oid):
        super().cancel(oid)
        self.save()

    def finish(self,oid,status):
        super().finish(oid,status)
        self.save()


class ShadowGateway(PaperGateway):
    """Real read-only health/capacity; every mutation goes to the private paper journal."""
    def __init__(self,path,reader):
        super().__init__(path)
        self.reader = reader

    def healthy(self,symbol,now):
        return self.reader.healthy(symbol,now)

    def capacity(self,symbol,side,kind,price):
        return self.reader.capacity(symbol,side,kind,price)

    def close(self):
        self.reader.close()


def make_gateway(settings, *, mutations=False):
    paper = settings.state_dir / settings.alias / settings.mode.lower() / "paper-broker.json"
    if settings.mode == "DRY_RUN":
        return PaperGateway(paper)
    from plumber.futu import FutuGateway
    reader = FutuGateway(settings.connection,allow_trading=mutations and settings.mode == "LIVE",
                         sdk_version=settings.sdk_version,lots={k:v["lot_size"] for k,v in settings.instruments.items()})
    return ShadowGateway(paper,reader) if settings.mode == "SHADOW" else reader


def emit(p,at,reason=None):
    # Only allowlisted, normalized fields. Never raw responses/configuration/exceptions.
    print(json.dumps({"at_hkt":at.isoformat(),"parent_order_id":p["id"],"account_alias":p["alias"],
                      "mode":p["mode"],"state":p["state"],"reason":reason or p["reason"],
                      "filled":p["filled"],"level":"ERROR" if p["state"] == "MANUAL_REVIEW" or reason else "INFO"}),flush=True)


def run(engine, *, once=False, interval=5):
    stop = threading.Event()
    old = {}
    for sig in (signal.SIGINT,signal.SIGTERM):
        old[sig] = signal.signal(sig,lambda *_: stop.set())
    last, warned = {}, set()
    failed = False
    try:
        while not stop.is_set():
            engine.cycle_snapshots = {}
            skip = engine.commands()
            ids = [r[0] for r in engine.store.db.execute("SELECT id FROM parents WHERE active=1")]
            try:
                events = engine.gateway.drain()
                engine.observe(events)
            except Unavailable:
                for pid in ids:
                    engine.manual(pid,"PUSH_STREAM_UNCERTAIN")
            for pid in ids:
                if pid in skip:
                    continue
                p = engine.store.parent(pid)
                try:
                    session = engine.calendar.session(p["day"])
                except ValueError:
                    # A missing historical date disables actions for this parent,
                    # not monitoring or unrelated parents in the same account.
                    session = None
                    engine.manual(pid, "CALENDAR_UNAVAILABLE")
                    try:
                        engine.reconcile(pid, for_cancel=True)
                    except (ValueError, Unavailable):
                        pass
                if session is not None:
                    # Paper mode expires unmatched orders; it does not invent fills.
                    if isinstance(engine.gateway, PaperGateway) and engine.time() >= session.close:
                        for c in engine.store.children(pid):
                            if c["broker_id"] in engine.gateway.orders:
                                o = engine.gateway.orders[c["broker_id"]]
                                if not o.terminal:
                                    engine.gateway.finish(o.id, "CANCELLED_PART" if o.filled else "CANCELLED_ALL")
                    engine.step(pid)
                p = engine.store.parent(pid)
                key = (p["state"],p["reason"],p["filled"])
                if last.get(pid) != key:
                    emit(p,engine.time())
                    last[pid] = key
                if p["state"] == "MANUAL_REVIEW":
                    failed = True
                if session is not None and p["active"] and engine.time() >= session.warning and not any(c["role"] == "AUCTION" and c["broker_id"] for c in engine.store.children(pid)) and pid not in warned:
                    emit(p,engine.time(),"CONVERSION_NOT_COMPLETE")
                    warned.add(pid)
            if once:
                return 2 if failed else 0
            stop.wait(interval)
        return 2 if failed else 0
    finally:
        for sig,handler in old.items():
            signal.signal(sig,handler)
