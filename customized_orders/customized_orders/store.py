"""Canonical execution journal, separate from accounting. Only account aliases stored."""
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import hashlib
import hmac
import secrets
import os
from pathlib import Path
import sqlite3
import uuid

SCHEMA = """
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS account_binding(id INTEGER PRIMARY KEY CHECK(id=1), fingerprint TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS parents(
 id TEXT PRIMARY KEY, alias TEXT NOT NULL, mode TEXT NOT NULL, symbol TEXT NOT NULL,
 side TEXT NOT NULL, quantity TEXT NOT NULL, price TEXT NOT NULL, day TEXT NOT NULL,
 state TEXT NOT NULL, filled TEXT NOT NULL DEFAULT '0', average_price TEXT,
 reason TEXT, last_reconciled TEXT, quiet_since TEXT, signature TEXT,
 cancel_user INTEGER NOT NULL DEFAULT 0, active INTEGER NOT NULL DEFAULT 1,
 version INTEGER NOT NULL DEFAULT 0, acknowledged TEXT);
CREATE UNIQUE INDEX IF NOT EXISTS no_conflict ON parents(alias,mode,symbol,side,day) WHERE active=1;
CREATE TABLE IF NOT EXISTS children(
 id TEXT PRIMARY KEY, parent TEXT NOT NULL REFERENCES parents(id), role TEXT NOT NULL,
 intent TEXT NOT NULL UNIQUE, broker_id TEXT UNIQUE, quantity TEXT NOT NULL, price TEXT,
 status TEXT NOT NULL, terminal INTEGER NOT NULL DEFAULT 0, filled TEXT NOT NULL DEFAULT '0',
 cancel_sent INTEGER NOT NULL DEFAULT 0, cancellation_source TEXT NOT NULL DEFAULT 'UNKNOWN', UNIQUE(parent,role));
CREATE TABLE IF NOT EXISTS executions(
 parent TEXT NOT NULL REFERENCES parents(id), deal_id TEXT NOT NULL, child TEXT NOT NULL REFERENCES children(id),
 quantity TEXT NOT NULL, price TEXT NOT NULL, at TEXT NOT NULL, PRIMARY KEY(parent,deal_id));
CREATE TABLE IF NOT EXISTS transitions(
 seq INTEGER PRIMARY KEY, parent TEXT NOT NULL REFERENCES parents(id), previous TEXT NOT NULL,
 next TEXT NOT NULL, reason TEXT NOT NULL, at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS events(
 fingerprint TEXT PRIMARY KEY,parent TEXT NOT NULL REFERENCES parents(id),payload TEXT NOT NULL,at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS commands(
 id TEXT PRIMARY KEY, parent TEXT NOT NULL REFERENCES parents(id), action TEXT NOT NULL,
 payload TEXT NOT NULL, done INTEGER NOT NULL DEFAULT 0);
"""
TERMINAL = {"COMPLETED", "PARTIALLY_FILLED", "UNFILLED", "CANCELLED_BY_USER", "FAILED"}

ALLOWED = {
    "ARMED": {"LIMIT_WORKING","TRANSITION_DUE","CANCEL_REQUESTED","RECONCILING","COMPLETED","CANCELLED_BY_USER","FAILED"},
    "LIMIT_WORKING": {"TRANSITION_DUE","CANCEL_REQUESTED","RECONCILING","COMPLETED","CANCELLED_BY_USER"},
    "TRANSITION_DUE": {"CANCEL_REQUESTED","RECONCILING","COMPLETED","CANCELLED_BY_USER"},
    "CANCEL_REQUESTED": {"RECONCILING","COMPLETED","CANCELLED_BY_USER","PARTIALLY_FILLED","UNFILLED"},
    "RECONCILING": {"AUCTION_SUBMITTING","CANCEL_REQUESTED","COMPLETED","CANCELLED_BY_USER"},
    "AUCTION_SUBMITTING": {"AUCTION_WORKING","CANCEL_REQUESTED","COMPLETED","PARTIALLY_FILLED","UNFILLED","CANCELLED_BY_USER"},
    "AUCTION_WORKING": {"CANCEL_REQUESTED","COMPLETED","PARTIALLY_FILLED","UNFILLED","CANCELLED_BY_USER"},
    "MANUAL_REVIEW": {"CANCEL_REQUESTED","CANCELLED_BY_USER"},
}


