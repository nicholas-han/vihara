#!/usr/bin/env python3
"""Smoke test for the instrument_manager_py pybind11 module.

Mirrors the C++ gtests' expectations (test_classify / test_validation /
test_symbology / test_projection) to prove the Python admin path calls the SAME
C++ validation + classification + projection code as the snapshot gate (ADR-7).

Builds two products end-to-end:
  - a BTC linear perp  = PerpetualLeg(Receive) + FundingLeg   (LINEAR / F, perpetual)
  - an SPX European call = single OptionLeg                   (OPTION / O)
then asserts classify(), validate() (a valid product is ok; an invalid one is
flagged with the exact gtest error code), canonical_symbol(), and project().

Run (after configuring with -DIM_BUILD_PYTHON=ON and building the module):

    PYTHONPATH=<build-dir> python3 instrument_manager/cpp/bindings/smoke_test.py

or import the module from wherever it was built. The build dir holding
instrument_manager_py*.so is auto-added to sys.path if found next to this file.
"""
import os
import sys

# Make the freshly-built module importable: search a few conventional build dirs
# relative to this file so the test runs without the caller wiring PYTHONPATH.
_HERE = os.path.dirname(os.path.abspath(__file__))
for _cand in (
    os.environ.get("IM_PY_BUILD_DIR", ""),
    os.path.join(_HERE, "..", "build"),
    os.path.join(_HERE, "..", "build", "bindings"),
    os.path.join(_HERE, "build"),
    os.getcwd(),
):
    if _cand and os.path.isdir(_cand) and _cand not in sys.path:
        sys.path.insert(0, _cand)

import instrument_manager_py as im  # noqa: E402


def _check(cond, msg):
    if not cond:
        raise AssertionError(msg)
    print(f"  ok: {msg}")


# ---------------------------------------------------------------------------
# A registry seeded with the L0 observables the products reference. The registry
# IS the ObservableResolver passed to validate / canonical_symbol / project.
# ---------------------------------------------------------------------------
def make_registry():
    reg = im.InstrumentRegistry()

    def obs(oid, kind, code):
        o = im.Observable()
        o.id = oid
        o.kind = kind
        o.code = code
        o.name = code
        return o

    reg.add_observable(obs("BTC", im.AssetKind.Transferable, "BTC"))
    reg.add_observable(obs("USDT", im.AssetKind.Transferable, "USDT"))
    reg.add_observable(obs("USD", im.AssetKind.Transferable, "USD"))
    reg.add_observable(obs("SPX", im.AssetKind.Reference, "SPX"))
    reg.add_observable(obs("BTC.PERP.FUNDING", im.AssetKind.Rate, "BTC.PERP.FUNDING"))
    reg.add_observable(obs("SOFR", im.AssetKind.Rate, "SOFR"))
    return reg


def make_leg(leg_id, position, payout, direction=im.Direction.Receive):
    leg = im.ProductLeg()
    leg.leg_id = leg_id
    leg.position = position
    leg.payout = payout
    leg.direction = direction
    return leg


# ---------------------------------------------------------------------------
# Product builders.
# ---------------------------------------------------------------------------
def make_btc_perp():
    """BTC linear perp = PerpetualLeg(Receive) + FundingLeg (same direction)."""
    perp = im.PerpetualLeg()
    perp.underlier = im.Ref.to_observable("BTC")
    perp.quote_ccy = im.Ref.to_observable("USDT")
    perp.contract_multiplier = 1.0
    perp.inverse = False

    funding = im.FundingLeg()
    funding.funding_index = im.Ref.to_observable("BTC.PERP.FUNDING")
    funding.pay_ccy = im.Ref.to_observable("USDT")

    p = im.Product()
    p.id = "p.btc.perp"
    p.name = "BTC-USDT Perp"
    p.lifecycle_class = im.Lifecycle.Perpetual
    p.legs = [make_leg("perp", 0, perp), make_leg("funding", 1, funding)]
    return p


def make_spx_option(expiration="2027-06-16"):
    """SPX European call, single OptionLeg, Dated."""
    o = im.OptionLeg()
    o.underlier = im.Ref.to_observable("SPX")
    o.type = im.OptionType.Call
    o.strike = 5000.0
    o.style = im.OptionLeg.Style.European
    o.path = im.OptionLeg.Path.Vanilla

    p = im.Product()
    p.id = "p.spx.opt"
    p.name = "SPX 5000 Call"
    p.lifecycle_class = im.Lifecycle.Dated
    p.expiration = expiration
    p.legs = [make_leg("L0", 0, o)]
    return p


