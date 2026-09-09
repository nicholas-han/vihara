"""Explicit private configuration; importing this module reads no files or secrets."""
from dataclasses import dataclass, field
import os
from pathlib import Path
import re
import stat
import tomllib


def outside_git(path):
    path = Path(path).expanduser()
    if path.is_symlink():
        raise ValueError("Private path must not be a symlink")
    path = path.resolve()
    if any((p / ".git").exists() for p in (path, *path.parents)):
        raise ValueError("Private configuration must be outside Git")
    return path


def private_file(path):
    path = outside_git(path)
    info = path.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise ValueError("Private file must be owned by you with mode 0600 or stricter")
    return path


@dataclass(frozen=True)
class HyperliquidConfig:
    network: str = "testnet"
    trading_enabled: bool = False
    funds_enabled: bool = False
    private_key: str | None = field(default=None, repr=False)
    account_address: str | None = field(default=None, repr=False)
    timeout: float = 10.0

    def __post_init__(self):
        if self.network not in {"testnet", "mainnet"}:
            raise ValueError("Network must be testnet or mainnet")
        if type(self.trading_enabled) is not bool or type(self.funds_enabled) is not bool:
            raise ValueError("Permissions must be booleans")
        if not isinstance(self.timeout, (int, float)) or isinstance(self.timeout, bool) or not 0 < self.timeout <= 60:
            raise ValueError("Timeout must be in (0, 60]")
        if self.account_address is not None and not re.fullmatch(r"0x[0-9a-fA-F]{40}", self.account_address):
            raise ValueError("Invalid account address")

    @property
    def api_url(self):
        return "https://api.hyperliquid-testnet.xyz" if self.network == "testnet" else "https://api.hyperliquid.xyz"


def load_config(path=None):
    """Load an external TOML; secret sources are explicit and mutually exclusive."""
    try:
        data = tomllib.loads(private_file(path or "~/.config/vihara/hyperliquid.toml").read_text())
        allowed = {"network", "trading_enabled", "funds_enabled", "account_address", "private_key_env", "private_key_file", "timeout"}
        if set(data) - allowed or ("private_key_env" in data and "private_key_file" in data):
            raise ValueError()
        key = None
        if "private_key_env" in data:
            name = data.pop("private_key_env")
            if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
                raise ValueError()
            key = os.environ.get(name)
            if not key:
                raise ValueError()
        if "private_key_file" in data:
            key = private_file(data.pop("private_key_file")).read_text().strip()
            if not key:
                raise ValueError()
        return HyperliquidConfig(private_key=key, **data)
    except (ValueError, TypeError, OSError):
        raise ValueError("Invalid private Hyperliquid configuration or secret source") from None
