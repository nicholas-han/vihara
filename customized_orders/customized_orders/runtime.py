"""Single account worker, private paper broker, and signal-driven wakeups."""
from contextlib import contextmanager
from dataclasses import asdict
from datetime import datetime
import fcntl
import hashlib
import hmac
import secrets
import json
import os
from pathlib import Path
import signal
import threading
from plumber.fake import FakeGateway
from plumber.models import Order, Deal, Snapshot, Unavailable, PushEvidenceError, decimal
from .config import outside_git, private_file
from .calendar import HKT


@contextmanager
def worker_lock(path):
    fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "a+") as handle:
        os.fchmod(handle.fileno(), 0o600)
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError("An execution worker is already running for this account and mode") from None
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


@contextmanager
def live_account_lock(settings):
    """One LIVE worker per broker account on this host/user, across configs."""
    if settings.mode != "LIVE":
        yield
        return
    # Deliberately independent of config path, aliases, state_dir and OpenD port.
    directory = outside_git(Path.home() / ".local/state/vihara/account-locks")
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    info = directory.stat()
    if info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise ValueError("Account lock directory must be private and owned by you")
    with worker_lock(directory / "registry.lock"):
        key_path = directory / "identity.key"
        if not key_path.exists():
            fd = os.open(key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            with os.fdopen(fd, "wb") as handle:
                handle.write(secrets.token_bytes(32))
                handle.flush()
                os.fsync(handle.fileno())
        key = private_file(key_path).read_bytes()
        if len(key) != 32:
            raise ValueError("Invalid account lock identity key")
        fingerprint = hmac.new(key, ("futu:REAL:" + str(settings.connection.account_id)).encode(), hashlib.sha256).hexdigest()
    with worker_lock(directory / (fingerprint + ".lock")):
        yield


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


def hold_push_recovery(engine, ids):
    with engine.store.tx() as db:
        for pid in ids:
            db.execute("INSERT INTO push_recovery(parent,since) VALUES (?,NULL) ON CONFLICT(parent) DO UPDATE SET since=NULL", (pid,))
            db.execute("UPDATE parents SET quiet_since=NULL,signature=NULL WHERE id=?", (pid,))
            p = engine.store.parent(pid)
            if p["state"] != "MANUAL_REVIEW":
                try:
                    expired = engine.time() >= engine.calendar.session(p["day"]).deadline
                except ValueError:
                    engine.store.change(db, pid, "MANUAL_REVIEW", "CALENDAR_UNAVAILABLE", engine.time().isoformat())
                else:
                    engine.store.change(db, pid, "MANUAL_REVIEW" if expired else p["state"],
                                        "PUSH_RECOVERY_DEADLINE" if expired else "PUSH_STREAM_RECOVERING", engine.time().isoformat())


def recover_push_stream(engine, pid):
    row = engine.store.db.execute("SELECT since FROM push_recovery WHERE parent=?", (pid,)).fetchone()
    if row is None:
        return True
    p = engine.store.parent(pid)
    try:
        engine.reconcile(pid, for_cancel=bool(p["cancel_user"]))
        if not engine.gateway.healthy(p["symbol"], engine.time()):
            raise Unavailable("MARKET_UNVERIFIED")
    except (ValueError, Unavailable):
        hold_push_recovery(engine, [pid])
        if engine.time() >= engine.calendar.session(p["day"]).deadline:
            engine.manual(pid, "PUSH_RECOVERY_DEADLINE")
        return False
    # observe() clears quiet_since for any new durable push. Do not reuse a
    # quiet interval if evidence changed during recovery or process restart.
    p = engine.store.parent(pid)
    signature = json.dumps([(c["broker_id"], c["status"], c["filled"]) for c in engine.store.children(pid)])
    if row[0] is None or p["quiet_since"] is None or p["signature"] != signature:
        with engine.store.tx() as db:
            db.execute("UPDATE push_recovery SET since=? WHERE parent=?", (engine.time().isoformat(), pid))
            db.execute("UPDATE parents SET quiet_since=?,signature=? WHERE id=?", (engine.time().isoformat(), signature, pid))
        return False
    if engine.time() - datetime.fromisoformat(row[0]) < engine.quiet:
        return False
    with engine.store.tx() as db:
        db.execute("DELETE FROM push_recovery WHERE parent=?", (pid,))
    return True


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
            except PushEvidenceError as exc:
                # An identified, unrelated order cannot poison our parents. An
                # unidentified parse failure may affect the whole account.
                affected = ids if exc.order_id is None else [pid for pid in ids if any(
                    child["broker_id"] == exc.order_id for child in engine.store.children(pid))]
                if exc.order_id is not None and not affected and any(
                    child["broker_id"] is None for pid in ids for child in engine.store.children(pid)):
                    affected = ids  # Submission identity has not yet been recovered.
                for pid in affected:
                    engine.manual(pid,"PUSH_EVIDENCE_INVALID")
                # A failed drain may still contain buffered events: no actions
                # until a clean drain has delivered all evidence.
                hold_push_recovery(engine, ids)
                skip.update(ids)
            except Unavailable:
                hold_push_recovery(engine, ids)
                skip.update(ids)
            for pid in ids:
                if pid in skip:
                    p = engine.store.parent(pid)
                    key = (p["state"], p["reason"], p["filled"])
                    if last.get(pid) != key:
                        emit(p, engine.time())
                        last[pid] = key
                    if p["state"] == "MANUAL_REVIEW":
                        failed = True
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
                    if recover_push_stream(engine, pid):
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
