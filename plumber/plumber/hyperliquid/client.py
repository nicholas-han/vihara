"""Connection object with separate read, trade and funds capabilities."""
from plumber.models import Unavailable, UnknownResult
from .config import HyperliquidConfig
from ._sdk import load_sdk, make_info, close_info


class HyperliquidClient:
    def __init__(self, config=None, *, allow_trading=False, allow_funds=False, confirm_mainnet=False):
        self.config = config or HyperliquidConfig()
        self.info = self._exchange = None
        self._signer_address = self._effective_address = None
        self._closed = False
        if any(type(x) is not bool for x in (allow_trading, allow_funds, confirm_mainnet)):
            raise ValueError("Capabilities must be booleans")
        if allow_trading and not self.config.trading_enabled:
            raise ValueError("Trading is disabled in private configuration")
        if allow_funds and not self.config.funds_enabled:
            raise ValueError("Funds operations are disabled in private configuration")
        if (allow_trading or allow_funds) and self.config.network == "mainnet" and not confirm_mainnet:
            raise ValueError("Mainnet mutations require explicit confirm_mainnet=True")
        self._allow_trading, self._allow_funds = allow_trading, allow_funds
        if (allow_trading or allow_funds) and not self.config.private_key:
            raise ValueError("A signing key is required for mutations")
        try:
            Account, Exchange, Info = load_sdk()
            self.info = make_info(Info, self.config)
            if allow_trading or allow_funds:
                wallet = Account.from_key(self.config.private_key)
                self._signer_address = wallet.address
                self._effective_address = self.config.account_address or wallet.address
                self._verify_account()
                self._exchange = Exchange(wallet, self.config.api_url, account_address=self._effective_address, timeout=self.config.timeout)
        except Exception:
            self.close()
            raise Unavailable("HYPERLIQUID_STARTUP_FAILED") from None

    @property
    def address(self):
        return self._effective_address or self.config.account_address

    def _verify_account(self):
        """Fail before signing if this network maps the signer to another account."""
        try:
            role = self.info.user_role(self._signer_address)
            if role.get("role") == "user":
                owner = self._signer_address
            elif role.get("role") == "agent" and not self._allow_funds:
                owner = role["data"]["user"]
            else:
                raise ValueError()
            if not isinstance(owner, str) or owner.lower() != self._effective_address.lower():
                raise ValueError()
        except Exception:
            raise Unavailable("HYPERLIQUID_ACCOUNT_VERIFICATION_FAILED") from None

    def require_capability(self, *, funds=False):
        """Check permission without exposing the underlying signing SDK object."""
        if type(funds) is not bool or self._closed or self._exchange is None or not (self._allow_funds if funds else self._allow_trading):
            raise ValueError("Requested mutation capability is disabled")

    def mutate(self, method, *args, funds=False, **kwargs):
        trade_methods = {"order", "market_open", "market_close", "cancel", "cancel_by_cloid", "modify_order", "update_leverage", "update_isolated_margin"}
        funds_methods = {"usd_transfer", "withdraw_from_bridge"}
        if method not in trade_methods | funds_methods or funds != (method in funds_methods):
            raise ValueError("Method does not belong to the requested capability")
        self.require_capability(funds=funds)
        # Agent authorizations can change while a client remains open.
        self._verify_account()
        try:
            return getattr(self._exchange, method)(*args, **kwargs)
        except Exception:
            # No mutation retry: a request may already have reached the exchange.
            raise UnknownResult("HYPERLIQUID_MUTATION_RESULT_UNKNOWN") from None

    def close(self):
        if self._closed:
            return
        self._closed = True
        close_info(self.info)
        if self._exchange:
            close_info(getattr(self._exchange, "info", None))
        self._exchange = None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
