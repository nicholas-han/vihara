const accountSummary = document.querySelector("#account-summary");
const allAccountsInput = document.querySelector("#all-accounts");
const excludeAccountsInput = document.querySelector("#exclude-accounts");
const accountOptions = document.querySelector("#account-options");
const costMethodSelect = document.querySelector("#cost-method");
const importFileInput = document.querySelector("#import-file");
const importStatus = document.querySelector("#import-status");
const reconcileBanner = document.querySelector("#reconcile-banner");
const body = document.querySelector("#holdings-body");
const subtitle = document.querySelector("#panel-subtitle");
const metricHoldings = document.querySelector("#metric-holdings");
const metricCost = document.querySelector("#metric-cost");
const metricRealized = document.querySelector("#metric-realized");
const metricDividends = document.querySelector("#metric-dividends");

const COLUMNS = 11;

let accountCache = [];

async function loadAccounts() {
  const response = await fetch("/api/accounts");
  accountCache = await response.json();
  accountOptions.innerHTML = "";
  for (const account of accountCache) {
    const label = document.createElement("label");
    label.className = "account-option";
    label.innerHTML = `
      <input type="checkbox" value="${escapeHtml(account.account_id)}" />
      <span>${escapeHtml(account.name)} <small>${escapeHtml(account.account_id)}</small></span>
    `;
    accountOptions.appendChild(label);
  }
  if (accountCache.length === 0) {
    body.innerHTML = `<tr><td colspan="${COLUMNS}" class="empty">No accounts found</td></tr>`;
    return;
  }
  updateAccountSummary();
  await refresh();
}

function accountParams() {
  const params = new URLSearchParams({
    exclude_accounts: String(excludeAccountsInput.checked),
  });
  if (!allAccountsInput.checked) {
    for (const accountId of selectedAccounts()) {
      params.append("account_ids", accountId);
    }
  }
  return params;
}

async function refresh() {
  await Promise.all([loadHoldings(), loadReconciliation(), loadSummary()]);
}

async function loadSummary() {
  const params = accountParams();
  params.set("cost_method", costMethodSelect.value);
  params.set("base_currency", "USD");
  const response = await fetch(`/api/summary?${params}`);
  const summary = await response.json();
  metricCost.textContent = formatNumber(summary.total_cost_base);
  metricRealized.textContent = formatNumber(summary.realized_pnl_base);
  metricRealized.className = pnlClass(summary.realized_pnl_base);
  metricDividends.textContent = formatNumber(summary.dividends_received_base);
  const unconverted = summary.unconverted_currencies || [];
  if (unconverted.length > 0) {
    metricCost.textContent += ` (未折算: ${unconverted.join(", ")})`;
  }
}

async function loadHoldings() {
  const selected = selectedAccounts();
  const params = accountParams();
  params.set("cost_method", costMethodSelect.value);
  body.innerHTML = `<tr><td colspan="${COLUMNS}" class="empty">Loading...</td></tr>`;
  const response = await fetch(`/api/holdings?${params}`);
  const payload = await response.json();
  subtitle.textContent = describeSelection(selected);
  renderRows(payload.rows || []);
}

async function loadReconciliation() {
  const response = await fetch(`/api/reconciliation?${accountParams()}`);
  const payload = await response.json();
  const issues = payload.issues || [];
  if (issues.length === 0) {
    reconcileBanner.hidden = true;
    return;
  }
  const detail = issues
    .map(
      (issue) =>
        `${issue.account_id}/${issue.instrument_id} @ ${issue.as_of}: ` +
        `对账单 ${formatNumber(issue.snapshot_quantity)} vs 交易推算 ${formatNumber(issue.computed_quantity)}`
    )
    .join("; ");
  reconcileBanner.textContent = `对账不一致（可能漏了交易或未录入公司行动）: ${detail}`;
  reconcileBanner.hidden = false;
}

