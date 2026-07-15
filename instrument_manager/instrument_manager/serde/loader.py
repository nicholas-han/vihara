"""JSON -> pybind structs -> InstrumentRegistry -> validate_all().

Canonical persistence is one JSON file per entity under
``vihara-data/instruments/`` (ADR-24):

    assets/<id>.json      L0 observables (+ event outcomes)
    products/<id>.json    L1 economics (13-leg payout model)
    listings/<id>.json    L2 venue tradability
    venues/<id>.json      venue reference rows (index-only)

Enum values are the UPPER_SNAKE strings the (retired) SQL schema used, so
the documented vocabulary carries over unchanged. ``Ref`` values encode as
``{"observable": id} | {"product": id} | {"listing": id} | null``; an
underlier may instead be ``{"basket": {"components": [...], "combine":
"ARITHMETIC"}}``.

Two JSON sections are index-only by design (the C++ read-structs do not
carry them): per-entity ``identifiers`` (the external_identifiers analogue)
and asset ``metadata``. They flow into the SQLite index, never into the
registry.

The loader collects errors instead of raising: a broken file is reported
and skipped, everything loadable still loads, and ``validate_all()`` runs
last as the same gate the C++ tests use.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..config import load_pybind

SCHEMA_VERSION = 1


@dataclass
class LoadedUniverse:
    registry: Any
    validation: Any  # instrument_manager_py.ValidationResult
    assets: list[dict] = field(default_factory=list)
    products: list[dict] = field(default_factory=list)
    listings: list[dict] = field(default_factory=list)
    venues: list[dict] = field(default_factory=list)
    files: list[Path] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors and self.validation.ok()


class _EnumMaps:
    """String <-> pybind enum tables, built once against the loaded module."""

    def __init__(self, im) -> None:
        self.im = im
        self.asset_kind = {
            "TRANSFERABLE": im.AssetKind.Transferable,
            "REFERENCE": im.AssetKind.Reference,
            "RATE": im.AssetKind.Rate,
            "VOLATILITY": im.AssetKind.Volatility,
            "CREDIT": im.AssetKind.Credit,
            "EVENT": im.AssetKind.Event,
            "LEGAL_CLAIM": im.AssetKind.LegalClaim,
            "PORTFOLIO": im.AssetKind.Portfolio,
            "OTHER": im.AssetKind.Other,
        }
        self.lifecycle = {
            "DATED": im.Lifecycle.Dated,
            "PERPETUAL": im.Lifecycle.Perpetual,
            "EVENT_RESOLVED": im.Lifecycle.EventResolved,
            "CALLABLE": im.Lifecycle.Callable,
            "OPEN_ENDED": im.Lifecycle.OpenEnded,
        }
        self.direction = {"RECEIVE": im.Direction.Receive, "PAY": im.Direction.Pay}
        self.settlement = {"CASH": im.Settlement.Cash, "PHYSICAL": im.Settlement.Physical}
        self.constraint_kind = {
            "SAME_NOTIONAL": im.ConstraintKind.SameNotional,
            "SAME_SCHEDULE": im.ConstraintKind.SameSchedule,
            "OUTCOME_PARTITION_EXACTLY_ONE": im.ConstraintKind.OutcomePartitionExactlyOne,
        }
        self.option_type = {"CALL": im.OptionType.Call, "PUT": im.OptionType.Put}
        self.option_style = {
            "EUROPEAN": im.OptionLeg.Style.European,
            "AMERICAN": im.OptionLeg.Style.American,
            "BERMUDAN": im.OptionLeg.Style.Bermudan,
        }
        self.option_path = {
            "VANILLA": im.OptionLeg.Path.Vanilla,
            "ASIAN": im.OptionLeg.Path.Asian,
            "LOOKBACK": im.OptionLeg.Path.Lookback,
            "BARRIER": im.OptionLeg.Path.Barrier,
        }
        self.strike_kind = {"FIXED": im.StrikeKind.Fixed, "FLOATING": im.StrikeKind.Floating}
        self.averaging = {
            "ARITHMETIC": im.AveragingType.Arithmetic,
            "GEOMETRIC": im.AveragingType.Geometric,
        }
        self.barrier_type = {
            "UP_AND_IN": im.BarrierType.UpAndIn,
            "UP_AND_OUT": im.BarrierType.UpAndOut,
            "DOWN_AND_IN": im.BarrierType.DownAndIn,
            "DOWN_AND_OUT": im.BarrierType.DownAndOut,
        }
        self.binary_payoff = {
            "CASH": im.BinaryPayoff.CashOrNothing,
            "ASSET": im.BinaryPayoff.AssetOrNothing,
            "CASH_OR_NOTHING": im.BinaryPayoff.CashOrNothing,
            "ASSET_OR_NOTHING": im.BinaryPayoff.AssetOrNothing,
        }
        self.digital_trigger = {
            "ABOVE": im.DigitalLeg.Trigger.Above,
            "BELOW": im.DigitalLeg.Trigger.Below,
            "EVENT_RESOLVES": im.DigitalLeg.Trigger.EventResolves,
        }
        self.performance_measure = {
            "PRICE_RETURN": im.PerformanceLeg.Measure.PriceReturn,
            "TOTAL_RETURN": im.PerformanceLeg.Measure.TotalReturn,
        }
        self.variance_measure = {
            "VARIANCE": im.VarianceLeg.Measure.Variance,
            "VOLATILITY": im.VarianceLeg.Measure.Volatility,
        }
        self.funding_convention = {
            "PERP_FUNDING_8H": im.FundingLeg.Convention.PerpFunding8h,
            "REPO": im.FundingLeg.Convention.Repo,
            "CONTINUOUS": im.FundingLeg.Convention.Continuous,
        }

    def get(self, table: dict, value: str, what: str):
        try:
            return table[value.upper()]
        except KeyError:
            raise ValueError(
                f"unknown {what} {value!r} (expected one of {sorted(table)})"
            ) from None


class _Loader:
    def __init__(self) -> None:
        self.im = load_pybind()
        self.enums = _EnumMaps(self.im)

    # -- shared value parsers ---------------------------------------------

    def ref(self, value: Any, what: str):
        im = self.im
        if value is None:
            return im.Ref.none()
        if not isinstance(value, dict) or len(value) != 1:
            raise ValueError(f"{what}: a ref must be null or one of "
                             '{"observable"|"product"|"listing": id}')
        ((kind, target),) = value.items()
        if kind == "observable":
            return im.Ref.to_observable(target)
        if kind == "product":
            return im.Ref.to_product(target)
        if kind == "listing":
            return im.Ref.to_listing(target)
        raise ValueError(f"{what}: unknown ref kind {kind!r}")

    def underlier(self, value: Any, what: str):
        im = self.im
        if isinstance(value, dict) and "basket" in value:
            spec = value["basket"]
            basket = im.Basket()
            basket.components = [
                im.BasketComponent(self.ref(c["ref"], what), float(c.get("weight", 1.0)))
                for c in spec.get("components", [])
            ]
            basket.combine = self.enums.get(
                self.enums.averaging, spec.get("combine", "ARITHMETIC"), "combine"
            )
            return basket
        return self.ref(value, what)

    # -- leg builders --------------------------------------------------------

    def build_payout(self, kind: str, params: dict, what: str):
        im, enums = self.im, self.enums
        kind = kind.upper()

        if kind == "HOLDING":
            leg = im.HoldingLeg()
            leg.asset = self.ref(params.get("asset"), what)
            leg.quote_ccy = self.ref(params.get("quote_ccy"), what)
            return leg
        if kind == "FORWARD":
            leg = im.ForwardLeg()
            leg.underlier = self.underlier(params.get("underlier"), what)
            leg.quote_ccy = self.ref(params.get("quote_ccy"), what)
            leg.contract_multiplier = float(params.get("contract_multiplier", 1.0))
            leg.inverse = bool(params.get("inverse", False))
            leg.settlement = enums.get(
                enums.settlement, params.get("settlement", "CASH"), "settlement")
            leg.deliver_into = self.ref(params.get("deliver_into"), what)
            return leg
        if kind == "PERPETUAL":
            leg = im.PerpetualLeg()
            leg.underlier = self.underlier(params.get("underlier"), what)
            leg.quote_ccy = self.ref(params.get("quote_ccy"), what)
            leg.contract_multiplier = float(params.get("contract_multiplier", 1.0))
            leg.inverse = bool(params.get("inverse", False))
            return leg
        if kind == "OPTION":
            leg = im.OptionLeg()
            leg.underlier = self.underlier(params.get("underlier"), what)
            leg.type = enums.get(enums.option_type, params["type"], "option type")
            leg.strike = float(params.get("strike", 0.0))
            leg.contract_multiplier = float(params.get("contract_multiplier", 1.0))
            leg.style = enums.get(enums.option_style, params.get("style", "EUROPEAN"), "style")
            leg.path = enums.get(enums.option_path, params.get("path", "VANILLA"), "path")
            leg.strike_kind = enums.get(
                enums.strike_kind, params.get("strike_kind", "FIXED"), "strike_kind")
            leg.averaging = enums.get(
                enums.averaging, params.get("averaging", "ARITHMETIC"), "averaging")
            leg.fixing_dates = list(params.get("fixing_dates", []))
            leg.exercise_dates = list(params.get("exercise_dates", []))
            if "barrier" in params and params["barrier"] is not None:
                spec = params["barrier"]
                terms = im.OptionLeg.BarrierTerms()
                terms.type = enums.get(enums.barrier_type, spec["type"], "barrier type")
                terms.level = float(spec.get("level", 0.0))
                terms.rebate = float(spec.get("rebate", 0.0))
                terms.discrete = bool(spec.get("discrete", False))
                terms.obs_dates = list(spec.get("obs_dates", []))
                leg.barrier = terms
            leg.settlement = enums.get(
                enums.settlement, params.get("settlement", "CASH"), "settlement")
            leg.deliver_into = self.ref(params.get("deliver_into"), what)
            return leg
        if kind == "DIGITAL":
            leg = im.DigitalLeg()
            leg.underlier = self.underlier(params.get("underlier"), what)
            leg.trigger = enums.get(
                enums.digital_trigger, params.get("trigger", "ABOVE"), "trigger")
            leg.level = float(params.get("level", 0.0))
            leg.outcome_code = str(params.get("outcome_code", ""))
            leg.payoff = enums.get(enums.binary_payoff, params.get("payoff", "CASH"), "payoff")
            leg.cash_amount = float(params.get("cash_amount", 1.0))
            leg.quote_ccy = self.ref(params.get("quote_ccy"), what)
            return leg
        if kind == "FIXED":
            leg = im.FixedRateLeg()
            leg.notional_ccy = self.ref(params.get("notional_ccy"), what)
            leg.rate = float(params.get("rate", 0.0))
            leg.schedule_id = str(params.get("schedule_id", ""))
            return leg
        if kind == "FLOATING":
            leg = im.FloatingRateLeg()
            leg.index = self.ref(params.get("index"), what)
            leg.spread = float(params.get("spread", 0.0))
            leg.schedule_id = str(params.get("schedule_id", ""))
            return leg
        if kind == "PERFORMANCE":
            leg = im.PerformanceLeg()
            leg.underlier = self.underlier(params.get("underlier"), what)
            leg.measure = enums.get(
                enums.performance_measure, params.get("measure", "TOTAL_RETURN"), "measure")
            leg.quote_ccy = self.ref(params.get("quote_ccy"), what)
            return leg
        if kind == "VARIANCE":
            leg = im.VarianceLeg()
            leg.underlier = self.underlier(params.get("underlier"), what)
            leg.measure = enums.get(
                enums.variance_measure, params.get("measure", "VARIANCE"), "measure")
            leg.vol_strike = float(params.get("vol_strike", 0.0))
            leg.num_observations = int(params.get("num_observations", 0))
            leg.annualization_factor = float(params.get("annualization_factor", 252.0))
            return leg
        if kind == "FUNDING":
            leg = im.FundingLeg()
            leg.funding_index = self.ref(params.get("funding_index"), what)
            leg.convention = enums.get(
                enums.funding_convention,
                params.get("convention", "PERP_FUNDING_8H"), "convention")
            leg.pay_ccy = self.ref(params.get("pay_ccy"), what)
            return leg
        if kind == "CREDIT_PROTECTION":
            leg = im.CreditProtectionLeg()
            leg.credit = self.ref(params.get("credit"), what)
            leg.recovery_floor = float(params.get("recovery_floor", 0.0))
            leg.pay_ccy = self.ref(params.get("pay_ccy"), what)
            return leg
        if kind == "CLAIM":
            leg = im.ClaimLeg()
            leg.pool = self.ref(params.get("pool"), what)
            leg.nav_ccy = self.ref(params.get("nav_ccy"), what)
            return leg
        if kind == "PRINCIPAL":
            leg = im.PrincipalLeg()
            leg.principal_ccy = self.ref(params.get("principal_ccy"), what)
            leg.face = float(params.get("face", 100.0))
            leg.redemption_schedule_id = str(params.get("redemption_schedule_id", ""))
            return leg
        raise ValueError(f"{what}: unknown leg kind {kind!r}")

    # -- entity builders ---------------------------------------------------

    def observable(self, data: dict):
        im = self.im
        o = im.Observable()
        o.id = data["id"]
        o.asset_class_id = data.get("asset_class_id", "")
        o.kind = self.enums.get(self.enums.asset_kind, data.get("kind", "REFERENCE"), "kind")
        o.code = data.get("code", data["id"])
        o.name = data.get("name", "")
        o.is_quotable = bool(data.get("is_quotable", False))
        o.is_settleable = bool(data.get("is_settleable", False))
        return o

    def event_outcome(self, asset_id: str, data: dict):
        im = self.im
        outcome = im.EventOutcome()
        outcome.id = data.get("id", f"{asset_id}__{data['outcome_code']}")
        outcome.asset_id = asset_id
        outcome.outcome_code = data["outcome_code"]
        outcome.name = data.get("name", data["outcome_code"])
        outcome.is_mutually_exclusive = bool(data.get("is_mutually_exclusive", True))
        outcome.resolved_value = data.get("resolved_value")
        return outcome

    def product(self, data: dict):
        im = self.im
        what = f"product {data.get('id', '?')}"
        p = im.Product()
        p.id = data["id"]
        p.name = data.get("name", "")
        p.lifecycle_class = self.enums.get(
            self.enums.lifecycle, data.get("lifecycle_class", "DATED"), "lifecycle_class")
        p.expiration = data.get("expiration") or ""
        p.quote_asset = self.ref(data.get("quote_asset"), what)
        p.settlement = self.ref(data.get("settlement"), what)
        p.stored_symbol = data.get("stored_symbol", "")
        p.metadata = {str(k): str(v) for k, v in (data.get("metadata") or {}).items()}

        legs = []
        for position, spec in enumerate(data.get("legs", [])):
            leg = im.ProductLeg()
            leg.leg_id = spec.get("leg_id", f"L{position}")
            leg.position = int(spec.get("position", position))
            leg.direction = self.enums.get(
                self.enums.direction, spec.get("direction", "RECEIVE"), "direction")
            leg.payout = self.build_payout(spec["kind"], spec.get("params", {}), what)
            notional = spec.get("notional")
            if notional is not None:
                leg.notional = im.Notional(
                    float(notional["amount"]),
                    self.ref(notional.get("currency"), what),
                )
            legs.append(leg)
        p.legs = legs

        p.constraints = [
            im.CompositionConstraint(
                self.enums.get(self.enums.constraint_kind, c["kind"], "constraint kind"),
                list(c.get("leg_ids", [])),
            )
            for c in data.get("constraints", [])
        ]
        return p

    def listing(self, data: dict):
        im = self.im
        listing = im.Listing()
        listing.id = data["id"]
        listing.product_id = data["product_id"]
        listing.venue_id = data["venue_id"]
        listing.venue_segment = data.get("venue_segment", "")
        listing.venue_symbol = data.get("venue_symbol", "")
        listing.contract_size = data.get("contract_size")
        return listing


def _read_json_dir(directory: Path, universe: LoadedUniverse) -> list[dict]:
    entries: list[dict] = []
    if not directory.is_dir():
        return entries
    for path in sorted(directory.glob("*.json")):
        universe.files.append(path)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            universe.errors.append(f"{path}: invalid JSON: {exc}")
            continue
        version = data.get("schema_version")
        if version != SCHEMA_VERSION:
            universe.errors.append(
                f"{path}: unsupported schema_version {version!r}"
            )
            continue
        expected = path.stem
        if data.get("id") != expected:
            universe.errors.append(
                f"{path}: id {data.get('id')!r} does not match filename"
            )
            continue
        data["_path"] = str(path)
        entries.append(data)
    return entries


def load_universe(instruments_dir: str | Path) -> LoadedUniverse:
    """Load every entity file, feed the registry, run the C++ load gate."""
    loader = _Loader()
    im = loader.im
    registry = im.InstrumentRegistry()
    universe = LoadedUniverse(registry=registry, validation=im.ValidationResult())
    instruments_dir = Path(instruments_dir)

    universe.venues = _read_json_dir(instruments_dir / "venues", universe)
    universe.assets = _read_json_dir(instruments_dir / "assets", universe)
    universe.products = _read_json_dir(instruments_dir / "products", universe)
    universe.listings = _read_json_dir(instruments_dir / "listings", universe)

    for data in universe.assets:
        try:
            registry.add_observable(loader.observable(data))
            for outcome in data.get("outcomes", []):
                registry.add_event_outcome(loader.event_outcome(data["id"], outcome))
        except (KeyError, ValueError, TypeError) as exc:
            universe.errors.append(f"{data['_path']}: {exc}")
    for data in universe.products:
        try:
            registry.add_product(loader.product(data))
        except (KeyError, ValueError, TypeError) as exc:
            universe.errors.append(f"{data['_path']}: {exc}")
    for data in universe.listings:
        try:
            registry.add_listing(loader.listing(data))
        except (KeyError, ValueError, TypeError) as exc:
            universe.errors.append(f"{data['_path']}: {exc}")

    universe.validation = registry.validate_all()
    return universe
