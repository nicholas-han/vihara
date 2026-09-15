"""Derived SQLite index over a loaded instrument universe.

Disposable by construction (rebuild = replace from JSON after validation). Flattened
lookups for non-C++ consumers — notably portfolio_manager's future adapter,
which joins its ``instrument_aliases`` against ``external_identifiers``
here. Classification and canonical symbols are DERIVED at build time by the
C++ core (classify / canonical_symbol), never authored (IM ADR-7).
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import tempfile
from datetime import date
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
-- Holdings listings may carry dated VENUE_SYMBOL identifiers only.
CREATE UNIQUE INDEX uq_listings_venue
    ON listings(venue_id, venue_segment, venue_symbol) WHERE venue_symbol <> '';
CREATE TABLE external_identifiers (
    identifier_id INTEGER PRIMARY KEY,
    entity_kind TEXT NOT NULL CHECK (entity_kind IN ('asset','product','listing')),
    entity_id   TEXT NOT NULL,
    scheme      TEXT NOT NULL,
    authority   TEXT,
    identifier  TEXT NOT NULL,
    valid_from  TEXT,
    valid_to    TEXT
);
-- NULL means unspecified; retain it distinctly from an explicitly empty value.
CREATE UNIQUE INDEX uq_external_identifiers_record ON external_identifiers(
    scheme, authority IS NULL, coalesce(authority, ''), identifier,
    entity_kind, entity_id,
    valid_from IS NULL, coalesce(valid_from, ''),
    valid_to IS NULL, coalesce(valid_to, '')
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


_INSERT_IDENTIFIERS = """
INSERT INTO external_identifiers
    (entity_kind, entity_id, scheme, authority, identifier, valid_from, valid_to)
VALUES (?, ?, ?, ?, ?, ?, ?)
ON CONFLICT DO NOTHING
"""


def _source_hashes(universe: LoadedUniverse) -> list[tuple[str, str]]:
    """Hash the bytes whose JSON still matches the loaded, validated snapshot."""
    loaded = {
        row["_path"]: {key: value for key, value in row.items() if key != "_path"}
        for rows in (universe.venues, universe.assets, universe.products, universe.listings)
        for row in rows
    }
    hashes = []
    for path in universe.files:
        content = path.read_bytes()
        if json.loads(content) != loaded.get(str(path)):
            raise ValueError(f"Instrument source changed since loading: {path}")
        hashes.append((str(path), hashlib.sha256(content).hexdigest()))
    return hashes


def _identifier_date(value, field: str) -> str | None:
    if value is None:
        return None
    try:
        if not isinstance(value, str) or date.fromisoformat(value).isoformat() != value:
            raise ValueError
    except ValueError:
        raise ValueError(f"Identifier {field} must be an ISO date or null") from None
    return value


def _identifiers(entity_kind: str, data: dict):
    for entry in data.get("identifiers", []):
        authority = entry.get("authority")
        if authority is not None and not isinstance(authority, str):
            raise ValueError("Identifier authority must be a string or null")
        valid_from = _identifier_date(entry.get("valid_from"), "valid_from")
        valid_to = _identifier_date(entry.get("valid_to"), "valid_to")
        if valid_from is not None and valid_to is not None and valid_from >= valid_to:
            raise ValueError("Identifier valid_from must be earlier than valid_to")
        yield (
            entity_kind,
            data["id"],
            entry["scheme"],
            authority,
            entry["value"],
            valid_from,
            valid_to,
        )


def rebuild(db_path: str | Path, universe: LoadedUniverse) -> None:
    """Publish a complete validated index, leaving any previous index on failure."""
    if not universe.ok:
        raise ValueError("Cannot rebuild index from an invalid instrument universe")
    input_files = _source_hashes(universe)
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{db_path.name}.", suffix=".tmp", dir=db_path.parent
    )
    os.close(descriptor)
    temporary_path = Path(temporary_name)
    try:
        _build(temporary_path, universe, input_files)
        if _source_hashes(universe) != input_files:
            raise ValueError("Instrument source changed during index rebuild")
        temporary_path.replace(db_path)
    finally:
        temporary_path.unlink(missing_ok=True)


def _build(db_path: Path, universe: LoadedUniverse, input_files: list[tuple[str, str]]) -> None:
    im = load_pybind()
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(_SCHEMA)
        conn.executemany(
            "INSERT INTO input_files VALUES (?, ?)",
            input_files,
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
                _INSERT_IDENTIFIERS,
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
                _INSERT_IDENTIFIERS,
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
                _INSERT_IDENTIFIERS,
                list(_identifiers("listing", data)),
            )
        conn.commit()
        if conn.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
            raise ValueError("Rebuilt instrument index failed integrity validation")
        if conn.execute("PRAGMA foreign_key_check").fetchone() is not None:
            raise ValueError("Rebuilt instrument index contains broken references")
    finally:
        conn.close()
