/**
 * @file  symbol.cpp
 * @brief Implementation of the leg-aware canonical-symbol generator (docs/50 §3).
 *
 * The generator is a pure function of the product's current terms. It dispatches
 * on the product's DOMINANT leg using `l1::dominant_leg()` — the same precedence
 * the classifier uses — so the generated symbol and the L3 label never disagree
 * about what the product "is". Nested refs (an option-on-future's underlying
 * future, a leg's observable code) are resolved through the `ObservableResolver`,
 * which the `InstrumentRegistry` implements; resolution falls back to the opaque
 * id when a ref does not resolve. No I/O, total, deterministic.
 *
 * See docs/50-identity-and-symbology.md and docs/20-product-economics.md §4.3.
 */
#include "symbology/symbol.hpp"

#include <cmath>
#include <cstdio>
#include <string>
#include <variant>

#include "classify/classify.hpp"  // l1::dominant_leg() — shared precedence
#include "core/payout_leg.hpp"
#include "core/product.hpp"
#include "core/ref.hpp"
#include "core/resolver.hpp"

namespace instrument_manager::symbology {
namespace {

/// The std::visit overload-set helper (same idiom the classifier uses).
template <class... Ts>
struct overloaded : Ts... {
  using Ts::operator()...;
};
template <class... Ts>
overloaded(Ts...) -> overloaded<Ts...>;

/// Resolve a leg's `Underlier` (a single `Ref` or an inline `Basket`) to a
/// display string. P0 has no inline baskets (named indices are L0 `Portfolio`
/// observables referenced by a single `Ref`); the basket arm renders as a
/// parenthesized weighted list for the deferred OTC path so the function stays
/// total over the variant.
std::string underlier_symbol(const l1::Underlier& u, const ObservableResolver& reg) {
  return std::visit(overloaded{
      [&](const Ref& r) { return ref_symbol(r, reg); },
      [&](const l1::Basket& b) {
        std::string s = "(";
        bool first = true;
        for (const auto& c : b.components) {
          if (!first) s += "+";
          first = false;
          s += ref_symbol(c.ref, reg);
        }
        s += ")";
        return s;
      },
  }, u);
}

/// Multi-leg / non-headlined products name off the dominant leg's primary
/// underlier (or the product quote asset when the leg carries none) plus a
/// form suffix. Swap forms (-IRS/-CDS/-TRS) are exercised only when swaps are
/// authored (deferred); P0 reaches this arm for the cash-stream legs that head
/// no P0 product on their own, so we fall back to a stable, term-derived name.
std::string multi_leg_symbol(const l1::Product& p, const ObservableResolver& reg) {
  const l1::ProductLeg& dom = l1::dominant_leg(p);
  return std::visit(overloaded{
      [&](const l1::PerformanceLeg& pf) {
        return underlier_symbol(pf.underlier, reg) + "-TRS";
      },
      [&](const l1::CreditProtectionLeg& cp) {
        return ref_symbol(cp.credit, reg) + "-CDS";
      },
      [&](const l1::FixedRateLeg& fr) {
        return ref_symbol(fr.notional_ccy, reg) + "-IRS";
      },
      [&](const l1::FloatingRateLeg& fl) {
        return ref_symbol(fl.index, reg) + "-IRS";
      },
      [&](const l1::PrincipalLeg& pr) {
        return ref_symbol(pr.principal_ccy, reg) + "-BOND";
      },
      [&](const l1::FundingLeg& fg) {
        return ref_symbol(fg.funding_index, reg) + "-FUNDING";
      },
      [&](const auto& /*other*/) {
        // Any other dominant leg that reaches here has no dedicated headline
        // form; fall back to the product's quote asset so the symbol is still
        // term-derived and deterministic.
        return ref_symbol(p.quote_asset, reg);
      },
  }, dom.payout);
}

}  // namespace

// ---------------------------------------------------------------------------
// Formatting helpers
// ---------------------------------------------------------------------------

std::string yyyymmdd(const std::string& iso8601) {
  // ISO8601 dates begin "YYYY-MM-DD..."; strip the separators of the date part.
  // Tolerate an already-compact "YYYYMMDD" and an empty/short string (return as-is).
  std::string out;
  out.reserve(8);
  for (char ch : iso8601) {
    if (ch >= '0' && ch <= '9') {
      out += ch;
      if (out.size() == 8) break;  // date part only; ignore any time component
    } else if (ch == 'T' || ch == ' ') {
      break;  // reached the time component
    }
    // any other char (e.g. '-') is a separator we drop
  }
  return out;
}

std::string format_strike(double strike) {
  // Normalize so 6000 / 6000.0 / 6000.00 collapse to one stable form: integral
  // strikes render with no decimal point; fractional strikes render with up to
  // six significant decimals, trailing zeros trimmed.
  if (std::isfinite(strike) && strike == std::floor(strike)) {
    char buf[32];
    std::snprintf(buf, sizeof(buf), "%lld", static_cast<long long>(strike));
    return std::string(buf);
  }
  char buf[64];
  std::snprintf(buf, sizeof(buf), "%.6f", strike);
  std::string s(buf);
  // Trim trailing zeros, then a dangling decimal point.
  auto last = s.find_last_not_of('0');
  if (last != std::string::npos) s.erase(last + 1);
  if (!s.empty() && s.back() == '.') s.pop_back();
  return s;
}

// ---------------------------------------------------------------------------
// Ref / option resolution
// ---------------------------------------------------------------------------

std::string ref_symbol(const Ref& ref, const ObservableResolver& reg) {
  if (ref.is_none()) return std::string();
  // Both the Observable arm (-> L0 code) and the Product arm (-> nested product's
  // canonical symbol) resolve through the single resolver surface; the registry's
  // symbol_of() recurses into nested products itself (bounded by the DAG
  // acyclicity invariant). Fall back to the opaque id when unresolved.
  if (auto sym = reg.symbol_of(ref.id)) return *sym;
  return ref.id;
}

std::string option_symbol(const l1::OptionLeg& opt, const std::string& expiration,
                          const ObservableResolver& reg) {
  const std::string root = underlier_symbol(opt.underlier, reg);  // resolves Ref{Product} too
  const std::string expiry = yyyymmdd(expiration);
  const char cp = (opt.type == l1::OptionType::Call) ? 'C' : 'P';
  const std::string strike = format_strike(opt.strike);
  std::string out = root;
  out += '-';
  out += expiry;
  out += '-';
  out += cp;
  out += strike;
  return out;  // e.g. SPX-20261218-C6000
}

// ---------------------------------------------------------------------------
// The product-grain canonical symbol
// ---------------------------------------------------------------------------

std::string canonical_symbol(const l1::Product& product, const ObservableResolver& reg) {
  if (product.legs.empty()) {
    // Defensive: a legless product cannot be named off a leg. Fall back to the
    // product quote asset (validation rejects legless products upstream).
    return ref_symbol(product.quote_asset, reg);
  }

  // Dominant-leg selection reuses classify()'s total precedence so the symbol and
  // the L3 label never disagree about what the product is.
  const l1::ProductLeg& dom = l1::dominant_leg(product);

  return std::visit(overloaded{
      // 1. Holding / spot — BTC/USDT, oTSLA/USDC, UBTC/USDC.
      [&](const l1::HoldingLeg& h) {
        return ref_symbol(h.asset, reg) + "/" + ref_symbol(h.quote_ccy, reg);
      },
      // 2. Dated linear — SPX-20260619, BTC-20260327 (multiplier-distinct products
      //    differ by the resolved underlier code, not the symbol shape).
      [&](const l1::ForwardLeg& f) {
        return underlier_symbol(f.underlier, reg) + "-" + yyyymmdd(product.expiration);
      },
      // 3. Perpetual — BTC-USDT-PERP; inverse (coin-margined) renders -USD-PERP
      //    since the inverse perp settles in USD-equivalent (docs/50 §3.2).
      [&](const l1::PerpetualLeg& pp) {
        const std::string quote = pp.inverse ? std::string("USD")
                                             : ref_symbol(pp.quote_ccy, reg);
        return underlier_symbol(pp.underlier, reg) + "-" + quote + "-PERP";
      },
      // 4. Option — SPX-20261218-C6000 (root, expiry, type, strike); option-on-
      //    future resolves the future's symbol as the root. Uniqueness-critical.
      [&](const l1::OptionLeg& o) {
        return option_symbol(o, product.expiration, reg);
      },
      // 5. Digital / prediction outcome — EVT_US_PRES_2028:WIN_A.
      [&](const l1::DigitalLeg& d) {
        return underlier_symbol(d.underlier, reg) + ":" + d.outcome_code;
      },
      // 9. Variance — SPX-VAR-20261218.
      [&](const l1::VarianceLeg& v) {
        return underlier_symbol(v.underlier, reg) + "-VAR-" + yyyymmdd(product.expiration);
      },
      // 12. Claim — SPY (the fund share; NAV pool resolved via the resolver).
      [&](const l1::ClaimLeg& c) {
        return ref_symbol(c.pool, reg);
      },
      // FixedRate/Floating/Performance/Funding/CreditProtection/Principal head a
      // multi-leg product named off the dominant leg + a form suffix.
      [&](const auto& /*other*/) {
        return multi_leg_symbol(product, reg);
      },
  }, dom.payout);
}

}  // namespace instrument_manager::symbology