# ===========================================================================
# 1. classify()
# ===========================================================================
def test_classify():
    print("[classify]")
    cp = im.classify(make_btc_perp())
    _check(cp.payoff_form == "LINEAR", f"perp payoff_form LINEAR (got {cp.payoff_form})")
    _check(cp.cfi_category == "F", f"perp cfi_category F (got {cp.cfi_category})")
    _check(cp.is_derivative, "perp is_derivative")
    _check("perpetual" in cp.tags, f"perp tags carry 'perpetual' (got {cp.tags})")
    _check("inverse" not in cp.tags, "linear perp has no 'inverse' tag")

    co = im.classify(make_spx_option())
    _check(co.payoff_form == "OPTION", f"option payoff_form OPTION (got {co.payoff_form})")
    _check(co.cfi_category == "O", f"option cfi_category O (got {co.cfi_category})")
    _check(co.is_derivative, "option is_derivative")
    _check("european" in co.tags, f"option tags carry 'european' (got {co.tags})")

    # dominant_leg of the perp is the PerpetualLeg arm.
    dom = im.dominant_leg(make_btc_perp())
    _check(isinstance(dom.payout, im.PerpetualLeg),
           f"dominant leg of perp is PerpetualLeg (got {type(dom.payout).__name__})")


# ===========================================================================
# 2. validate()  — a valid product passes; an invalid one is flagged.
# ===========================================================================
def _codes(res):
    return {i.code for i in res.issues}


def test_validate():
    print("[validate]")
    reg = make_registry()

    # valid: perp passes
    rp = im.validate_product(make_btc_perp(), reg)
    _check(rp.ok(), f"valid perp passes (issues: {[str(i) for i in rp.issues]})")

    # valid: SPX option passes
    ro = im.validate(make_spx_option(), reg)  # overloaded dispatch on Product
    _check(ro.ok(), f"valid SPX option passes (issues: {[str(i) for i in ro.issues]})")

    # invalid: a Perpetual product missing its FundingLeg.
    bad = im.Product()
    bad.id = "p.btc.perp.bad"
    bad.lifecycle_class = im.Lifecycle.Perpetual
    perp = im.PerpetualLeg()
    perp.underlier = im.Ref.to_observable("BTC")
    perp.quote_ccy = im.Ref.to_observable("USDT")
    bad.legs = [make_leg("perp", 0, perp)]  # no FundingLeg
    rb = im.validate_product(bad, reg)
    _check(not rb.ok(), "perp without funding leg fails")
    _check("LIFECYCLE_PERPETUAL_NEEDS_FUNDING_LEG" in _codes(rb),
           f"flagged LIFECYCLE_PERPETUAL_NEEDS_FUNDING_LEG (got {_codes(rb)})")

    # invalid: a Dated product with no expiration.
    bad2 = im.Product()
    bad2.id = "p.btc.fut.bad"
    bad2.lifecycle_class = im.Lifecycle.Dated
    bad2.expiration = ""  # missing
    f = im.ForwardLeg()
    f.underlier = im.Ref.to_observable("BTC")
    f.quote_ccy = im.Ref.to_observable("USDT")
    bad2.legs = [make_leg("L0", 0, f)]
    rb2 = im.validate_product(bad2, reg)
    _check(not rb2.ok(), "dated product without expiration fails")
    _check("LIFECYCLE_DATED_REQUIRES_EXPIRY" in _codes(rb2),
           f"flagged LIFECYCLE_DATED_REQUIRES_EXPIRY (got {_codes(rb2)})")

    # leg-level validator reports an unresolved underlier (DOGE not in resolver).
    h = im.HoldingLeg()
    h.asset = im.Ref.to_observable("DOGE")
    h.quote_ccy = im.Ref.to_observable("USD")
    rl = im.validate_leg(h, reg, "L0")
    _check(not rl.ok(), "leg with unresolved underlier fails")
    _check("LEG_UNDERLIER_UNRESOLVED" in _codes(rl),
           f"flagged LEG_UNDERLIER_UNRESOLVED (got {_codes(rl)})")


# ===========================================================================
# 3. canonical_symbol()  — dispatched off the dominant leg, resolved via registry.
# ===========================================================================
def test_symbol():
    print("[symbol]")
    reg = make_registry()
    _check(im.canonical_symbol(make_btc_perp(), reg) == "BTC-USDT-PERP",
           "perp symbol BTC-USDT-PERP")
    spx = make_spx_option("2026-12-18")
    _check(im.canonical_symbol(spx, reg) == "SPX-20261218-C5000",
           f"option symbol SPX-20261218-C5000 (got {im.canonical_symbol(spx, reg)})")
    _check(im.yyyymmdd("2026-12-18") == "20261218", "yyyymmdd compacts")
    _check(im.format_strike(6000.0) == "6000", "format_strike normalizes")


