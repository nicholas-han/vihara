"""CLI writes durable commands; only the locked worker may mutate a real broker."""
import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import sqlite3
from plumber.models import Unavailable, decimal
from .calendar import Calendar, HKT
from .config import load, ConfigError, outside_git
from .engine import Engine
from .runtime import make_gateway, run, worker_lock, live_account_lock
from .store import Store


def parser():
    p = argparse.ArgumentParser(prog="vihara-order")
    p.add_argument("--config")
    p.add_argument("--account",default="paper",help="Local account alias, never a broker account number")
    commands = p.add_subparsers(dest="command",required=True)
    c = commands.add_parser("create")
    c.add_argument("--symbol",required=True)
    c.add_argument("--side",choices=["BUY","SELL"],required=True)
    c.add_argument("--quantity",required=True)
    c.add_argument("--limit-price",required=True)
    c.add_argument("--trade-date",required=True)
    for name in ("status","cancel","reconcile","acknowledge"):
        sub = commands.add_parser(name)
        sub.add_argument("parent_order_id")
        if name == "acknowledge":
            sub.add_argument("--resolution",required=True)
    commands.add_parser("list").add_argument("--date")
    w = commands.add_parser("worker")
    w.add_argument("--once",action="store_true")
    w.add_argument("--confirm-live",action="store_true")
    commands.add_parser("check-config")
    return p


def main(argv=None):
    args = parser().parse_args(argv)
    os.umask(0o077)
    store = gateway = None
    try:
        cfg = load(args.config,args.account)
        calendar = Calendar.load(cfg.calendar)
        directory = outside_git(cfg.state_dir / cfg.alias / cfg.mode.lower())
        directory.mkdir(parents=True,exist_ok=True,mode=0o700)
        if directory.stat().st_mode & 0o077:
            raise ConfigError("State directory must have mode 0700")
        store = Store(directory / "orders.sqlite3")
        store.bind(cfg.alias,cfg.mode)
        if cfg.connection:
            store.verify_account(cfg.connection.account_id)
        if args.command == "check-config":
            print(json.dumps({"valid":True,"account_alias":cfg.alias,"mode":cfg.mode,"live_status":"IMPLEMENTED_NOT_LIVE_VERIFIED"}))
            return 0
        if args.command == "list":
            ids = store.db.execute("SELECT id FROM parents WHERE (? IS NULL OR day=?) ORDER BY rowid",(args.date,args.date)).fetchall()
            print(json.dumps([store.status(r[0]) for r in ids],indent=2))
            return 0
        if args.command == "status":
            p = store.status(args.parent_order_id)
            p["remaining"] = str(decimal(p["quantity"])-decimal(p["filled"]))
            try:
                session = calendar.session(p["day"])
            except ValueError:
                session = None
                p["calendar_warning"] = "CALENDAR_UNAVAILABLE"
            p["next_action"] = {
                "ARMED":"Submit limit order", "LIMIT_WORKING":"Reconcile and cancel at transition",
                "TRANSITION_DUE":"Request cancellation", "CANCEL_REQUESTED":"Confirm child terminal state",
                "RECONCILING":"Confirm stable remaining quantity", "AUCTION_SUBMITTING":"Query submission identity",
                "AUCTION_WORKING":"Track auction and reconcile close", "MANUAL_REVIEW":"Manual action required; monitoring continues",
            }.get(p["state"],"No automatic action")
            p["conversion_window_hkt"] = [session.transition.isoformat(),session.deadline.isoformat()] if session else None
            print(json.dumps(p,indent=2))
            return 2 if p["state"] == "MANUAL_REVIEW" else 0
        if args.command in {"cancel","reconcile","acknowledge"}:
            store.command(args.parent_order_id,args.command,getattr(args,"resolution",""))
            print("Command queued for the worker; broker action is not yet confirmed.")
            return 0
        if args.command == "worker":
            if cfg.mode == "LIVE":
                if not cfg.live_enabled or not args.confirm_live:
                    raise ConfigError("LIVE requires local live_enabled=true and --confirm-live at every worker startup")
                if input("LIVE may execute real trades and fees. Type LIVE to start: ") != "LIVE":
                    return 1
            with live_account_lock(cfg), worker_lock(directory / "worker.lock"):
                gateway = make_gateway(cfg,mutations=True)
                engine = Engine(store,gateway,cfg,calendar,lambda: datetime.now(HKT))
                return run(engine,once=args.once)
        if args.command == "create":
            if cfg.mode == "LIVE" and not cfg.live_enabled:
                raise ConfigError("LIVE is disabled in local configuration")
            gateway = make_gateway(cfg,mutations=False)
            engine = Engine(store,gateway,cfg,calendar,lambda: datetime.now(HKT),recover=False)
            session = calendar.session(args.trade_date)
            preview = dict(symbol=args.symbol,side=args.side,quantity=args.quantity,price=args.limit_price,day=args.trade_date)
            engine.risk(preview,"LIMIT")
            print(json.dumps({"order_type":"LIMIT_WITH_MOC","mode":cfg.mode,"account_alias":cfg.alias,
                              **preview,"transition_hkt":session.transition.isoformat(),"deadline_hkt":session.deadline.isoformat(),
                              "max_notional":str(cfg.max_notional),"risk_check":"passed"},indent=2))
            print("Remaining quantity will become an unpriced closing auction order. The original limit will no longer apply. Full execution is not guaranteed.")
            if input("Type CONFIRM to create: ") != "CONFIRM":
                return 1
            pid = engine.create(args.symbol,args.side,args.quantity,args.limit_price,args.trade_date)
            print(json.dumps({"parent_order_id":pid,"state":"ARMED","next_action":"worker submits limit order"}))
            return 0
    except ConfigError as exc:
        print(json.dumps({"error":"CONFIGURATION_ERROR","help":str(exc)}))
        return 2
    except (ValueError,Unavailable,OSError,sqlite3.Error,ImportError,EOFError):
        # Exception strings, TOML snippets and SDK errors are intentionally never printed.
        print(json.dumps({"error":"COMMAND_FAILED","help":"Check private config permissions/schema, SDK installation, calendar, risk limits, worker ownership, and order status."}))
        return 2
    finally:
        if gateway:
            gateway.close()
        if store:
            store.close()
