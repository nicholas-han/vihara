"""Explicit funds capability, independent from order trading."""
import re
from plumber.models import decimal


class FundsService:
    def __init__(self, client):
        self._client = client

    def _send(self, method, amount, destination):
        if isinstance(amount, bool) or decimal(amount) <= 0 or not re.fullmatch(r"0x[0-9a-fA-F]{40}", destination):
            raise ValueError("Invalid transfer amount or destination")
        return self._client.mutate(method, amount, destination, funds=True)

    def transfer_usd(self, amount, destination):
        return self._send("usd_transfer", amount, destination)

    def withdraw_from_bridge(self, amount, destination):
        return self._send("withdraw_from_bridge", amount, destination)