def timestamp():
    return datetime.now(timezone.utc).isoformat()


class Store:
    def __init__(self, path):
        path = Path(path)
        if path.is_symlink():
            raise ValueError("State database must not be a symlink")
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path = path
        self.db = sqlite3.connect(path, timeout=5, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        os.chmod(path, 0o600)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.executescript(SCHEMA)

    @contextmanager
    def tx(self):
        self.db.execute("BEGIN IMMEDIATE")
        try:
            yield self.db
            self.db.execute("COMMIT")
        except BaseException:
            self.db.execute("ROLLBACK")
            raise

    def bind(self, alias, mode):
        with self.tx() as db:
            existing = dict(db.execute("SELECT key,value FROM metadata"))
            expected = {"alias": alias, "mode": mode, "schema": "1"}
            if existing and existing != expected:
                raise ValueError("Database belongs to another account alias, mode, or schema")
            for key, value in expected.items():
                db.execute("INSERT OR IGNORE INTO metadata VALUES (?,?)", (key,value))

    def verify_account(self, account_id):
        """Detect alias remapping without persisting the actual broker account ID."""
        key_path = self.path.parent / "account-binding.key"
        if key_path.is_symlink():
            raise ValueError("Account binding key must not be a symlink")
        try:
            fd = os.open(key_path,os.O_WRONLY | os.O_CREAT | os.O_EXCL,0o600)
        except FileExistsError:
            pass
        else:
            with os.fdopen(fd,"wb") as f:
                f.write(secrets.token_bytes(32))
                f.flush()
                os.fsync(f.fileno())
        key = key_path.read_bytes()
        if len(key) != 32 or key_path.stat().st_mode & 0o077:
            raise ValueError("Invalid private account binding key")
        fingerprint = hmac.new(key,str(account_id).encode(),hashlib.sha256).hexdigest()
        with self.tx() as db:
            old = db.execute("SELECT fingerprint FROM account_binding WHERE id=1").fetchone()
            if old and not hmac.compare_digest(old[0],fingerprint):
                raise ValueError("Account alias was remapped; use a new alias and reconcile the original account")
            db.execute("INSERT OR IGNORE INTO account_binding VALUES (1,?)",(fingerprint,))

    def parent(self, pid):
        row = self.db.execute("SELECT * FROM parents WHERE id=?", (pid,)).fetchone()
        if row is None:
            raise ValueError("Unknown parent order")
        return dict(row)

    def children(self, pid):
        return [dict(r) for r in self.db.execute("SELECT * FROM children WHERE parent=? ORDER BY rowid", (pid,))]

    def change(self, db, pid, state, reason, at):
        previous = db.execute("SELECT state FROM parents WHERE id=?", (pid,)).fetchone()[0]
        if state != previous and state != "MANUAL_REVIEW" and state not in ALLOWED.get(previous,set()):
            raise ValueError("Illegal parent state transition")
        db.execute("UPDATE parents SET state=?,reason=?,active=?,version=version+1 WHERE id=?",
                   (state,reason,int(state not in TERMINAL),pid))
        if previous != state:
            db.execute("INSERT INTO transitions(parent,previous,next,reason,at) VALUES (?,?,?,?,?)", (pid,previous,state,reason,at))

    def command(self, pid, action, payload=""):
        self.parent(pid)
        if action not in {"cancel", "reconcile", "acknowledge"}:
            raise ValueError("Unknown command")
        # Free text must never become a path, SQL, shell, or log template.
        if len(payload) > 1000:
            raise ValueError("Resolution must be at most 1000 characters")
        with self.tx() as db:
            db.execute("INSERT INTO commands(id,parent,action,payload) VALUES (?,?,?,?)", (uuid.uuid4().hex,pid,action,payload))

    def status(self, pid):
        p = self.parent(pid)
        p["children"] = self.children(pid)
        return p

    def close(self):
        self.db.close()
