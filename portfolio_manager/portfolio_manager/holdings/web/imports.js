import { $, api, cell, message } from "./app.js";
import { journal } from "./transactions.js";
let current = null,
  viewSequence = 0,
  ready = false;
const busy = new Set();
function updateActions() {
  const disabled = current === null || busy.has(current);
  $("#preview-import").disabled = disabled;
  $("#commit-import").disabled = disabled || !ready;
}
async function history() {
  const data = await api("/api/imports");
  const box = $("#import-history");
  box.replaceChildren();
  for (const batch of data.rows) {
    const b = document.createElement("button");
    b.textContent = "#" + batch.batch_id + " " + batch.filename;
    b.addEventListener("click", () =>
      show(batch.batch_id).catch((e) => message(e.message, true)),
    );
    box.append(b);
  }
}
async function show(id) {
  id = String(id);
  const sequence = ++viewSequence;
  current = null;
  ready = false;
  $("#import-batch").hidden = true;
  updateActions();
  const batch = await api("/api/imports/" + id);
  if (sequence !== viewSequence) return;
  current = id;
  ready = batch.rows.some((r) => r.status === "READY");
  updateActions();
  $("#import-batch").hidden = false;
  $("#import-title").textContent = "#" + id + " · " + batch.filename;
  const box = $("#import-result");
  box.replaceChildren();
  const counts = document.createElement("p");
  counts.textContent =
    "Total: " +
    batch.rows.length +
    " rows · Ready: " +
    batch.rows.filter((r) => r.status === "READY").length +
    " · Errors: " +
    batch.rows.filter((r) => r.status === "ERROR").length +
    " · Processed: " +
    batch.rows.filter((r) => r.transaction_id).length;
  box.append(counts);
  const wrap = document.createElement("div");
  wrap.className = "table-wrap";
  const table = document.createElement("table");
  const head = document.createElement("tr");
  for (const label of [
    "Row",
    "Effective Date / Transaction Type",
    "Status",
    "Information",
    "Mapping",
  ]) {
    const th = document.createElement("th");
    th.textContent = label;
    head.append(th);
  }
  table.append(head);
  for (const row of batch.rows) {
    const tr = document.createElement("tr");
    cell(tr, String(row.row_number));
    cell(
      tr,
      (row.raw.effective_date || "") + " / " + (row.raw.transaction_type || ""),
    );
    cell(
      tr,
      {
        STAGED: "Staged",
        READY: "Ready",
        ERROR: "Error",
        COMMITTED: "Committed",
        DUPLICATE: "Duplicate (Linked)",
      }[row.status],
    );
    cell(
      tr,
      row.transaction_id
        ? "Transaction #" + row.transaction_id
        : row.error?.message
          ? /[\u3400-\u9fff]/u.test(row.error.message)
            ? "Legacy validation result (" +
              (row.error.code || "ERROR") +
              "). Preview this row again for current details."
            : row.error.message
          : "",
    );
    const actions = cell(tr, "");
    const inspect = document.createElement("button");
    inspect.textContent = "View Details";
    inspect.addEventListener("click", () => {
      const details = document.createElement("div");
      details.className = "panel";
      const data = row.payload?.input || row.payload || row.raw;
      const p = document.createElement("p");
      const labels = {
        amount: "Amount",
        currency: "Currency",
        quantity: "Quantity",
        price: "Price",
        side: "Side",
        sell_amount: "Sell Amount",
        sell_currency: "Sell Currency",
        buy_amount: "Buy Amount",
        buy_currency: "Buy Currency",
        effective_date: "Effective Date",
      };
      p.textContent = Object.entries(data)
        .filter(([k]) => labels[k])
        .map(([k, v]) => labels[k] + "：" + v)
        .join(" · ");
      details.append(p);
      if (row.payload?.journal) {
        const lines = document.createElement("div");
        journal(lines, row.payload.journal);
        details.append(lines);
      }
      box.prepend(details);
    });
    actions.append(inspect);
    if (!row.transaction_id) {
      const b = document.createElement("button");
      b.textContent = "Adjust Mapping";
      b.addEventListener("click", () =>
        mapping(row).catch((e) => message(e.message, true)),
      );
      actions.append(b);
    }
    table.append(tr);
  }
  wrap.append(table);
  box.append(wrap);
}
async function mapping(row) {
  const batchId = String(row.batch_id),
    sequence = viewSequence;
  const box = $("#import-result");
  const panel = document.createElement("form");
  panel.className = "entry-form panel";
  const [accounts, products, observables] = await Promise.all([
    api("/api/accounts"),
    api("/api/instruments/search"),
    api("/api/observables"),
  ]);
  if (current !== batchId || sequence !== viewSequence) return;
  const merged = { ...row.raw, ...row.override };
  const fields =
    row.raw.transaction_type === "CASH_TRANSFER"
      ? ["source_account_code", "destination_account_code"]
      : ["account_code"];
  if (row.raw.transaction_type === "TRADE") fields.push("product_id");
  if (row.raw.transaction_type === "DIVIDEND_RECEIPT")
    fields.push("observable_id");
  for (const field of fields) {
    const label = document.createElement("label");
    label.textContent = {
      account_code: "Financial Account",
      source_account_code: "Source Account",
      destination_account_code: "Destination Account",
      product_id: "Product",
      observable_id: "Dividend Observable",
    }[field];
    const select = document.createElement("select");
    select.name = field;
    select.add(new Option("Keep Original Mapping", ""));
    const options = field.endsWith("account_code")
      ? accounts.map((a) => [a.account_code, a.display_name])
      : field === "product_id"
        ? products.rows.map((p) => [p.product_id, p.name])
        : observables.rows.map((o) => [o.observable_id, o.name]);
    for (const [v, name] of options) select.add(new Option(name, v));
    select.value = merged[field] || "";
    label.append(select);
    panel.append(label);
  }
  const save = document.createElement("button");
  save.textContent = "Save Mapping and Preview";
  panel.append(save);
  panel.addEventListener("submit", async (e) => {
    e.preventDefault();
    if (current !== batchId || sequence !== viewSequence || busy.has(batchId))
      return;
    save.disabled = true;
    busy.add(batchId);
    updateActions();
    try {
      const values = Object.fromEntries(
        [...new FormData(panel)].filter(([k, v]) => v),
      );
      if (values.product_id) values.listing_id = "";
      await api("/api/import-rows/" + row.row_id, {
        method: "PATCH",
        body: JSON.stringify({ mapping: values }),
      });
      await api("/api/imports/" + batchId + "/preview", { method: "POST" });
      if (current === batchId && sequence === viewSequence) await show(batchId);
    } catch (e) {
      message(e.message, true);
      save.disabled = false;
    } finally {
      busy.delete(batchId);
      updateActions();
    }
  });
  box.prepend(panel);
}
$("#upload-import").addEventListener("click", async () => {
  const file = $("#import-file").files[0];
  if (!file) {
    message("Select a CSV file.", true);
    return;
  }
  const b = $("#upload-import");
  b.disabled = true;
  try {
    const result = await api("/api/imports", {
      method: "POST",
      body: JSON.stringify({
        filename: file.name,
        csv_text: await file.text(),
      }),
    });
    await history();
    await show(result.batch_id);
    message("File saved to staging. No transactions have been committed.");
  } catch (e) {
    message(e.message, true);
  } finally {
    b.disabled = false;
  }
});
for (const [id, path] of [
  ["preview-import", "preview"],
  ["commit-import", "canonicalize"],
])
  $("#" + id).addEventListener("click", async () => {
    const batchId = current,
      sequence = viewSequence;
    if (batchId === null || busy.has(batchId)) return;
    busy.add(batchId);
    updateActions();
    try {
      await api("/api/imports/" + batchId + "/" + path, { method: "POST" });
      if (current === batchId && sequence === viewSequence) {
        await show(batchId);
        message(
          path === "preview"
            ? "Preview complete. Review row statuses and duplicate warnings."
            : "Ready rows processed. Review individual row results.",
        );
      }
      window.dispatchEvent(new Event("holdings-changed"));
    } catch (e) {
      if (current === batchId) message(e.message, true);
    } finally {
      busy.delete(batchId);
      updateActions();
    }
  });
$("#reload-imports").addEventListener("click", () =>
  history().catch((e) => message(e.message, true)),
);
try {
  await history();
} catch (e) {
  message(e.message, true);
}