# ===========================================================================
# 4. project()  — pure IM -> asset_pricer projection.
# ===========================================================================
def test_project():
    print("[project]")
    reg = make_registry()
    as_of = "2026-06-16"

    # SPX European vanilla -> VanillaOption / BSM, T ~ 1y (ACT/365), needs scalar vol.
    ro = im.project(make_spx_option("2027-06-16"), as_of, reg)
    _check(len(ro.legs) == 1, "option projects one leg")
    out = ro.legs[0].outcome
    _check(isinstance(out, im.Priceable), f"option leg is Priceable (got {type(out).__name__})")
    _check(out.engine == im.Engine.Bsm, f"option engine BSM (got {out.engine})")
    _check(isinstance(out.contract, im.VanillaOption),
           f"option contract is VanillaOption (got {type(out.contract).__name__})")
    _check(out.contract.type == im.OptionType.Call, "vanilla is a Call")
    _check(out.contract.strike == 5000.0, "vanilla strike 5000")
    _check(abs(out.contract.time_to_expiry - 1.0) < 1e-9,
           f"vanilla T ~ 1y (got {out.contract.time_to_expiry})")
    _check(out.market.needs_scalar_vol, "option needs scalar vol")
    _check(not out.market.needs_smile, "option does NOT need a smile")
    _check(out.market.vol_at == im.VolAnchor.AtStrike, "option vol_at AtStrike")
    _check(out.market.underlier == im.Ref.to_observable("SPX"), "option underlier SPX")

    # BTC perp -> one priceable LinearForward (T=0) + one non-priced funding leg;
    # exactly one aggregated market request (BTC spot, not the funding index).
    rp = im.project(make_btc_perp(), as_of, reg)
    _check(len(rp.legs) == 2, "perp projects two legs")
    o0, o1 = rp.legs[0].outcome, rp.legs[1].outcome
    _check(isinstance(o0, im.Priceable), "perp leg 0 is Priceable")
    _check(o0.engine == im.Engine.LinearForward, f"perp engine LinearForward (got {o0.engine})")
    fwd = o0.contract
    _check(isinstance(fwd, im.ForwardContract), "perp contract is ForwardContract")
    _check(fwd.time_to_expiry == 0.0, "perp forward T = 0")
    _check(o0.inverse is None, "linear perp carries no InverseQuote")
    _check(isinstance(o1, im.NonPriced), "perp funding leg is NonPriced")
    _check(o1.reason == im.NonPriceReason.DeferredCashflow,
           f"funding reason DeferredCashflow (got {o1.reason})")
    _check(len(rp.market_requests) == 1, "perp aggregates exactly one market request")
    _check(rp.market_requests[0].underlier == im.Ref.to_observable("BTC"),
           "perp market request is for BTC")
    _check(rp.market_requests[0].needs_spot, "perp market request needs_spot")

    # An Unsupported (style x path) cell: American x Barrier carries no contract.
    o = im.OptionLeg()
    o.underlier = im.Ref.to_observable("SPX")
    o.type = im.OptionType.Call
    o.strike = 5000.0
    o.style = im.OptionLeg.Style.American
    o.path = im.OptionLeg.Path.Barrier
    pu = im.Product()
    pu.id = "p.unsup"
    pu.lifecycle_class = im.Lifecycle.Dated
    pu.expiration = "2027-06-16"
    pu.legs = [make_leg("L0", 0, o)]
    ru = im.project(pu, as_of, reg)
    uout = ru.legs[0].outcome
    _check(isinstance(uout, im.Unsupported), "American x Barrier is Unsupported")
    _check(uout.reason == im.UnsupportedReason.EarlyExercisePathDependent,
           f"unsupported reason EarlyExercisePathDependent (got {uout.reason})")
    _check(len(ru.market_requests) == 0, "unsupported cell advertises no market request")


# ===========================================================================
# 5. registry-wide load gate end to end (validate_all over a seeded snapshot).
# ===========================================================================
def test_registry_gate():
    print("[registry validate_all]")
    reg = make_registry()
    reg.add_product(make_btc_perp())
    reg.add_product(make_spx_option("2026-12-18"))
    res = reg.validate_all()
    _check(res.ok(), f"seeded snapshot passes validate_all (issues: {[str(i) for i in res.issues]})")
    ult = reg.ultimate_underliers("p.btc.perp")
    _check(any(r.id == "BTC" for r in ult),
           f"ultimate_underliers(p.btc.perp) includes BTC (got {[r.id for r in ult]})")


def main():
    print(f"instrument_manager_py loaded from: {im.__file__}")
    test_classify()
    test_validate()
    test_symbol()
    test_project()
    test_registry_gate()
    print("\nALL SMOKE TESTS PASSED")


if __name__ == "__main__":
    main()
