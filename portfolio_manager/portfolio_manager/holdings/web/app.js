export const $ = (s) => document.querySelector(s);
export const message = (text, error = false) => {
  const el = $("#message");
  el.textContent = text;
  el.classList.toggle("error", error);
  el.hidden = false;
};
export async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: { "Content-Type": "application/json", ...options.headers },
  });
  const data = await response.json();
  if (!response.ok)
    throw new Error(
      (data.error?.message || "Request failed. Please try again.") +
        (data.error?.related_transaction_ids?.length
          ? " Affected transactions: " +
            data.error.related_transaction_ids.join(", ")
          : ""),
    );
  return data;
}
export function page(name) {
  for (const section of [
    "holdings",
    "settings",
    "transactions",
    "entry",
    "imports",
  ])
    $(`#${section}`).hidden = section !== name;
  for (const b of document.querySelectorAll("[data-page]")) {
    if (b.dataset.page === name) b.setAttribute("aria-current", "page");
    else b.removeAttribute("aria-current");
  }
}
for (const b of document.querySelectorAll("[data-page]"))
  b.addEventListener("click", () => page(b.dataset.page));
$("#setup-account").addEventListener("click", () => {
  page("settings");
  $("[name=account_code]").focus();
});
export function cell(row, text) {
  const td = document.createElement("td");
  td.textContent = text;
  row.append(td);
  return td;
}
async function accounts() {
  const rows = await api("/api/accounts");
  const body = $("#accounts");
  body.replaceChildren();
  if (!rows.length) {
    const tr = document.createElement("tr");
    cell(tr, "No Financial Accounts").colSpan = 5;
    body.append(tr);
  }
  for (const account of rows) {
    const tr = document.createElement("tr");
    cell(tr, account.account_code);
    cell(tr, account.display_name);
    cell(tr, account.institution_type);
    cell(tr, account.country_or_region || "—");
    const info = cell(tr, "");
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = "View References";
    button.addEventListener("click", async () => {
      button.disabled = true;
      try {
        const [scopes, references] = await Promise.all([
          api(`/api/accounts/${account.financial_account_id}/position-scopes`),
          api(`/api/accounts/${account.financial_account_id}/external-account-references`),
        ]);
        const details = document.createElement("p");
        details.textContent = "Position holdings: " + (scopes.map(s =>
          (s.scope_code === "DEFAULT" ? "Account default holdings" : s.display_name) +
          (s.tax_scheme_name ? " · " + s.tax_scheme_name : "")).join("; ") || "None") +
          ". External references: " + (references.map(r => r.external_account_number).join(", ") || "None");
        info.append(details);
      } catch (e) {
        message(e.message, true);
        button.disabled = false;
      }
    });
    info.append(button);
    body.append(tr);
  }
}
$("#account-form [name=institution_type]").addEventListener("change", event => {
  $("#account-has-positions").checked = event.target.value === "BROKER-DEALER";
});
$("#account-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget,
    button = form.querySelector("button");
  button.disabled = true;
  try {
    await api("/api/accounts", {
      method: "POST",
      body: JSON.stringify({
        account_code: form.elements.account_code.value,
        display_name: form.elements.display_name.value,
        institution_type: form.elements.institution_type.value,
        country_or_region: form.elements.country_or_region.value.trim() || null,
        position_scopes: $("#account-has-positions").checked
          ? [{scope_code: "DEFAULT", display_name: "Default"}] : [],
      }),
    });
    form.reset();
    await accounts();
    window.dispatchEvent(new Event("accounts-changed"));
    message("Financial Account created.");
  } catch (e) {
    message(e.message, true);
  } finally {
    button.disabled = false;
  }
});
let searchSequence = 0;
async function instruments() {
  const seq = ++searchSequence;
  const data = await api(
    "/api/instruments/search?q=" +
      encodeURIComponent($("#instrument-search").value),
  );
  if (seq !== searchSequence) return;
  const body = $("#instruments");
  body.replaceChildren();
  for (const p of data.rows) {
    const tr = document.createElement("tr");
    const button = document.createElement("button");
    button.textContent = p.code;
    button.addEventListener("click", () =>
      detail(p.product_id).catch((e) => message(e.message, true)),
    );
    cell(tr, "").append(button);
    cell(tr, p.name);
    cell(tr, p.asset_class);
    cell(tr, p.currency);
    body.append(tr);
  }
  if (!data.rows.length) {
    const tr = document.createElement("tr");
    cell(tr, "No matching Products").colSpan = 4;
    body.append(tr);
  }
}
async function detail(id) {
  const p = await api("/api/instruments/" + encodeURIComponent(id));
  const el = $("#instrument-detail");
  el.replaceChildren();
  el.hidden = false;
  const title = document.createElement("h3");
  title.textContent = p.name;
  el.append(title);
  const dl = document.createElement("dl");
  for (const [label, value] of [
    ["Observable", p.observable.name],
    ["Quote Observable", p.quote_observable.name],
    ["Product ID", p.product_id],
    ["Observable ID", p.asset_observable_id],
    [
      "HoldingLeg",
      p.holding_leg
        ? `${p.holding_leg.leg_id} · ${p.holding_leg.direction || "RECEIVE"} · ${p.observable.name} / ${p.quote_observable.code}`
        : "Not Specified",
    ],
    [
      "ExternalIdentifiers",
      (p.identifiers || [])
        .map(
          (i) =>
            `${i.scheme || "Identifier"}: ${i.identifier} · ${i.authority || "No Authority"} · ${i.target_type} ${i.target_id} · ${i.valid_from || "Unspecified"} to ${i.valid_to || "Open Ended"}`,
        )
        .join("; ") || "Not Specified",
    ],
    [
      "Available Listings",
      p.listings.map((l) => l.venue_segment + " · " + l.venue_id).join(" / ") ||
        "Not Specified",
    ],
  ]) {
    const dt = document.createElement("dt");
    dt.textContent = label;
    const dd = document.createElement("dd");
    dd.textContent = value;
    dl.append(dt, dd);
  }
  el.append(dl);
}
$("#instrument-search").addEventListener("input", () =>
  instruments().catch((e) => message(e.message, true)),
);
try {
  const c = await api("/api/configuration");
  $("#currency-label").textContent =
    "Functional Currency: " + c.functional_currency;
  $("#config-description").textContent =
    `Owner: SELF · Functional Currency: ${c.functional_currency}`;
  $("#currencies").textContent =
    "Supported Cash Currencies: " +
    c.currencies.map((x) => x.currency_code).join(", ");
  await Promise.all([accounts(), instruments()]);
} catch (e) {
  message(e.message, true);
}
