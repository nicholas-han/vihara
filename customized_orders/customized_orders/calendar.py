"""Explicit dated HK sessions. No inference from weekdays or holiday names."""
from dataclasses import dataclass
from datetime import date, datetime, time
import json
from zoneinfo import ZoneInfo

HKT = ZoneInfo("Asia/Hong_Kong")


@dataclass(frozen=True)
class Session:
    day: str
    kind: str
    transition: datetime
    warning: datetime
    deadline: datetime
    no_cancel: datetime
    close: datetime

    def continuous(self, now):
        now = now.astimezone(HKT)
        if now.date().isoformat() != self.day:
            return False
        t = now.time().replace(tzinfo=None)
        return time(9, 30) <= t < time(12) or (self.kind == "FULL_DAY" and time(13) <= t < time(16))


class Calendar:
    def __init__(self, records):
        self.records = records

    @classmethod
    def load(cls, path):
        return cls(json.loads(path.read_text()))

    def session(self, day):
        r = self.records.get(day, {})
        if r.get("session_type") not in {"FULL_DAY", "HALF_DAY"}:
            raise ValueError("Trading date is missing, closed, or disabled")
        if not r.get("source") or not r.get("verified_at") or r.get("valid_until", "") < day:
            raise ValueError("Trading calendar evidence is missing or expired")
        verified = datetime.fromisoformat(r["verified_at"])
        if verified.tzinfo is None or verified.date() > date.fromisoformat(day):
            raise ValueError("Invalid calendar verification timestamp")
        half = r["session_type"] == "HALF_DAY"
        hour = "12" if half else "16"
        def dt(value):
            return datetime.combine(date.fromisoformat(day), time.fromisoformat(value), HKT)
        start = dt(hour + ":01:00")
        no_cancel = dt(hour + ":06:00")
        transition = dt(r.get("transition_start", hour + ":01:02"))
        warning = dt(r.get("warning_at", hour + ":04:30"))
        deadline = dt(r.get("submission_deadline", hour + ":05:30"))
        if not start <= transition < warning < deadline < no_cancel:
            raise ValueError("Invalid conversion window")
        return Session(day, r["session_type"], transition, warning, deadline, no_cancel, dt(hour + ":10:00"))
