/**
 * @file  demo.cpp
 * @brief Builds the option -> future -> index chain in code and exercises the
 *        registry: graph walk, derivatives, and validation.
 */
#include <iostream>

#include <registry/registry.hpp>

using namespace instrument_manager;

int main() {
  InstrumentRegistry r;
  r.add_asset({"SPX", "EQUITY_INDEX", "SPX", "S&P 500 Index", AssetKind::Reference});
  r.add_asset({"USD", "CURRENCY", "USD", "US Dollar", AssetKind::Transferable});

  Instrument fut;
  fut.id = "ESM2026";
  fut.form = PayoffForm::Linear;
  fut.quote_asset_id = "USD";
  fut.underlying = Ref::to_asset("SPX");
  fut.settlement = Ref::to_asset("USD");
  fut.lifecycle = Lifecycle::Dated;
  fut.expiration = "2026-06-19T00:00:00Z";
  r.add_instrument(fut);

  Instrument opt;
  opt.id = "ESM2026_C_6000";
  opt.form = PayoffForm::Option;
  opt.underlying = Ref::to_instrument("ESM2026");
  opt.settlement = Ref::to_instrument("ESM2026");
  opt.lifecycle = Lifecycle::Dated;
  opt.expiration = "2026-06-19T00:00:00Z";
  opt.metadata = {{"strike", "6000"}, {"option_type", "CALL"}};
  r.add_instrument(opt);

  std::cout << "instruments=" << r.instrument_count() << " assets=" << r.asset_count() << "\n";

  const Instrument* o = r.by_id("ESM2026_C_6000");
  std::cout << "option form = " << to_string(o->form) << " (OptionOnFuture is not a type)\n";

  Ref u = r.ultimate_underlying("ESM2026_C_6000");
  std::cout << "ultimate underlying = " << (u.is_asset() ? "asset " : "instrument ") << u.id << "\n";

  std::cout << "all derivatives of SPX:";
  for (const Instrument* p : r.all_derivatives("SPX")) std::cout << " " << p->id;
  std::cout << "\n";

  ValidationResult v = r.validate_all();
  std::cout << "validate_all: " << (v.ok() ? "OK" : "ISSUES") << "\n";
  return v.ok() ? 0 : 1;
}
