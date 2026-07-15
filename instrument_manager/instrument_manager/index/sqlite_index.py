"""Derived SQLite index over a loaded instrument universe.

Disposable by construction (rebuild = drop + recreate from JSON). Flattened
lookups for non-C++ consumers — notably portfolio_manager's future adapter,
which joins its ``instrument_aliases`` against ``external_identifiers``
here. Classification and canonical symbols are DERIVED at build time by the
C++ core (classify / canonical_symbol), never authored (IM ADR-7).
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

from ..config import load_pybind
from ..serde.loader import LoadedUniverse

_SCHEMA = """
CREATE TABLE input_files (
    path   TEXT PRIMARY KEY,
    sha256 TEXT NOT NULL
);
CREATE TABLE venues (
    venue_id  TEXT PRIMARY KEY,
    name      TEXT NOT NULL,
    meta_json TEXT NOT NULL
);
CREATE TABLE assets (
    asset_id       TEXT PRIMARY KEY,
    kind           TEXT NOT NULL,
    code           TEXT NOT NULL,
    name           TEXT NOT NULL,
    asset_class_id TEXT,
    is_quotable    INTEGER NOT NULL,
    is_settleable  INTEGER NOT NULL,
    meta_json      TEXT NOT NULL
);
CREATE TABLE event_outcomes (
    outcome_id   TEXT PRIMARY KEY,
    asset_id     TEXT NOT NULL REFERENCES assets(asset_id),
    outcome_code TEXT NOT NULL,
    name         TEXT NOT NULL
);
CREATE TABLE products (
    product_id     TEXT PRIMARY KEY,
    name           TEXT NOT NULL,
    lifecycle      TEXT NOT NULL,
    expiration     TEXT,
    symbol         TEXT NOT NULL,     -- canonical, regenerated at build
    cfi_category   TEXT NOT NULL,     -- classify() output, never authored
    cfi_group      TEXT NOT NULL,
    payoff_form    TEXT NOT NULL,
    is_derivative  INTEGER NOT NULL,
    tags           TEXT NOT NULL,     -- space-separated
    meta_json      TEXT NOT NULL
);
CREATE TABLE product_legs (
    product_id TEXT NOT NULL REFERENCES products(product_id),
    position   INTEGER NOT NULL,
    leg_id     TEXT NOT NULL,
    kind       TEXT NOT NULL,
    direction  TEXT NOT NULL,
    PRIMARY KEY (product_id, position)
);
CREATE TABLE listings (
    listing_id    TEXT PRIMARY KEY,
    product_id    TEXT NOT NULL REFERENCES products(product_id),
    venue_id      TEXT NOT NULL,
    venue_segment TEXT NOT NULL,
    venue_symbol  TEXT NOT NULL,
    contract_size TEXT
);
CREATE UNIQUE INDEX uq_listings_venue
    ON listings(venue_id, venue_segment, venue_symbol);
CREATE TABLE external_identifiers (
    entity_kind TEXT NOT NULL CHECK (entity_kind IN ('asset','product','listing')),
    entity_id   TEXT NOT NULL,
    scheme      TEXT NOT NULL,
    identifier  TEXT NOT NULL,
    valid_from  TEXT,
    valid_to    TEXT,
    PRIMARY KEY (scheme, identifier, entity_kind, entity_id)
);
CREATE INDEX ix_external_identifiers_entity
    ON external_identifiers(entity_kind, entity_id);
