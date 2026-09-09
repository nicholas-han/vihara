"""Read-only MVP catalog over IM JSON, gated by the existing C++ validator.

The catalog is a derived projection, not another instrument registry. It adds
Portfolio eligibility and identifier context without changing derivative APIs.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
import hashlib
import json
from pathlib import Path
from types import MappingProxyType

from .serde.loader import load_universe

ASSET_CLASSES = frozenset({"EQUITY", "CRYPTO", "FIAT_CURRENCY", "STABLECOIN"})


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


class HoldingCatalog:
    def __init__(self, directory: Path):
        universe = load_universe(directory)
        if not universe.ok:
            raise CatalogError(
                "Invalid instrument master: "
                + "; ".join(
                    universe.errors + [str(i) for i in universe.validation.issues]
                )
            )
        observables = {}
        currencies = {}
        for row in universe.assets:
            obs = Observable(
                row["id"],
                row.get("code", row["id"]),
                row.get("name", ""),
                row.get("kind", "REFERENCE"),
                row.get("asset_class_id"),
            )
            observables[obs.observable_id] = obs
            code = row.get("metadata", {}).get("currency_code")
            if code:
                if (
                    not isinstance(code, str)
                    or not code.isascii()
                    or not code.isalnum()
                    or code != code.upper()
                    or obs.kind != "TRANSFERABLE"
                    or obs.asset_class not in {"FIAT_CURRENCY", "STABLECOIN"}
                ):
                    raise CatalogError("Invalid Currency mapping")
                if code in currencies:
                    raise CatalogError("Duplicate Currency code")
                currencies[code] = obs.observable_id
        products = {}
        self.holding_legs = {}
        holding_leg_ids = set()
        all_products = {r["id"] for r in universe.products}
        for row in universe.products:
            legs = row.get("legs", [])
            if row.get("lifecycle_class") != "OPEN_ENDED" or len(legs) != 1:
                continue
            leg = legs[0]
            if leg["kind"] != "HOLDING":
                continue
            if row.get("expiration"):
                raise CatalogError("OPEN_ENDED Product must not expire")
            leg_id = leg.get("leg_id")
            if not isinstance(leg_id, str) or not leg_id or leg_id in holding_leg_ids:
                raise CatalogError("HoldingLeg requires a unique leg_id")
            holding_leg_ids.add(leg_id)
            params = leg.get("params", {})
            asset = params.get("asset", {}).get("observable")
            quote = params.get("quote_ccy", {}).get("observable")
            if asset not in observables or quote not in observables:
                raise CatalogError("HoldingLeg must reference Observables")
            obs = observables[asset]
            if obs.kind != "TRANSFERABLE" or obs.asset_class not in {
                "EQUITY",
                "CRYPTO",
            }:
                continue
            if quote not in currencies.values():
                continue
            if (
                leg.get("direction", "RECEIVE") != "RECEIVE"
                or leg.get("notional") is not None
            ):
                raise CatalogError(
                    "MVP HoldingLeg cannot carry a direction/notional override"
                )
            self.holding_legs[row["id"]] = leg
            products[row["id"]] = HoldingProduct(
                row["id"], row.get("name", ""), asset, quote
            )
        venues = {r["id"] for r in universe.venues}
        listings = {}
        seen = set()
        for row in universe.listings:
            listing = Listing(
                row["id"], row["product_id"], row["venue_id"], row["venue_segment"]
            )
            key = (listing.product_id, listing.venue_id, listing.venue_segment)
            if (
                key in seen
                or listing.venue_id not in venues
                or listing.venue_segment != listing.venue_segment.upper()
                or not listing.venue_segment
            ):
                raise CatalogError("Invalid or duplicate Listing identity")
            seen.add(key)
            listings[listing.listing_id] = listing
        identifiers = []
        for target_type, rows in [
            ("OBSERVABLE", universe.assets),
            ("PRODUCT", universe.products),
            ("LISTING", universe.listings),
        ]:
            for row in rows:
                for item in row.get("identifiers", []):
                    if not item.get("valid_from"):
                        raise CatalogError("Identifier valid_from is required")
                    start = date.fromisoformat(item["valid_from"])
                    end = (
                        date.fromisoformat(item["valid_to"])
                        if item.get("valid_to")
                        else None
                    )
                    entry = Identifier(
                        item["scheme"],
                        item.get("authority"),
                        item["value"],
                        target_type,
                        row["id"],
                        start,
                        end,
                    )
                    if (
                        not entry.scheme
                        or not entry.identifier
                        or (end and end <= start)
                    ):
                        raise CatalogError("Invalid identifier interval")
                    if entry.scheme == "VENUE_SYMBOL" and target_type != "LISTING":
                        raise CatalogError("VENUE_SYMBOL must target Listing")
                    for previous in identifiers:
                        same_key = (
                            entry.scheme,
                            entry.authority,
                            entry.identifier,
                        ) == (previous.scheme, previous.authority, previous.identifier)
                        overlaps = (
                            previous.valid_to is None or start < previous.valid_to
                        ) and (end is None or previous.valid_from < end)
                        if same_key and overlaps and entry != previous:
                            different = (entry.target_type, entry.target_id) != (
                                previous.target_type,
                                previous.target_id,
                            )
                            if different and entry.scheme != "VENUE_SYMBOL":
                                raise CatalogError("Overlapping identifier targets")
                    identifiers.append(entry)
        self.observables = MappingProxyType(observables)
        self.currencies = MappingProxyType(currencies)
        self.products = MappingProxyType(products)
        self.all_products = frozenset(all_products)
        self.listings = MappingProxyType(listings)
        self.identifiers = tuple(identifiers)

    def holding(self, product_id: str, listing_id: str | None = None) -> HoldingProduct:
        if product_id not in self.products:
            raise CatalogError("Product is missing or ineligible for Portfolio MVP")
        if listing_id is not None:
            listing = self.listings.get(listing_id)
            if listing is None or listing.product_id != product_id:
                raise CatalogError("Listing does not belong to Product")
        return self.products[product_id]

    def search(self, query: str = "") -> list[dict]:
        query = query.casefold().strip()
        result = []
        for product in self.products.values():
            obs = self.observables[product.asset_observable_id]
            aliases = [
                i.identifier
                for i in self.identifiers
                if (i.target_type == "PRODUCT" and i.target_id == product.product_id)
                or (i.target_type == "OBSERVABLE" and i.target_id == obs.observable_id)
                or (
                    i.target_type == "LISTING"
                    and self.listings[i.target_id].product_id == product.product_id
                )
            ]
            if query and not any(
                query in s.casefold()
                for s in [product.name, obs.code, obs.name, *aliases]
            ):
                continue
            result.append(
                {
                    **asdict(product),
                    "code": obs.code,
                    "asset_class": obs.asset_class,
                    "currency": next(
                        c
                        for c, oid in self.currencies.items()
                        if oid == product.quote_observable_id
                    ),
                }
            )
        return sorted(result, key=lambda p: (p["code"], p["product_id"]))

    def resolve(
        self,
        scheme: str,
        identifier: str,
        as_of: date,
        *,
        authority: str | None = None,
        venue_id: str | None = None,
        venue_segment: str | None = None,
    ) -> dict:
        matches = [
            i
            for i in self.identifiers
            if i.scheme == scheme
            and i.identifier == identifier
            and (authority is None or i.authority == authority)
            and i.valid_from <= as_of
            and (i.valid_to is None or as_of < i.valid_to)
        ]
        selected = []
        for item in matches:
            if venue_id or venue_segment:
                if item.target_type == "LISTING":
                    candidates = [self.listings[item.target_id]]
                else:
                    product_ids = (
                        {item.target_id}
                        if item.target_type == "PRODUCT"
                        else {
                            p.product_id
                            for p in self.products.values()
                            if p.asset_observable_id == item.target_id
                        }
                    )
                    candidates = [
                        listing
                        for listing in self.listings.values()
                        if listing.product_id in product_ids
                    ]
                if not any(
                    (not venue_id or listing.venue_id == venue_id)
                    and (not venue_segment or listing.venue_segment == venue_segment)
                    for listing in candidates
                ):
                    continue
            selected.append((item.target_type, item.target_id))
        targets = sorted(set(selected))
        state = (
            "FOUND"
            if len(targets) == 1
            else "AMBIGUOUS" if targets else "MISMATCH" if matches else "NOT_FOUND"
        )
        return {
            "state": state,
            "candidates": [{"target_type": t, "target_id": i} for t, i in targets],
        }

    def fingerprint(self, target_type: str, target_id: str) -> str:
        if target_type == "OBSERVABLE":
            obj = self.observables.get(target_id)
            if obj is None:
                raise CatalogError("Missing referenced Observable")
            payload = (obj.observable_id, obj.kind, obj.asset_class)
        elif target_type == "PRODUCT":
            obj = self.holding(target_id)
            payload = (obj.product_id, obj.asset_observable_id, obj.quote_observable_id)
        elif target_type == "LISTING":
            obj = self.listings.get(target_id)
            if obj is None:
                raise CatalogError("Missing referenced Listing")
            payload = (obj.listing_id, obj.product_id, obj.venue_id, obj.venue_segment)
        else:
            raise CatalogError("Unsupported reference pin")
        return hashlib.sha256(json.dumps(payload).encode()).hexdigest()