async function importTrades(file) {
  importStatus.hidden = false;
  importStatus.textContent = `正在导入 ${file.name}...`;
  try {
    const response = await fetch("/api/imports", {
      method: "POST",
      headers: { "content-type": "text/csv", "x-filename": file.name },
      body: await file.text(),
    });
    const payload = await response.json();
    if (!response.ok) {
      importStatus.textContent = `导入失败: ${payload.detail || response.status}`;
      return;
    }
    importStatus.textContent =
      `导入完成（batch ${payload.batch_id}）: ${payload.row_count} 行, ` +
      `新增 ${payload.inserted}, 跳过 ${payload.skipped}`;
    await refresh();
  } catch (error) {
    importStatus.textContent = `导入失败: ${error.message}`;
  } finally {
    importFileInput.value = "";
  }
}

function renderRows(rows) {
  updateMetrics(rows);
  if (rows.length === 0) {
    body.innerHTML = `<tr><td colspan="${COLUMNS}" class="empty">No holdings</td></tr>`;
    return;
  }

  body.innerHTML = rows
    .map(
      (row) => `
        <tr>
          <td><span class="account-chip">${escapeHtml(row.account_id)}</span></td>
          <td><span class="market-badge">${escapeHtml(row.market)}</span></td>
          <td class="symbol">${escapeHtml(row.symbol)}</td>
          <td>${escapeHtml(row.name)}</td>
          <td class="number">${formatNumber(row.quantity)}</td>
          <td class="number">${formatMoney(row.average_cost, row.currency)}</td>
          <td class="number ${pnlClass(row.realized_pnl)}">${formatMoney(row.realized_pnl, row.currency)}</td>
          <td class="number">${formatMoney(row.dividends_received, row.currency)}</td>
          <td class="number">${formatNullable(row.dividend_per_share, row.dividend_fiscal_year)}</td>
          <td class="number">${formatNullable(row.eps, row.eps_fiscal_year)}</td>
          <td><span class="source-tag">${escapeHtml(row.position_source)}</span> ${escapeHtml(row.cost_method)}</td>
        </tr>
      `
    )
    .join("");
}

function selectedAccounts() {
  return [...accountOptions.querySelectorAll("input:checked")].map((input) => input.value);
}

function updateAccountSummary() {
  const selected = selectedAccounts();
  const mode = excludeAccountsInput.checked ? "排除" : "包含";
  if (allAccountsInput.checked || selected.length === 0) {
    accountSummary.textContent = "全部账户";
    return;
  }
  accountSummary.textContent = `${mode} ${selected.length} 个账户`;
}

function describeSelection(selected) {
  if (allAccountsInput.checked || selected.length === 0) {
    return "Showing all accounts";
  }
  const mode = excludeAccountsInput.checked ? "Excluding" : "Showing";
  return `${mode} ${selected.join(", ")}`;
}

function updateMetrics(rows) {
  metricHoldings.textContent = String(rows.length);
}

function pnlClass(value) {
  const numeric = Number(value || 0);
  if (numeric > 0) return "gain";
  if (numeric < 0) return "loss";
  return "";
}

function formatNumber(value) {
  return Number(value).toLocaleString(undefined, { maximumFractionDigits: 6 });
}

function formatMoney(value, currency) {
  const formatted = Number(value).toLocaleString(undefined, { maximumFractionDigits: 4 });
  return `${formatted} ${escapeHtml(currency || "")}`;
}

function formatNullable(value, fiscalYear) {
  if (value === null || value === undefined) return "-";
  return `${formatNumber(value)} (${fiscalYear})`;
}

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (char) => {
    const entities = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };
    return entities[char];
  });
}

allAccountsInput.addEventListener("change", () => {
  if (allAccountsInput.checked) {
    for (const input of accountOptions.querySelectorAll("input")) {
      input.checked = false;
    }
  }
  updateAccountSummary();
  refresh();
});
accountOptions.addEventListener("change", () => {
  allAccountsInput.checked = selectedAccounts().length === 0;
  updateAccountSummary();
  refresh();
});
excludeAccountsInput.addEventListener("change", () => {
  updateAccountSummary();
  refresh();
});
costMethodSelect.addEventListener("change", refresh);
importFileInput.addEventListener("change", () => {
  const file = importFileInput.files && importFileInput.files[0];
  if (file) importTrades(file);
});

loadAccounts().catch((error) => {
  body.innerHTML = `<tr><td colspan="${COLUMNS}" class="empty">${escapeHtml(error.message)}</td></tr>`;
});
