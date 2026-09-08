import { $, api, cell, message, page } from "./app.js";
const form = $("#cash-form"),
  trade = $("#trade-form"),
  fx = $("#fx-form"),
  dividend = $("#dividend-form");
let prepared = null,
  txOffset = 0,
  previewSequence = 0,
  refreshSequence = 0,
  detailSequence = 0;
const labels = {
  CASH: "Cash",
  EXTERNAL_CAPITAL_FLOW: "External Capital Flow",
  FX_ADJUSTMENT_RESERVE: "FX Adjustment Reserve",
  INVESTMENT: "Investment",
  REALIZED_TRADE_PNL: "Realized Trade P&L",
  DIVIDEND_INCOME: "Dividend Income",
};
const typeNames = {
  CASH_TRANSFER: "Cash Transfer",
  TRADE: "Trade",
  FX_CONVERSION: "FX Conversion",
  DIVIDEND_RECEIPT: "Dividend Receipt",
  REVERSAL: "Reversal",
};
export function journal(
  container,
  lines,
  accounts = new Map(),
  positionName = null,
) {
  container.replaceChildren();
  table(
    container,
    [
      "Ledger Account",
      "Financial Account",
      "Position",
      "Side",
      "Book Amount (HKD)",
      "Native Amount",
    ],
    lines.map((l) => [
      labels[l.ledger_account_code] || l.ledger_account_code,
      l.financial_account_id
        ? accounts.get(l.financial_account_id) || l.financial_account_id
        : "—",
      l.position_id ? positionName || l.position_id : "—",
      l.side === "DEBIT" ? "Debit" : "Credit",
      l.book_amount,
      l.native_amount === null
        ? "—"
        : l.native_amount + " " + l.native_currency,
    ]),
  );
}
function table(container, headers, rows) {
  const wrap = document.createElement("div");
  wrap.className = "table-wrap";
  const t = document.createElement("table"),
    head = document.createElement("tr");
  for (const s of headers) {
    const th = document.createElement("th");
    th.textContent = s;
    head.append(th);
  }
  t.append(head);
  for (const r of rows) {
    const tr = document.createElement("tr");
    for (const v of r) cell(tr, v ?? "—");
    t.append(tr);
  }
  wrap.append(t);
  container.append(wrap);
}
function selectOptions(select, items) {
  const previous = select.value;
  select.replaceChildren(
    ...items.map(([value, label]) => new Option(label, value)),
  );
  if (items.some(([value]) => value === previous)) select.value = previous;
}
async function options() {
  const [accounts, c, products] = await Promise.all([
    api("/api/accounts"),
    api("/api/configuration"),
    api("/api/instruments/search"),
  ]);
  for (const select of [
    form.elements.source_account_id,
    form.elements.destination_account_id,
    trade.elements.account_id,
    fx.elements.account_id,
    dividend.elements.account_id,
  ])
    selectOptions(
      select,
      accounts.map((a) => [
        a.financial_account_id,
        a.display_name + " (" + a.account_code + ")",
      ]),
    );
  for (const select of [$("#holdings-account"), $("#tx-account")])
    selectOptions(select, [
      ["", "All"],
      ...accounts.map((a) => [a.financial_account_id, a.display_name]),
    ]);
  selectOptions($("#holdings-currency"), [
    ["", "All"],
    ...c.currencies.map((c) => [c.currency_code, c.currency_code]),
    ["UNKNOWN", "Valuation Currency Unknown"],
  ]);
  selectOptions(
    form.elements.currency,
    c.currencies.map((c) => [c.currency_code, c.currency_code]),
  );
  selectOptions(
    trade.elements.product_id,
    products.rows.map((p) => [p.product_id, p.name]),
  );
  for (const select of [
    fx.elements.sell_currency,
    fx.elements.buy_currency,
    dividend.elements.currency,
  ])
    selectOptions(
      select,
      c.currencies.map((c) => [c.currency_code, c.currency_code]),
    );
  const observables = await api("/api/observables");
  selectOptions(
    dividend.elements.observable_id,
    observables.rows.map((o) => [o.observable_id, o.name]),
  );
  await productDetails();
}
async function productDetails() {
  if (!trade.elements.product_id.value) return;
  const id = trade.elements.product_id.value;
  const p = await api("/api/instruments/" + id);
  if (id !== trade.elements.product_id.value) return;
  trade.elements.quote_currency.value = p.quote_observable.code;
  selectOptions(trade.elements.listing_id, [
    ["", "Not Specified"],
    ...p.listings.map((l) => [
      l.listing_id,
      l.venue_segment + " · " + l.venue_id,
    ]),
  ]);
}
trade.elements.product_id.addEventListener("change", () =>
  productDetails().catch((e) => message(e.message, true)),
);
function invalidate() {
  previewSequence++;
  prepared = null;
  $("#cash-preview").hidden = true;
  $("#submit-cash").hidden = true;
}
for (const f of [form, trade, fx, dividend]) {
  f.addEventListener("input", invalidate);
  f.elements.effective_date.value = new Date().toLocaleDateString("en-CA");
}
$("#entry-kind").addEventListener("change", () => {
  form.hidden = $("#entry-kind").value !== "cash";
  trade.hidden = $("#entry-kind").value !== "trade";
  fx.hidden = $("#entry-kind").value !== "fx";
  dividend.hidden = $("#entry-kind").value !== "dividend";
  invalidate();
});
form.elements.direction.addEventListener("change", () => {
  $("#source-label").hidden = form.elements.direction.value === "deposit";
  $("#destination-label").hidden =
    form.elements.direction.value === "withdrawal";
  invalidate();
});
$("#add-fee").addEventListener("click", () => {
  invalidate();
  const row = document.createElement("div");
  row.className = "fee-row";
  const type = document.createElement("select");
  for (const [k, v] of [
    ["COMMISSION", "Commission"],
    ["EXCHANGE_FEE", "Exchange Fee"],
    ["REGULATORY_FEE", "Regulatory Fee"],
    ["OTHER", "Other"],
  ])
    type.add(new Option(v, k));
  type.setAttribute("aria-label", "Fee Type");
  const amount = document.createElement("input");
  amount.placeholder = "Fee Amount";
  amount.setAttribute("aria-label", "Fee Amount");
  amount.inputMode = "decimal";
  const remove = document.createElement("button");
  remove.type = "button";
  remove.textContent = "Remove";
  remove.addEventListener("click", () => {
    row.remove();
    invalidate();
  });
  row.append(type, amount, remove);
  $("#fee-rows").append(row);
});
async function preview(body, path) {
  const sequence = previewSequence;
  try {
    const result = await api("/api/transaction-previews", {
      method: "POST",
      body: JSON.stringify(body),
    });
    if (sequence !== previewSequence) return;
    prepared = { body, path };
    journal($("#cash-preview"), result.journal);
    if (result.allocations?.length)
      table(
        $("#cash-preview"),
        ["Source BUY Transaction", "Disposed Quantity", "Disposed Cost (HKD)"],
        result.allocations.map((a) => [
          a.buy_transaction_id,
          a.quantity_disposed,
          a.book_cost_disposed,
        ]),
      );
    $("#cash-preview").hidden = false;
    $("#submit-cash").hidden = false;
  } catch (e) {
    message(e.message, true);
  }
}
form.addEventListener("submit", async (e) => {
  e.preventDefault();
  invalidate();
  const f = Object.fromEntries(new FormData(form));
  await preview(
    {
      effective_date: f.effective_date,
      currency: f.currency,
      amount: f.amount,
      memo: f.memo || null,
      source_account_id: f.direction === "deposit" ? null : f.source_account_id,
      destination_account_id:
        f.direction === "withdrawal" ? null : f.destination_account_id,
      request_key: crypto.randomUUID(),
    },
    "cash-transfers",
  );
});
trade.addEventListener("submit", async (e) => {
  e.preventDefault();
  invalidate();
  const f = Object.fromEntries(new FormData(trade));
  delete f.quote_currency;
  for (const k of [
    "listing_id",
    "trade_time",
    "scheduled_settlement_date",
    "memo",
  ])
    f[k] = f[k] || null;
  f.fees = [...document.querySelectorAll(".fee-row")].map((r) => ({
    fee_type: r.querySelector("select").value,
    amount: r.querySelector("input").value,
  }));
  f.request_key = crypto.randomUUID();
  await preview(f, "trades");
});
$("#submit-cash").addEventListener("click", async () => {
  if (!prepared) return;
  const button = $("#submit-cash");
  button.disabled = true;
  try {
    const result = await api("/api/transactions/" + prepared.path, {
      method: "POST",
      body: JSON.stringify(prepared.body),
    });
    invalidate();
    form.elements.amount.value = "";
    await refresh();
    await detail(result.transaction_id);
    message("Transaction committed.");
    page("transactions");
  } catch (e) {
    message(e.message, true);
  } finally {
    button.disabled = false;
  }
});
async function detail(id) {
  const sequence = ++detailSequence;
  const tx = await api("/api/transactions/" + id);
  const economic =
    tx.transaction_type === "REVERSAL"
      ? await api("/api/transactions/" + tx.data.target_transaction_id)
      : tx;
  const [accountRows, observables, product] = await Promise.all([
    api("/api/accounts"),
    api("/api/observables"),
    economic.data.product_id
      ? api("/api/instruments/" + economic.data.product_id)
      : null,
  ]);
  if (sequence !== detailSequence) return;
  const accountNames = new Map(
    accountRows.map((a) => [
      a.financial_account_id,
      a.display_name + " (" + a.account_code + ")",
    ]),
  );
  const observable = observables.rows.find(
    (o) =>
      o.observable_id ===
      (economic.observable_id || economic.data.observable_id),
  );
  const container = $("#transaction-detail");
  container.replaceChildren();
  container.hidden = false;
  const title = document.createElement("h2");
  title.textContent =
    "Transaction #" +
    id +
    " · " +
    tx.effective_date +
    " · " +
    typeNames[tx.transaction_type];
  container.append(title);
  const identities = [];
  if (product) {
    identities.push(
      ["Product", product.name],
      ["Observable", product.observable.name],
    );
    const listing = product.listings.find(
      (l) => l.listing_id === economic.data.listing_id,
    );
    const symbol =
      listing &&
      product.identifiers.find(
        (i) =>
          i.target_type === "LISTING" && i.target_id === listing.listing_id,
      );
    identities.push([
      "Listing",
      listing
        ? [
            symbol?.authority || listing.venue_id,
            listing.venue_segment,
            symbol?.identifier,
          ]
            .filter(Boolean)
            .join(" · ")
        : "Not Specified",
    ]);
  } else if (observable)
    identities.push([
      "Dividend Observable",
      observable.name + " (" + observable.code + ")",
    ]);
  for (const [role, accountId] of Object.entries(economic.accounts)) {
    identities.push([
      {
        ACCOUNT: "Financial Account",
        SOURCE: "Source Account",
        DESTINATION: "Destination Account",
      }[role] || role,
      accountNames.get(accountId) || accountId,
    ]);
  }
  if (identities.length) table(container, ["Field", "Value"], identities);
  const desc = document.createElement("p");
  const fieldLabels = {
    amount: "Amount",
    currency: "Currency",
    quantity: "Quantity",
    price: "Price",
    side: "Side",
    trade_date: "Trade Date",
    trade_time: "Trade Time",
    scheduled_settlement_date: "Scheduled Settlement Date",
    sell_amount: "Sell Amount",
    sell_currency: "Sell Currency",
    buy_amount: "Buy Amount",
    buy_currency: "Buy Currency",
    target_transaction_id: "Original Transaction",
  };
  desc.textContent =
    Object.entries(tx.data)
      .filter(([k, v]) => fieldLabels[k] && v !== null)
      .map(([k, v]) => fieldLabels[k] + ": " + v)
      .join(" · ") + (tx.memo ? " · " + tx.memo : "");
  container.append(desc);
  if (tx.data.fees && Object.keys(tx.data.fees).length)
    table(
      container,
      ["Fee Type", "Fee Amount (Quote Currency)"],
      Object.entries(tx.data.fees),
    );
  if (tx.book_fx_evidence?.length)
    table(
      container,
      [
        "Book FX Currency",
        "Applied Rate",
        "Effective Date",
        "Source / Revision",
      ],
      tx.book_fx_evidence.map((f) => [
        f.base_currency,
        f.rate,
        f.effective_date,
        f.source + " / " + f.revision,
      ]),
    );
  const lines = document.createElement("div");
  journal(lines, tx.journal, accountNames, observable?.name);
  container.append(lines);
  if (tx.position_lines?.length)
    table(
      container,
      ["Position Dimension", "Quantity Change"],
      tx.position_lines.map((l) => [
        l.line_type === "OWNERSHIP"
          ? "Ownership / SELF"
          : "Location / Financial Account " + l.financial_account_id,
        l.quantity_delta,
      ]),
    );
  if (tx.lots?.length)
    table(
      container,
      ["Cost Basis Lot", "Acquired Quantity", "Cost (HKD)"],
      tx.lots.map((l) => [
        l.cost_basis_lot_id,
        l.quantity_acquired,
        l.book_cost_basis,
      ]),
    );
  if (tx.allocations?.length)
    table(
      container,
      ["Source BUY Transaction", "Disposed Quantity", "Disposed Cost (HKD)"],
      tx.allocations.map((a) => [
        a.buy_transaction_id,
        a.quantity_disposed,
        a.book_cost_disposed,
      ]),
    );
  if (tx.reversed_by) {
    const p = document.createElement("p");
    p.textContent = "Reversed by Transaction #" + tx.reversed_by;
    container.append(p);
  } else if (tx.transaction_type !== "REVERSAL") {
    const check = document.createElement("button");
    check.textContent = "Check and Preview Reversal";
    check.addEventListener("click", async () => {
      try {
        const preview = await api(
          "/api/transactions/" + id + "/reversal-check",
        );
        const box = document.createElement("div");
        journal(box, preview.journal);
        const submit = document.createElement("button");
        submit.textContent = "Confirm Reversal";
        submit.className = "primary";
        const key = crypto.randomUUID();
        submit.addEventListener("click", async () => {
          submit.disabled = true;
          try {
            const result = await api("/api/transactions/" + id + "/reversal", {
              method: "POST",
              body: JSON.stringify({ request_key: key }),
            });
            await refresh();
            await detail(result.transaction_id);
            message("Reversal committed. The original record is retained.");
          } catch (e) {
            message(e.message, true);
            submit.disabled = false;
          }
        });
        box.append(submit);
        container.append(box);
        check.disabled = true;
      } catch (e) {
        message(e.message, true);
      }
    });
    container.append(check);
  }
}
async function refresh() {
  const sequence = ++refreshSequence;
  const [holdings, transactions] = await Promise.all([
    api("/api/holdings" + holdingsQuery()),
    api("/api/transactions" + transactionQuery()),
  ]);
  if (sequence !== refreshSequence) return;
  const allRows = [...holdings.cash, ...holdings.investments];
  const filter = (r) =>
    (!$("#holdings-asset").value ||
      [r.name, r.code, r.currency]
        .filter(Boolean)
        .some((v) =>
          v.toLowerCase().includes($("#holdings-asset").value.toLowerCase()),
        )) &&
    (!$("#holdings-account").value ||
      r.financial_account_id === $("#holdings-account").value) &&
    (!$("#holdings-class").value ||
      r.asset_class === $("#holdings-class").value) &&
    (!$("#holdings-currency").value ||
      (r.valuation_currency || "UNKNOWN") === $("#holdings-currency").value);
  holdings.cash = holdings.cash.filter(filter);
  holdings.investments = holdings.investments.filter(filter);
  const selected = allRows.filter(filter),
    groups = new Map();
  for (const r of selected) {
    const key = r[$("#holdings-group").value] || "Valuation Currency Unknown";
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(r);
  }
  $("#holding-groups").replaceChildren();
  table(
    $("#holding-groups"),
    [
      "Group",
      "Historical Cost (HKD)",
      "Functional Market Value (HKD)",
      "Valuation Coverage",
    ],
    [...groups].map(([k, rs]) => [
      k,
      displaySum(rs.map((r) => r.book_value)),
      displaySum(
        rs.filter((r) => r.market_value !== null).map((r) => r.market_value),
      ),
      rs.filter((r) => r.market_value !== null).length + "/" + rs.length,
    ]),
  );
  $("#valuation-summary").textContent =
    "Portfolio · " +
    (holdings.valuation.complete
      ? "Total Functional Market Value"
      : "Partial Valuation Total") +
    " HKD " +
    holdings.valuation.valued_subtotal +
    (holdings.valuation.unvalued_count
      ? " · " +
        holdings.valuation.unvalued_count +
        " items have missing quotes and are excluded from the total"
      : "") +
    " · Investment Unrealized Difference" +
    (holdings.valuation.investment_unrealized_complete ? "" : " (Partial)") +
    " HKD " +
    holdings.valuation.investment_unrealized_subtotal;
  const body = $("#cash-rows");
  body.replaceChildren();
  for (const r of holdings.cash) {
    const tr = document.createElement("tr");
    cell(tr, r.account_name);
    const open = document.createElement("button");
    open.textContent = r.currency;
    open.addEventListener("click", () =>
      holdingDetail(
        "/api/cash/" + r.financial_account_id + "/" + r.currency,
      ).catch((e) => message(e.message, true)),
    );
    cell(tr, "").append(open);
    cell(tr, r.quantity).className = "numeric";
    cell(tr, r.book_value).className = "numeric";
    cell(tr, r.market_value ?? "Incomplete Valuation").className = "numeric";
    cell(tr, marketStatus(r));
    body.append(tr);
  }
  $("#cash-panel").hidden = !holdings.cash.length;
  const inv = $("#investment-rows");
  inv.replaceChildren();
  for (const r of holdings.investments) {
    const tr = document.createElement("tr");
    const open = document.createElement("button");
    open.textContent = r.name;
    open.addEventListener("click", () =>
      holdingDetail("/api/holdings/" + r.position_id).catch((e) =>
        message(e.message, true),
      ),
    );
    cell(tr, "").append(open);
    cell(tr, r.account_name);
    cell(tr, r.quantity).className = "numeric";
    cell(tr, r.book_value).className = "numeric";
    cell(tr, r.market_value ?? "Incomplete Valuation").className = "numeric";
    cell(tr, r.unrealized_difference ?? "—").className = "numeric";
    cell(tr, marketStatus(r));
    inv.append(tr);
  }
  $("#investment-panel").hidden = !holdings.investments.length;
  $("#holdings-empty").hidden = holdings.transaction_count > 0;
  $("#tx-page").textContent =
    " " +
    (transactions.total ? txOffset + 1 : 0) +
    "–" +
    Math.min(txOffset + 50, transactions.total) +
    " / " +
    transactions.total +
    " ";
  $("#tx-prev").disabled = txOffset === 0;
  $("#tx-next").disabled = txOffset + 50 >= transactions.total;
  const txbody = $("#transaction-rows");
  txbody.replaceChildren();
  for (const tx of transactions.rows) {
    const tr = document.createElement("tr");
    cell(tr, tx.effective_date);
    cell(tr, typeNames[tx.transaction_type]);
    const b = document.createElement("button");
    b.textContent = "#" + tx.transaction_id;
    b.addEventListener("click", () =>
      detail(tx.transaction_id).catch((e) => message(e.message, true)),
    );
    cell(tr, "").append(b);
    txbody.append(tr);
  }
}
$("#refresh-transactions").addEventListener("click", () =>
  refresh().catch((e) => message(e.message, true)),
);
window.addEventListener("accounts-changed", () =>
  options().catch((e) => message(e.message, true)),
);
try {
  await options();
  await refresh();
} catch (e) {
  message(e.message, true);
}

