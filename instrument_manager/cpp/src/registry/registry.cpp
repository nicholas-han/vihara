/**
 * @file  registry.cpp
 * @brief Implementation of `InstrumentRegistry` (ADR-14): the in-memory snapshot of
 *        observables / products / listings, the multi-leg underlier DAG, the
 *        `ObservableResolver` surface, and the registry-wide `validate_all()` load gate.
 *
 * Design contracts realized here (see docs/10-layered-model.md §2, §4 and
 * docs/70-persistence-and-cpp.md §6.2–§6.3):
 *   - `derivatives_` is populated PER LEG: every leg whose underlier is a
 *     `Ref{Product}` or `Ref{Observable}` contributes an edge `underlier_id ->
 *     product_id`. A two-leg swap contributes two edges.
 *   - `ultimate_underliers` returns the SET of L0 leaves reached across all legs of
 *     all nested products (fan-out, not a single chain), deduped into a vector<Ref>.
 *   - `validate_all()` re-runs intra-leg + cross-leg `validate(Product)` using the
 *     registry itself as the resolver, then the registry-wide invariants: all refs
 *     resolve, the multi-leg DAG is acyclic (visited-set DFS), and
 *     OutcomePartitionExactlyOne holds across each prediction-market group.
 */
#include "registry/registry.hpp"

#include <algorithm>
#include <functional>
#include <unordered_set>
#include <utility>

#include "core/payout_leg.hpp"
#include "symbology/symbol.hpp"

