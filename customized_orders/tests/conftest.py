from datetime import datetime
from decimal import Decimal
from pathlib import Path
import pytest
from plumber.fake import FakeGateway
from customized_orders.calendar import Calendar,HKT
from customized_orders.config import Settings
from customized_orders.engine import Engine
from customized_orders.store import Store


class Clock:
    def __init__(self):
        self.set("10:00:00")
    def set(self,time,day="2026-09-10"):
        self.value = datetime.fromisoformat(day+"T"+time).replace(tzinfo=HKT)
    def __call__(self):
        return self.value


@pytest.fixture
def setup(tmp_path):
    clock = Clock()
    records = {"2026-09-10":{"session_type":"FULL_DAY","source":"fixture","verified_at":"2026-09-09T00:00:00+08:00","valid_until":"2026-09-10"}}
    calendar = Calendar(records)
    settings = Settings("paper","DRY_RUN",tmp_path,tmp_path / "calendar.json",Decimal(1000),Decimal(200000),
                        {"HK.00700":{"cas":True,"verified_for":"2026-09-10","source":"fixture","lot_size":100,"tick_size":"0.2","tick_lower":"50","tick_upper":"200","auction_risk_price":"110"}})
    store = Store(tmp_path / "orders.sqlite3")
    gateway = FakeGateway()
    engine = Engine(store,gateway,settings,calendar,clock)
    yield engine,gateway,clock,store
    store.close()


def limit(setup):
    e,g,t,s = setup
    pid = e.create("HK.00700","BUY",300,100,"2026-09-10")
    e.step(pid)
    e.step(pid)
    return pid


def auction(setup,pid):
    e,g,t,s = setup
    t.set("16:01:02")
    e.step(pid)  # cancel accepted
    e.step(pid)  # terminal snapshot, quiet begins
    t.set("16:01:03")
    e.step(pid)  # auction intent + submit
    e.step(pid)  # confirm
