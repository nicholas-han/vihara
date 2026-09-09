"""Private runtime configuration. This layer resolves account aliases for injection."""
import os
from pathlib import Path
import re
import stat
import tomllib
from dataclasses import dataclass, field
from decimal import Decimal
from plumber.models import decimal


class ConfigError(ValueError):
    pass


def outside_git(path: Path):
    resolved = path.expanduser().resolve()
    for parent in (resolved, *resolved.parents):
        if (parent / ".git").exists():
            raise ConfigError("Private configuration and state must be outside every Git checkout")
    return resolved


def private_file(path: Path):
    if path.is_symlink():
        raise ConfigError("Private configuration must not be a symlink")
    p = outside_git(path)
    s = p.stat()
    if not stat.S_ISREG(s.st_mode) or s.st_mode & 0o077 or s.st_uid != os.getuid():
        raise ConfigError("Private configuration must be owned by you with mode 0600")
    return p


@dataclass(frozen=True)
class Connection:
    host: str
    port: int
    account_id: int = field(repr=False)
    unlock_env: str = field(default="", repr=False)


@dataclass(frozen=True)
class Settings:
    alias: str
    mode: str
    state_dir: Path
    calendar: Path
    max_quantity: Decimal
    max_notional: Decimal
    instruments: dict
    connection: Connection | None = field(default=None, repr=False)
    live_enabled: bool = False
    sdk_version: str = "10.10.7008"


def load(path=None, alias="paper"):
    p = private_file(Path(path or os.environ.get("VIHARA_TRADING_CONFIG", "~/.config/vihara/trading.toml")).expanduser())
    try:
        data = tomllib.loads(p.read_text())
        a = data["accounts"][alias]
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,31}", alias):
            raise ValueError()
        if not isinstance(a.get("live_enabled",False),bool):
            raise ValueError()
        mode = a.get("mode", "DRY_RUN")
        if mode not in {"DRY_RUN", "SHADOW", "LIVE"}:
            raise ValueError()
        state = outside_git(Path(data.get("state_dir", "~/.local/state/vihara/orders")))
        calendar = private_file(Path(data["calendar"]).expanduser())
        qty, notional = decimal(a["max_quantity"]), decimal(a["max_notional"])
        if qty <= 0 or notional <= 0:
            raise ValueError()
        instruments = a["instruments"]
        if not instruments:
            raise ValueError()
        connection = None
        if mode != "DRY_RUN":
            c = data["connections"][a["connection"]]
            if set(c) - {"host","port","account_id","unlock_env"}:
                raise ValueError()
            connection = Connection(c.get("host", "127.0.0.1"), int(c.get("port", 11111)), int(c["account_id"]), c.get("unlock_env", ""))
            if connection.account_id <= 0 or not 0 < connection.port < 65536:
                raise ValueError()
        if mode == "LIVE":
            # Multiple aliases must not bypass the per-account execution/conflict lock.
            for other_alias, other in data["accounts"].items():
                if other_alias != alias and other.get("mode") == "LIVE":
                    other_conn = data["connections"][other["connection"]]
                    if int(other_conn["account_id"]) == connection.account_id:
                        raise ValueError()
        # Never treat user configuration as evidence of live certification.
        return Settings(alias, mode, state, calendar, qty, notional, instruments,
                        connection, bool(a.get("live_enabled", False)), data.get("sdk_version", "10.10.7008"))
    except (KeyError, TypeError, ValueError, tomllib.TOMLDecodeError):
        raise ConfigError("Invalid private trading configuration; check the example schema") from None