for (const [f, path] of [
  [fx, "fx-conversions"],
  [dividend, "dividends"],
])
  f.addEventListener("submit", async (e) => {
    e.preventDefault();
    invalidate();
    const body = Object.fromEntries(new FormData(f));
    body.memo = body.memo || null;
    body.request_key = crypto.randomUUID();
    await preview(body, path);
  });

function asOfQuery() {
  const value = $("#as-of").value;
  return value ? "?as_of=" + encodeURIComponent(value) : "";
}
$("#as-of").addEventListener("change", () =>
  refresh().catch((e) => message(e.message, true)),
);

function marketStatus(r) {
  return r.valuation_status === "MISSING_PRICE"
    ? "Missing Market Price"
    : r.valuation_status === "MISSING_FX"
      ? "Missing " + r.valuation_currency + " Market FX"
      : [r.price_as_of, r.fx_as_of].filter(Boolean).join(" / ");
}

function transactionQuery() {
  const q = new URLSearchParams();
  if ($("#as-of").value) q.set("as_of", $("#as-of").value);
  if ($("#tx-account").value) q.set("account_id", $("#tx-account").value);
  if ($("#tx-type").value) q.set("transaction_type", $("#tx-type").value);
  if ($("#tx-from").value) q.set("date_from", $("#tx-from").value);
  q.set("offset", String(txOffset));
  return "?" + q;
}
for (const id of [
  "holdings-account",
  "holdings-class",
  "holdings-currency",
  "holdings-group",
  "tx-account",
  "tx-type",
  "tx-from",
])
  $("#" + id).addEventListener("change", () => {
    txOffset = 0;
    refresh().catch((e) => message(e.message, true));
  });