CREATE TABLE ultimate_underliers (
    product_id TEXT NOT NULL REFERENCES products(product_id),
    ref_kind   TEXT NOT NULL,
    ref_id     TEXT NOT NULL,
    PRIMARY KEY (product_id, ref_kind, ref_id)
);
"""

_LEG_KINDS = {
    "HoldingLeg": "HOLDING",
    "ForwardLeg": "FORWARD",
    "PerpetualLeg": "PERPETUAL",
    "OptionLeg": "OPTION",
    "DigitalLeg": "DIGITAL",
    "FixedRateLeg": "FIXED",
    "FloatingRateLeg": "FLOATING",
    "PerformanceLeg": "PERFORMANCE",
    "VarianceLeg": "VARIANCE",
    "FundingLeg": "FUNDING",
    "CreditProtectionLeg": "CREDIT_PROTECTION",
    "ClaimLeg": "CLAIM",
    "PrincipalLeg": "PRINCIPAL",
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _identifiers(entity_kind: str, data: dict):
    for entry in data.get("identifiers", []):
        yield (
            entity_kind,
            data["id"],
            entry["scheme"],
            entry["value"],
            entry.get("valid_from"),
            entry.get("valid_to"),
        )


def rebuild(db_path: str | Path, universe: LoadedUniverse) -> None:
    im = load_pybind()
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()

    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(_SCHEMA)
        conn.executemany(
            "INSERT INTO input_files VALUES (?, ?)",
            [(str(p), _sha256(p)) for p in universe.files],
        )
        for data in universe.venues:
            conn.execute(
                "INSERT INTO venues VALUES (?, ?, ?)",
                (data["id"], data.get("name", data["id"]),
                 json.dumps(data.get("metadata", {}), sort_keys=True)),
            )
        for data in universe.assets:
            observable = universe.registry.observable_by_id(data["id"])
            if observable is None:
                continue
            conn.execute(
                "INSERT INTO assets VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    observable.id,
                    im.asset_kind_to_string(observable.kind),
                    observable.code,
                    observable.name,
                    observable.asset_class_id or None,
                    int(observable.is_quotable),
                    int(observable.is_settleable),
                    json.dumps(data.get("metadata", {}), sort_keys=True),
                ),
            )
            for outcome in data.get("outcomes", []):
                conn.execute(
                    "INSERT INTO event_outcomes VALUES (?, ?, ?, ?)",
                    (
                        outcome.get("id", f"{data['id']}__{outcome['outcome_code']}"),
                        data["id"],
                        outcome["outcome_code"],
                        outcome.get("name", outcome["outcome_code"]),
                    ),
                )
            conn.executemany(
                "INSERT INTO external_identifiers VALUES (?, ?, ?, ?, ?, ?)",
                list(_identifiers("asset", data)),
            )
        for data in universe.products:
            product = universe.registry.product_by_id(data["id"])
            if product is None:
                continue
            classification = im.classify(product)
            symbol = im.canonical_symbol(product, universe.registry)
            conn.execute(
                "INSERT INTO products VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    product.id,
                    product.name,
                    im.lifecycle_to_string(product.lifecycle_class),
                    product.expiration or None,
                    symbol,
                    classification.cfi_category,
                    classification.cfi_group,
                    classification.payoff_form,
                    int(classification.is_derivative),
                    " ".join(sorted(classification.tags)),
                    json.dumps(dict(product.metadata), sort_keys=True),
                ),
            )
            for leg in product.legs:
                conn.execute(
                    "INSERT INTO product_legs VALUES (?, ?, ?, ?, ?)",
                    (
                        product.id,
                        leg.position,
                        leg.leg_id,
                        _LEG_KINDS.get(type(leg.payout).__name__, "UNKNOWN"),
                        "RECEIVE" if leg.direction == im.Direction.Receive else "PAY",
                    ),
                )
            for ref in universe.registry.ultimate_underliers(product.id):
                conn.execute(
                    "INSERT OR IGNORE INTO ultimate_underliers VALUES (?, ?, ?)",
                    (product.id, str(ref.kind).rsplit(".", 1)[-1], ref.id),
                )
            conn.executemany(
                "INSERT INTO external_identifiers VALUES (?, ?, ?, ?, ?, ?)",
                list(_identifiers("product", data)),
            )
        for data in universe.listings:
            listing = universe.registry.listing_by_id(data["id"])
            if listing is None:
                continue
            conn.execute(
                "INSERT INTO listings VALUES (?, ?, ?, ?, ?, ?)",
                (
                    listing.id,
                    listing.product_id,
                    listing.venue_id,
                    listing.venue_segment,
                    listing.venue_symbol,
                    str(listing.contract_size) if listing.contract_size is not None else None,
                ),
            )
            conn.executemany(
                "INSERT INTO external_identifiers VALUES (?, ?, ?, ?, ?, ?)",
                list(_identifiers("listing", data)),
            )
        conn.commit()
    finally:
        conn.close()