namespace instrument_manager {

namespace {

constexpr char kSep = '\x1F';  // unit separator for compound map keys

std::string venue_key(std::string_view venue, std::string_view segment,
                      std::string_view symbol) {
  std::string k;
  k.reserve(venue.size() + segment.size() + symbol.size() + 2);
  k.append(venue.data(), venue.size());
  k.push_back(kSep);
  k.append(segment.data(), segment.size());
  k.push_back(kSep);
  k.append(symbol.data(), symbol.size());
  return k;
}

std::string external_key(std::string_view scheme, std::string_view identifier) {
  std::string k;
  k.reserve(scheme.size() + identifier.size() + 1);
  k.append(scheme.data(), scheme.size());
  k.push_back(kSep);
  k.append(identifier.data(), identifier.size());
  return k;
}

/// Append the underlier `Ref`s a single leg points at (the edges it contributes to
/// the multi-leg DAG / the leaf-set walk). A leg's `Underlier` arm may be a single
/// `Ref` or an inline `Basket` (each component is an edge). Pure cashflow legs
/// (Fixed, Principal) contribute no underlier edge. `Ref::Kind::None` is skipped.
void collect_underlier_refs(const l1::PayoutLeg& leg, std::vector<Ref>& out) {
  auto push = [&out](const Ref& r) {
    if (!r.is_none()) out.push_back(r);
  };
  auto push_underlier = [&](const l1::Underlier& u) {
    if (const Ref* r = std::get_if<Ref>(&u)) {
      push(*r);
    } else if (const l1::Basket* b = std::get_if<l1::Basket>(&u)) {
      for (const auto& comp : b->components) push(comp.ref);
    }
  };

  std::visit(
      [&](const auto& l) {
        using L = std::decay_t<decltype(l)>;
        if constexpr (std::is_same_v<L, l1::HoldingLeg>) {
          push(l.asset);
        } else if constexpr (std::is_same_v<L, l1::ForwardLeg>) {
          push_underlier(l.underlier);
        } else if constexpr (std::is_same_v<L, l1::PerpetualLeg>) {
          push_underlier(l.underlier);
        } else if constexpr (std::is_same_v<L, l1::OptionLeg>) {
          push_underlier(l.underlier);
        } else if constexpr (std::is_same_v<L, l1::DigitalLeg>) {
          push_underlier(l.underlier);
        } else if constexpr (std::is_same_v<L, l1::FloatingRateLeg>) {
          push(l.index);
        } else if constexpr (std::is_same_v<L, l1::PerformanceLeg>) {
          push_underlier(l.underlier);
        } else if constexpr (std::is_same_v<L, l1::VarianceLeg>) {
          push_underlier(l.underlier);
        } else if constexpr (std::is_same_v<L, l1::FundingLeg>) {
          push(l.funding_index);
        } else if constexpr (std::is_same_v<L, l1::CreditProtectionLeg>) {
          push(l.credit);
        } else if constexpr (std::is_same_v<L, l1::ClaimLeg>) {
          push(l.pool);
        }
        // FixedRateLeg, PrincipalLeg: pure cashflow streams; no underlier edge.
      },
      leg);
}

}  // namespace

// ---- build / ingest ---------------------------------------------------------

void InstrumentRegistry::add_observable(Observable obs) {
  std::string id = obs.id;
  observables_[std::move(id)] = std::move(obs);
}

void InstrumentRegistry::add_product(l1::Product product) {
  const std::string product_id = product.id;
  // Populate the per-leg underlier DAG: one edge per leg whose underlier is a
  // Ref{Product} or Ref{Observable}.
  std::vector<Ref> refs;
  for (const auto& leg : product.legs) {
    refs.clear();
    collect_underlier_refs(leg.payout, refs);
    for (const Ref& r : refs) {
      if (r.is_product() || r.is_observable()) {
        derivatives_[r.id].push_back(product_id);
      }
    }
  }
  products_[product_id] = std::move(product);
}

void InstrumentRegistry::add_listing(Listing listing) {
  const std::string listing_id = listing.id;
  venue_symbols_[venue_key(listing.venue_id, listing.venue_segment,
                           listing.venue_symbol)] = listing_id;
  listings_[listing_id] = std::move(listing);
}

void InstrumentRegistry::add_event_outcome(EventOutcome outcome) {
  std::string id = outcome.id;
  event_outcomes_[std::move(id)] = std::move(outcome);
}

// ---- by opaque id, per layer ------------------------------------------------

const Observable* InstrumentRegistry::observable_by_id(std::string_view id) const {
  auto it = observables_.find(std::string(id));
  return it == observables_.end() ? nullptr : &it->second;
}

const l1::Product* InstrumentRegistry::product_by_id(std::string_view id) const {
  auto it = products_.find(std::string(id));
  return it == products_.end() ? nullptr : &it->second;
}

const Listing* InstrumentRegistry::listing_by_id(std::string_view id) const {
  auto it = listings_.find(std::string(id));
  return it == listings_.end() ? nullptr : &it->second;
}

// ---- by venue symbol (segment is in the key) --------------------------------

const Listing* InstrumentRegistry::by_venue_symbol(std::string_view venue,
                                                   std::string_view segment,
                                                   std::string_view symbol) const {
  auto it = venue_symbols_.find(venue_key(venue, segment, symbol));
  if (it == venue_symbols_.end()) return nullptr;
  return listing_by_id(it->second);
}

// ---- listings of a product --------------------------------------------------

std::vector<const Listing*> InstrumentRegistry::listings_of_product(
    std::string_view product_id) const {
  std::vector<const Listing*> out;
  for (const auto& [id, listing] : listings_) {
    (void)id;
    if (listing.product_id == product_id) out.push_back(&listing);
  }
  return out;
}

// ---- external identifiers ---------------------------------------------------

const std::string* InstrumentRegistry::product_by_external_id(
    std::string_view scheme, std::string_view identifier) const {
  auto it = external_ids_.find(external_key(scheme, identifier));
  return it == external_ids_.end() ? nullptr : &it->second;
}

// ---- multi-leg graph (ADR-14) -----------------------------------------------

std::vector<const l1::Product*> InstrumentRegistry::direct_derivatives(
    std::string_view ref_id) const {
  std::vector<const l1::Product*> out;
  auto it = derivatives_.find(std::string(ref_id));
  if (it == derivatives_.end()) return out;
  // A product with N legs referencing ref_id appears N times in the edge list;
  // dedup so each derived product is returned once.
  std::unordered_set<std::string> seen;
  for (const std::string& pid : it->second) {
    if (!seen.insert(pid).second) continue;
    if (const l1::Product* p = product_by_id(pid)) out.push_back(p);
  }
  return out;
}

std::vector<Ref> InstrumentRegistry::ultimate_underliers(
    std::string_view product_id) const {
  std::vector<Ref> leaves;
  std::unordered_set<std::string> leaf_seen;   // dedup the result set
  std::unordered_set<std::string> visited;     // cycle protection across the DAG

  std::vector<Ref> leg_refs;
  std::function<void(const std::string&)> walk = [&](const std::string& pid) {
    if (!visited.insert(pid).second) return;  // already expanded; cycle-safe
    const l1::Product* p = product_by_id(pid);
    if (!p) return;
    for (const auto& leg : p->legs) {
      leg_refs.clear();
      collect_underlier_refs(leg.payout, leg_refs);
      for (const Ref& r : leg_refs) {
        if (r.is_product()) {
          walk(r.id);  // fan out into the nested product's legs
        } else if (r.is_observable()) {
          if (leaf_seen.insert(r.id).second) leaves.push_back(r);  // L0 leaf
        }
        // Ref::Kind::Listing / None are not L0 leaves; ignore.
      }
    }
  };
  walk(std::string(product_id));
  return leaves;
}

// ---- ObservableResolver -----------------------------------------------------

std::optional<AssetKind> InstrumentRegistry::kind_of(std::string_view id) const {
  if (const Observable* obs = observable_by_id(id)) return obs->kind;
  return std::nullopt;
}

std::optional<std::string> InstrumentRegistry::symbol_of(std::string_view id) const {
  if (const Observable* obs = observable_by_id(id)) return obs->code;
  if (const l1::Product* p = product_by_id(id)) {
    return symbology::canonical_symbol(*p, *this);
  }
  return std::nullopt;
}

const l1::Product* InstrumentRegistry::find_product(std::string_view id) const {
  return product_by_id(id);
}

// ---- registry-wide load gate ------------------------------------------------

ValidationResult InstrumentRegistry::validate_all() const {
  ValidationResult result;

  // 1. Intra-leg + cross-leg validation of every product, resolving refs through
  //    the registry itself (it IS-A ObservableResolver).
  for (const auto& [pid, product] : products_) {
    (void)pid;
    result.merge(validate(product, *this));
  }

  // 2. Referential integrity: every underlier Ref on every leg, plus each
  //    product's quote_asset / settlement, must resolve to an existing row.
  auto resolve_ref = [&](const Ref& r, const std::string& entity_id,
                         const char* role) {
    if (r.is_none()) return;
    bool ok = false;
    switch (r.kind) {
      case Ref::Kind::Observable:
        ok = observable_by_id(r.id) != nullptr;
        break;
      case Ref::Kind::Product:
        ok = product_by_id(r.id) != nullptr;
        break;
      case Ref::Kind::Listing:
        ok = listing_by_id(r.id) != nullptr;
        break;
      case Ref::Kind::None:
        ok = true;
        break;
    }
    if (!ok) {
      result.add_error("REF_UNRESOLVED", entity_id,
                       std::string(role) + " ref '" + r.id + "' does not resolve");
    }
  };

  std::vector<Ref> leg_refs;
  for (const auto& [pid, product] : products_) {
    resolve_ref(product.quote_asset, pid, "quote_asset");
    resolve_ref(product.settlement, pid, "settlement");
    for (const auto& leg : product.legs) {
      leg_refs.clear();
      collect_underlier_refs(leg.payout, leg_refs);
      for (const Ref& r : leg_refs) resolve_ref(r, leg.leg_id, "underlier");
    }
  }

  // 3. DAG acyclicity across all legs of all nested products (visited-set DFS).
  //    A product underlier edge p -> q (q nested in p) must not cycle back.
  enum class Color { White, Gray, Black };
  std::unordered_map<std::string, Color> color;
  std::vector<Ref> dfs_refs;
  std::function<void(const std::string&)> dfs = [&](const std::string& pid) {
    color[pid] = Color::Gray;
    const l1::Product* p = product_by_id(pid);
    if (p) {
      for (const auto& leg : p->legs) {
        dfs_refs.clear();
        collect_underlier_refs(leg.payout, dfs_refs);
        for (const Ref& r : dfs_refs) {
          if (!r.is_product()) continue;
          auto c = color.find(r.id);
          if (c != color.end() && c->second == Color::Gray) {
            result.add_error("DAG_CYCLE", pid,
                             "underlier nesting cycle through product '" + r.id +
                                 "'");
          } else if (c == color.end() || c->second == Color::White) {
            dfs(r.id);
          }
        }
      }
    }
    color[pid] = Color::Black;
  };
  for (const auto& [pid, product] : products_) {
    (void)product;
    if (color.find(pid) == color.end()) dfs(pid);
  }

  // 4. OutcomePartitionExactlyOne across each prediction-market group. A
  //    categorical market is N single-leg DigitalLeg(EventResolves) products that
  //    share one Event observable; exactly one outcome must resolve. The group is
  //    keyed by the shared Event underlier id. Each member's outcome_code must be a
  //    distinct member of that event's outcome space, and at most one outcome may
  //    carry a resolved_value at any time (post-resolution: exactly one).
  struct PartitionMember {
    std::string product_id;
    std::string outcome_code;
  };
  std::unordered_map<std::string, std::vector<PartitionMember>> groups;  // event id -> members
  for (const auto& [pid, product] : products_) {
    // Members are single-leg DigitalLeg(EventResolves) products that declare an
    // OutcomePartitionExactlyOne constraint.
    bool declares_partition = false;
    for (const auto& c : product.constraints) {
      if (c.kind == l1::ConstraintKind::OutcomePartitionExactlyOne) {
        declares_partition = true;
        break;
      }
    }
    if (!declares_partition) continue;
    if (product.legs.size() != 1) continue;
    const l1::PayoutLeg& payout = product.legs.front().payout;
    const l1::DigitalLeg* dig = std::get_if<l1::DigitalLeg>(&payout);
    if (!dig || dig->trigger != l1::DigitalLeg::Trigger::EventResolves) continue;
    const Ref* event_ref = std::get_if<Ref>(&dig->underlier);
    if (!event_ref || !event_ref->is_observable()) continue;
    groups[event_ref->id].push_back({pid, dig->outcome_code});
  }

  for (const auto& [event_id, members] : groups) {
    // Each member's outcome_code must be unique within the group (no two products
    // claim the same outcome).
    std::unordered_set<std::string> seen_codes;
    for (const auto& m : members) {
      if (!seen_codes.insert(m.outcome_code).second) {
        result.add_error(
            "OUTCOME_PARTITION_EXACTLY_ONE", event_id,
            "duplicate outcome_code '" + m.outcome_code +
                "' in prediction group for event '" + event_id + "'");
      }
    }

    // Tally the declared outcome space for this event and how many have resolved.
    std::vector<const EventOutcome*> outcomes;
    int resolved_count = 0;
    for (const auto& [oid, oc] : event_outcomes_) {
      (void)oid;
      if (oc.asset_id == event_id) {
        outcomes.push_back(&oc);
        if (oc.resolved_value.has_value()) ++resolved_count;
      }
    }

    // The product partition must cover exactly the mutually-exclusive outcome
    // space: every member's outcome_code must be a real outcome of the event, and
    // every mutually-exclusive outcome must have a member product.
    std::unordered_set<std::string> declared_codes;
    for (const auto* oc : outcomes) {
      if (oc->is_mutually_exclusive) declared_codes.insert(oc->outcome_code);
    }
    for (const auto& m : members) {
      if (!declared_codes.count(m.outcome_code)) {
        result.add_error(
            "OUTCOME_PARTITION_EXACTLY_ONE", m.product_id,
            "outcome_code '" + m.outcome_code +
                "' is not a mutually-exclusive outcome of event '" + event_id +
                "'");
      }
    }
    std::unordered_set<std::string> member_codes;
    for (const auto& m : members) member_codes.insert(m.outcome_code);
    for (const std::string& code : declared_codes) {
      if (!member_codes.count(code)) {
        result.add_error(
            "OUTCOME_PARTITION_EXACTLY_ONE", event_id,
            "mutually-exclusive outcome '" + code + "' of event '" + event_id +
                "' has no partition-member product");
      }
    }

    // Resolution invariant: at most one outcome may be resolved at any time;
    // once resolved, EXACTLY one. (>1 resolved is always an error.)
    if (resolved_count > 1) {
      result.add_error(
          "OUTCOME_PARTITION_EXACTLY_ONE", event_id,
          "event '" + event_id + "' has " + std::to_string(resolved_count) +
              " resolved outcomes; a mutually-exclusive partition resolves to one");
    }
  }

  return result;
}

}  // namespace instrument_manager