$("#tx-prev").addEventListener("click", () => {
  txOffset = Math.max(0, txOffset - 50);
  refresh().catch((e) => message(e.message, true));
});
$("#tx-next").addEventListener("click", () => {
  txOffset += 50;
  refresh().catch((e) => message(e.message, true));
});
async function holdingDetail(path) {
  const r = await api(path + asOfQuery()),
    box = $("#holding-detail");
  box.hidden = false;
  box.replaceChildren();
  const title = document.createElement("h2");
  title.textContent = r.name || r.currency + " · " + r.quantity;
  box.append(title);
  if (r.lots)
    table(
      box,
      [
        "BUY Transaction",
        "Financial Account",
        "Remaining Quantity",
        "Remaining Cost (HKD)",
      ],
      r.lots.map((l) => [
        l.buy_transaction_id,
        l.financial_account_id,
        l.remaining_quantity,
        l.remaining_book_cost,
      ]),
    );
  if (r.lines)
    table(
      box,
      ["Effective Date", "Transaction", "Side", "Native Amount", "Cost (HKD)"],
      r.lines.map((l) => [
        l.effective_date,
        l.transaction_id,
        l.side,
        l.native_amount,
        l.book_amount,
      ]),
    );
  for (const id of r.transaction_ids || [
    ...new Set(r.lines.map((l) => l.transaction_id)),
  ]) {
    const b = document.createElement("button");
    b.textContent = "Transaction #" + id;
    b.addEventListener("click", () => {
      page("transactions");
      detail(id).catch((e) => message(e.message, true));
    });
    box.append(b);
  }
}
// Exact decimal addition for display grouping only. Canonical amounts remain server-owned.
function displaySum(values) {
  const parts = values.map((v) => {
    const sign = v.startsWith("-") ? -1n : 1n;
    const [i, f = ""] = v.replace(/^-/, "").split(".");
    return { sign, i, f };
  });
  const scale = Math.max(0, ...parts.map((p) => p.f.length));
  const total = parts.reduce(
    (n, p) => n + p.sign * BigInt(p.i + p.f.padEnd(scale, "0")),
    0n,
  );
  const sign = total < 0n ? "-" : "";
  let text = (total < 0n ? -total : total).toString().padStart(scale + 1, "0");
  return (
    sign + (scale ? text.slice(0, -scale) + "." + text.slice(-scale) : text)
  );
}

window.addEventListener("holdings-changed", () =>
  refresh().catch((e) => message(e.message, true)),
);

function holdingsQuery() {
  const q = new URLSearchParams();
  if ($("#as-of").value) q.set("as_of", $("#as-of").value);
  if (!$("#hide-zero").checked) q.set("include_zero", "true");
  return "?" + q;
}
$("#hide-zero").addEventListener("change", () =>
  refresh().catch((e) => message(e.message, true)),
);
$("#holdings-asset").addEventListener("input", () =>
  refresh().catch((e) => message(e.message, true)),
);
