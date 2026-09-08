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
    cell(tr, "No Financial Accounts").colSpan = 3;
    body.append(tr);
  }
  for (const account of rows) {
    const tr = document.createElement("tr");
    cell(tr, account.account_code);
    const nameCell = cell(tr, account.display_name);
    const actions = cell(tr, "");
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = "Rename";
    button.addEventListener("click", () => {
      button.disabled = true;
      const form = document.createElement("form");
      form.className = "account-rename-form";
      const input = document.createElement("input");
      input.name = "display_name";
      input.value = account.display_name;
      input.required = true;
      input.maxLength = 200;
      input.setAttribute("aria-label", "Financial Account Display Name");
      const save = document.createElement("button");
      save.type = "submit";
      save.textContent = "Save";
      const cancel = document.createElement("button");
      cancel.type = "button";
      cancel.textContent = "Cancel";
      const close = () => {
        nameCell.textContent = account.display_name;
        button.disabled = false;
        button.focus();
      };
      cancel.addEventListener("click", close);
      form.addEventListener("keydown", (event) => {
        if (event.key === "Escape" && !cancel.disabled) {
          event.preventDefault();
          close();
        }
      });
      input.addEventListener("input", () => input.setCustomValidity(""));
      form.addEventListener("submit", async (event) => {
        event.preventDefault();
        if (save.disabled) return;
        const value = input.value.trim();
        if (!value) {
          input.setCustomValidity("Enter a Financial Account Display Name.");
          input.reportValidity();
          return;
        }
        input.disabled = save.disabled = cancel.disabled = true;
        try {
          await api(`/api/accounts/${account.financial_account_id}`, {
            method: "PATCH",
            body: JSON.stringify({ display_name: value }),
          });
          account.display_name = value;
          close();
          window.dispatchEvent(new Event("accounts-changed"));
          message("Financial Account name updated.");
        } catch (e) {
          message(e.message, true);
          input.disabled = save.disabled = cancel.disabled = false;
          input.focus();
        }
      });
      form.append(input, save, cancel);
      nameCell.replaceChildren(form);
      input.focus();
      input.select();
    });
    actions.append(button);
    body.append(tr);
  }
}
$("#account-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget,
    button = form.querySelector("button");
  button.disabled = true;
  try {
    await api("/api/accounts", {
      method: "POST",
      body: JSON.stringify(Object.fromEntries(new FormData(form))),
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
