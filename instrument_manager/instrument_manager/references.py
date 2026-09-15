"""Public, read-only reference contract for investment consumers.

The JSON catalog supplies this interface today. Consumers depend on its frozen
reference values and detached results, not the catalog's storage or dictionaries.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Literal, Mapping, Protocol, TypedDict

__all__ = [
    "CatalogError",
    "Observable",
    "HoldingProduct",
    "Listing",
    "Identifier",
    "ReferenceCandidate",
    "Resolution",
    "ReferencePort",
]


class CatalogError(ValueError):
    pass


@dataclass(frozen=True)
class Observable:
    observable_id: str
    code: str
    name: str
    kind: str
    asset_class: str | None


@dataclass(frozen=True)
class HoldingProduct:
    product_id: str
    name: str
    asset_observable_id: str
    quote_observable_id: str


@dataclass(frozen=True)
class Listing:
    listing_id: str
    product_id: str
    venue_id: str
    venue_segment: str


@dataclass(frozen=True)
class Identifier:
    scheme: str
    authority: str | None
    identifier: str
    target_type: str
    target_id: str
    valid_from: date
    valid_to: date | None


class ReferenceCandidate(TypedDict):
    target_type: Literal["OBSERVABLE", "PRODUCT", "LISTING"]
    target_id: str


class Resolution(TypedDict):
    state: Literal["FOUND", "AMBIGUOUS", "MISMATCH", "NOT_FOUND"]
    candidates: list[ReferenceCandidate]


class ReferencePort(Protocol):
    """Queries over the same validated reference snapshot.

    Lookup methods return ``None`` for missing IDs/codes so callers retain their
    own domain error messages. ``holding`` and ``detail`` instead validate MVP
    eligibility and optional Listing ownership, raising ``CatalogError``.
    """

    @property
    def currency_mappings(self) -> Mapping[str, str]: ...

    def holding(
        self, product_id: str, listing_id: str | None = None
    ) -> HoldingProduct: ...

    def listing(self, listing_id: str) -> Listing | None: ...

    def observable(self, observable_id: str) -> Observable | None: ...

    def currency_observable(self, currency_code: str) -> str | None: ...

    def holdings_for_observable(
        self, observable_id: str
    ) -> tuple[HoldingProduct, ...]: ...

    def listings_for_product(self, product_id: str) -> tuple[Listing, ...]: ...

    def resolve(
        self,
        scheme: str,
        identifier: str,
        as_of: date,
        *,
        authority: str | None = None,
        venue_id: str | None = None,
        venue_segment: str | None = None,
    ) -> Resolution: ...

    def search(self, query: str = "") -> list[dict]: ...

    def fingerprint(self, target_type: str, target_id: str) -> str: ...

    def detail(self, product_id: str, listing_id: str | None = None) -> dict: ...

    def transferable_observables(self) -> list[Observable]:
        """Equity and crypto Observables selectable in Holdings."""
        ...
