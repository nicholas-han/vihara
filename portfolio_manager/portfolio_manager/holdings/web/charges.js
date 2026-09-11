import { $, api, cell, message } from "./app.js";
function field(form, text, name, choices = null) {
  const label = document.createElement("label");
  label.textContent = text;
  const input = document.createElement(choices ? "select" : "input");
  input.name = name;
  if (choices)
    for (const [id, label] of choices) input.add(new Option(label, id));
  label.append(input);
  form.append(label);
  return input;
}
function button(parent, text, action) {
  const b = document.createElement("button");
  b.type = "button";
  b.textContent = text;
  b.addEventListener("click", async () => {
    b.disabled = true;
    try {
      await action();
    } catch (e) {
      message(e.message, true);
    } finally {
      b.disabled = false;
    }
  });
  parent.append(b);
  return b;
}
export async function renderRelations(container, id, isCurrent = () => true) {
  const data = await api(`/api/investment-charges/${id}/related-transactions`);
  if (!isCurrent()) return;
  const panel = document.createElement("div"),
    heading = document.createElement("h3");
  heading.textContent = "Related transactions";
  panel.append(heading);
  const p = document.createElement("p");
  p.textContent = data.rows.length
    ? data.rows
        .map(
          (r) =>
            `#${r.transaction_id} · ${r.transaction_type} · ${r.effective_date}${r.reversed_by ? " (reversed)" : ""}`,
        )
        .join("; ")
    : "No related transactions. This charge is complete.";
  panel.append(p);
  const input = field(
    panel,
    "Related Transaction IDs (comma separated; leave empty to remove all)",
    "related",
  );
  input.value = data.rows.map((r) => r.transaction_id).join(", ");
  button(panel, "Save Related Transactions", async () => {
    await api(`/api/investment-charges/${id}/related-transactions`, {
      method: "PUT",
      body: JSON.stringify({
        transaction_ids: input.value
          .split(",")
          .map((s) => s.trim())
          .filter(Boolean),
        expected_version: data.version,
      }),
    });
    panel.remove();
    await renderRelations(container, id, isCurrent);
    message("Related transactions saved.");
  });
  container.append(panel);
}
let settingsSequence = 0;
async function settings() {
  const seq = ++settingsSequence;
  const [categories, mappings, accounts] = await Promise.all([
    api("/api/investment-charge-categories"),
    api("/api/investment-charge-source-mappings"),
    api("/api/accounts"),
  ]);
  if (seq !== settingsSequence) return;
  const box = $("#charge-settings");
  box.replaceChildren();
  const h = document.createElement("h2");
  h.textContent = "Investment Charge Categories and Source Labels";
  box.append(h);
  const categoryOptions = categories.map((c) => [c.id, c.display_name]);
  const names = new Map(
    accounts.map((a) => [a.financial_account_id, a.display_name]),
  );
  const selectCategory = field(box, "Category", "category", categoryOptions);
  const displayName = field(box, "Display Name", "display_name");
  const updateName = () => {
    displayName.value =
      categories.find((c) => c.id === selectCategory.value)?.display_name || "";
  };
  selectCategory.addEventListener("change", updateName);
  updateName();
  const changed = async () => {
    await settings();
    window.dispatchEvent(new Event("charge-references-changed"));
  };
  button(box, "Save Category Name", async () => {
    await api(`/api/investment-charge-categories/${selectCategory.value}`, {
      method: "PATCH",
      body: JSON.stringify({ display_name: displayName.value }),
    });
    await changed();
  });
  const add = document.createElement("details"),
    summary = document.createElement("summary");
  summary.textContent = "Add category";
  add.append(summary);
  const code = field(add, "Code", "code"),
    name = field(add, "Display Name", "name");
  const ledger = field(add, "Expense Account", "ledger", [
    ["INVESTMENT_FEES", "Investment Fees"],
    ["INVESTMENT_TAXES", "Investment Taxes"],
    ["INVESTMENT_FINANCING_INTEREST", "Financing Interest"],
  ]);
  button(add, "Create Category", async () => {
    await api("/api/investment-charge-categories", {
      method: "POST",
      body: JSON.stringify({
        code: code.value,
        display_name: name.value,
        ledger_account_code: ledger.value,
      }),
    });
    await changed();
  });
  box.append(add);
  const mappingForm = document.createElement("div");
  mappingForm.className = "entry-form";
  let editId = null;
  const account = field(
    mappingForm,
    "Financial Account",
    "account",
    accounts.map((a) => [a.financial_account_id, a.display_name]),
  );
  const label = field(
    mappingForm,
    "Statement Source Label",
    "source_label_raw",
  );
  const category = field(mappingForm, "Category", "category", categoryOptions);
  const description = field(
    mappingForm,
    "Description (optional)",
    "description",
  );
  button(mappingForm, "Save Source Mapping", async () => {
    await api(
      "/api/investment-charge-source-mappings" + (editId ? `/${editId}` : ""),
      {
        method: editId ? "PATCH" : "POST",
        body: JSON.stringify({
          financial_account_id: account.value,
          source_label_raw: label.value,
          investment_charge_category_id: category.value,
          description: description.value || null,
        }),
      },
    );
    await changed();
  });
  button(mappingForm, "New Mapping", () => {
    editId = null;
    label.value = "";
    description.value = "";
  });
  box.append(mappingForm);
  const table = document.createElement("table");
  for (const m of mappings) {
    const row = document.createElement("tr");
    cell(row, names.get(m.financial_account_id));
    cell(row, m.source_label_raw);
    cell(
      row,
      categories.find((c) => c.id === m.investment_charge_category_id)
        ?.display_name,
    );
    const actions = cell(row, "");
    button(actions, "Edit", () => {
      editId = m.id;
      account.value = m.financial_account_id;
      label.value = m.source_label_raw;
      category.value = m.investment_charge_category_id;
      description.value = m.description || "";
      label.focus();
    });
    button(actions, "Delete Mapping", async () => {
      await api(`/api/investment-charge-source-mappings/${m.id}`, {
        method: "DELETE",
      });
      await changed();
    });
    table.append(row);
  }
  box.append(table);
}
window.addEventListener("accounts-changed", () =>
  settings().catch((e) => message(e.message, true)),
);
window.addEventListener("source-mapping-changed", () =>
  settings().catch((e) => message(e.message, true)),
);
settings().catch((e) => message(e.message, true));
