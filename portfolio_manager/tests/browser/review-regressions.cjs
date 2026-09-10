// Runs real UI modules against intercepted APIs; never opens a financial database.
const { test, before, after } = require("node:test");
const assert = require("node:assert/strict");
const { chromium } = require("playwright");
const http = require("node:http");
const fs = require("node:fs");
const path = require("node:path");
let browser, server, base;
const web = path.resolve(__dirname, "../../portfolio_manager/holdings/web");
const account = {
  financial_account_id: "1",
  account_code: "BROKER",
  display_name: "Broker Account",
};
const destination = {
  financial_account_id: "2",
  account_code: "BANK",
  display_name: "Bank Account",
};
const product = {
  product_id: "p",
  name: "AAPL / USD",
  code: "AAPL",
  asset_class: "EQUITY",
  currency: "USD",
  asset_observable_id: "o",
  quote_observable_id: "usd",
  observable: { observable_id: "o", name: "Apple Inc.", code: "AAPL" },
  quote_observable: { code: "USD" },
  holding_leg: { leg_id: "leg-aapl", kind: "HOLDING" },
  listings: [{ listing_id: "l", venue_id: "v", venue_segment: "STOCK" }],
  identifiers: [
    {
      target_type: "LISTING",
      target_id: "l",
      authority: "NASDAQ",
      identifier: "AAPL",
    },
  ],
};
function batch(id) {
  return {
    batch_id: id,
    filename: id + ".csv",
    rows: [
      {
        row_id: id,
        batch_id: id,
        row_number: 1,
        status: "READY",
        raw: {
          transaction_type: "CASH_TRANSFER",
          effective_date: "2026-09-01",
        },
        override: {},
        payload: { input: { amount: "100", currency: "HKD" } },
        transaction_id: null,
      },
    ],
  };
}
function deferred() {
  let resolve;
  const promise = new Promise((r) => (resolve = r));
  return { promise, resolve };
}
before(async () => {
  server = http.createServer((req, res) => {
    const name = req.url === "/" ? "index.html" : path.basename(req.url);
    if (!/\.(html|js|css)$/.test(name)) {
      res.writeHead(404);
      res.end();
      return;
    }
    res.setHeader(
      "Content-Type",
      name.endsWith(".js")
        ? "text/javascript"
        : name.endsWith(".css")
          ? "text/css"
          : "text/html",
    );
    res.end(fs.readFileSync(path.join(web, name)));
  });
  await new Promise((r) => server.listen(0, "127.0.0.1", r));
  base = "http://127.0.0.1:" + server.address().port;
  browser = await chromium.launch({
    headless: true,
    ...(process.env.CHROME_PATH
      ? { executablePath: process.env.CHROME_PATH }
      : {}),
  });
});
after(async () => {
  await browser?.close();
  await new Promise((r) => server?.close(r));
});
async function pageFixture(t, override = () => undefined) {
  const page = await browser.newPage();
  page.setDefaultTimeout(5000);
  const errors = [];
  page.on("pageerror", (e) => errors.push(e.message));
  t.after(async () => {
    await page.close();
    assert.deepEqual(errors, []);
  });
  await page.route("**/api/**", async (route) => {
    const url = new URL(route.request().url());
    let body = await override(url.pathname, route.request());
    if (body === undefined) {
      switch (url.pathname) {
        case "/api/accounts":
          body = [account, destination];
          break;
        case "/api/accounts/1/position-scopes":
          body = [{position_scope_id: "10",financial_account_id: "1",scope_code: "DEFAULT",display_name: "Default",tax_scheme_id: null}];
          break;
        case "/api/accounts/2/position-scopes":
        case "/api/accounts/1/external-account-references":
        case "/api/accounts/2/external-account-references":
          body = [];
          break;
        case "/api/configuration":
          body = {
            functional_currency: "HKD",
            currencies: [{ currency_code: "HKD" }, { currency_code: "USD" }],
          };
          break;
        case "/api/instruments/search":
          body = { rows: [product] };
          break;
        case "/api/instruments/p":
          body = product;
          break;
        case "/api/observables":
          body = { rows: [product.observable] };
          break;
        case "/api/holdings":
          body = {
            cash: [],
            investments: [],
            transaction_count: 1,
            valuation: {
              complete: true,
              valued_subtotal: "0",
              unvalued_count: 0,
              investment_unrealized_complete: true,
              investment_unrealized_subtotal: "0",
            },
          };
          break;
        case "/api/transactions":
          body = { total: 0, rows: [] };
          break;
        case "/api/imports":
          body = {
            rows: [
              { batch_id: "101", filename: "101.csv" },
              { batch_id: "102", filename: "102.csv" },
            ],
          };
          break;
        default:
          body = batch(url.pathname.split("/")[3]);
      }
    }
    await route.fulfill({ json: body });
  });
  await page.goto(base);
  await page.waitForFunction(
    () =>
      document.querySelector("#trade-form [name=quote_currency]").value ===
      "USD",
  );
  return page;
}
test("late batch response cannot change the visible batch or commit target", async (t) => {
  const held = deferred(),
    entered = deferred();
  let committed;
  const p = await pageFixture(t, async (url, req) => {
    if (url === "/api/imports/101") {
      entered.resolve();
      await held.promise;
      return batch("101");
    }
    if (req.method() === "POST") {
      committed = url;
      return batch("102");
    }
  });
  await p.locator("[data-page=imports]").click();
  await p.getByRole("button", { name: "#101 101.csv", exact: true }).click();
  await entered.promise;
  assert(await p.locator("#commit-import").isDisabled());
  await p.getByRole("button", { name: "#102 102.csv", exact: true }).click();
  await p.locator("#import-title").filter({ hasText: "102.csv" }).waitFor();
  const response = p.waitForResponse((r) =>
    r.url().endsWith("/api/imports/101"),
  );
  held.resolve();
  await response;
  await p.waitForTimeout(50);
  assert((await p.locator("#import-title").innerText()).includes("102.csv"));
  const committedResponse = p.waitForResponse((r) =>
    r.url().endsWith("/canonicalize"),
  );
  await p.locator("#commit-import").click();
  await committedResponse;
  assert.equal(committed, "/api/imports/102/canonicalize");
});
test("completion of an old commit does not replace a newly selected batch", async (t) => {
  const held = deferred(),
    entered = deferred();
  let committed;
  const p = await pageFixture(t, async (url, req) => {
    if (req.method() === "POST") {
      committed = url;
      entered.resolve();
      await held.promise;
      return batch("101");
    }
  });
  await p.locator("[data-page=imports]").click();
  await p.getByRole("button", { name: "#101 101.csv", exact: true }).click();
  await p.locator("#import-title").filter({ hasText: "101.csv" }).waitFor();
  await p.locator("#commit-import").click();
  await entered.promise;
  await p.getByRole("button", { name: "#102 102.csv", exact: true }).click();
  await p.locator("#import-title").filter({ hasText: "102.csv" }).waitFor();
  const response = p.waitForResponse((r) => r.url().endsWith("/canonicalize"));
  held.resolve();
  await response;
  await p.waitForTimeout(50);
  assert.equal(committed, "/api/imports/101/canonicalize");
  assert((await p.locator("#import-title").innerText()).includes("102.csv"));
  assert(await p.locator("#commit-import").isEnabled());
});
for (const kind of ["TRADE", "CASH_TRANSFER", "DIVIDEND_RECEIPT", "REVERSAL"])
  test("transaction identity is readable for " + kind, async (t) => {
    const trade = {
      transaction_id: "7",
      transaction_type: "TRADE",
      effective_date: "2026-09-01",
      accounts: { ACCOUNT: "1" },
      observable_id: "o",
      data: {
        product_id: "p",
        listing_id: "l",
        side: "BUY",
        quantity: "1",
        price: "10",
      },
      journal: [],
      position_lines: [],
      lots: [],
      allocations: [],
    };
    const tx = { ...trade, transaction_type: kind };
    if (kind === "CASH_TRANSFER") {
      tx.accounts = { SOURCE: "1", DESTINATION: "2" };
      tx.data = { currency: "HKD", amount: "100" };
    }
    if (kind === "DIVIDEND_RECEIPT")
      tx.data = { observable_id: "o", currency: "USD", amount: "10" };
    if (kind === "REVERSAL") {
      tx.accounts = {};
      tx.data = { target_transaction_id: "8" };
    }
    const p = await pageFixture(t, (url) =>
      url === "/api/transactions"
        ? { total: 1, rows: [tx] }
        : url === "/api/transactions/7"
          ? tx
          : url === "/api/transactions/8"
            ? trade
            : undefined,
    );
    await p.locator("[data-page=transactions]").click();
    await p.locator("#transaction-rows button").click();
    await p
      .locator("#transaction-detail")
      .getByText("Broker Account (BROKER)", { exact: true })
      .waitFor();
    const text = await p.locator("#transaction-detail").innerText();
    if (kind === "CASH_TRANSFER") {
      assert(text.includes("Source Account"));
      assert(text.includes("Destination Account"));
      assert(text.includes("Bank Account (BANK)"));
    } else if (kind === "DIVIDEND_RECEIPT") {
      assert(text.includes("Dividend Observable"));
      assert(text.includes("Apple Inc. (AAPL)"));
    } else {
      assert(text.includes("AAPL / USD"));
      assert(text.includes("NASDAQ · STOCK · AAPL"));
    }
  });

test("transaction filters send currency, observable, status and end date", async (t) => {
  let query;
  const p = await pageFixture(t, (url, req) => {
    if (url === "/api/transactions") query = new URL(req.url()).searchParams;
  });
  await p.click('[data-page="transactions"]');
  await p.selectOption("#tx-currency", "USD");
  await p.selectOption("#tx-observable", "o");
  await p.selectOption("#tx-status", "REVERSED");
  const filtered = p.waitForResponse((r) =>
    r.url().includes("date_to=2026-09-02"),
  );
  await p.fill("#tx-to", "2026-09-02");
  await p.locator("#tx-to").dispatchEvent("change");
  await filtered;
  assert.equal(query.get("currency"), "USD");
  assert.equal(query.get("observable_id"), "o");
  assert.equal(query.get("status"), "REVERSED");
  assert.equal(query.get("date_to"), "2026-09-02");
  assert.equal(query.get("offset"), "0");
});

test("instrument detail shows HoldingLeg and external identity", async (t) => {
  const p = await pageFixture(t);
  await p.click('[data-page="settings"]');
  await p.locator("#instruments button").click();
  await p.waitForFunction(() =>
    document
      .querySelector("#instrument-detail")
      .textContent.includes("leg-aapl"),
  );
  const detail = await p.locator("#instrument-detail").innerText();
  assert.match(detail, /HoldingLeg/);
  assert.match(detail, /ExternalIdentifiers/);
  assert.match(detail, /NASDAQ/);
  assert.match(detail, /LISTING l/);
});

test("valuation renders actual zero price and distinguishes missing market FX", async (t) => {
  const p = await pageFixture(t, (url) => {
    if (url !== "/api/holdings") return;
    return {
      transaction_count: 1,
      cash: [
        {
          financial_account_id: "1",
          account_name: "Broker Account",
          currency: "USD",
          quantity: "10",
          book_value: "78",
          valuation_currency: "USD",
          market_value: null,
          market_fx_rate: null,
          valuation_status: "MISSING_FX",
        },
      ],
      investments: [
        {
          financial_account_id: "1",
          account_name: "Broker Account",
          name: "Apple Inc.",
          code: "AAPL",
          position_id: "1",
          quantity: "2",
          book_value: "160",
          average_historical_cost: "80",
          valuation_currency: "USD",
          market_price: "0",
          native_market_value: "0",
          market_value: "0",
          unrealized_difference: "-160",
          valuation_status: "AVAILABLE",
          price_as_of: "2026-09-02",
          fx_as_of: "2026-09-02",
        },
      ],
      valuation: {
        complete: false,
        valued_subtotal: "0",
        unvalued_count: 1,
        investment_unrealized_complete: true,
        investment_unrealized_subtotal: "-160",
      },
    };
  });
  const investment = await p.locator("#investment-rows td").allTextContents();
  assert.deepEqual(investment.slice(2, 10), [
    "2",
    "160",
    "80",
    "0",
    "USD",
    "0",
    "0",
    "-160",
  ]);
  const cash = await p.locator("#cash-rows td").allTextContents();
  assert.equal(cash[4], "Unavailable");
  assert.equal(cash[5], "Incomplete Valuation");
  assert.match(cash[6], /Missing USD Market FX/);
});

test("DEFAULT scope is hidden but submitted, and cash-only accounts disable trades", async (t) => {
  const p = await pageFixture(t);
  const scope = p.locator('#trade-form [name=position_scope_id]');
  await p.waitForFunction(() => document.querySelector('#trade-form [name=position_scope_id]').value === '10');
  assert.equal(await scope.inputValue(), '10');
  assert(await p.locator('#trade-scope-label').evaluate(el => el.hidden));
  const data = await p.locator('#trade-form').evaluate(form => Object.fromEntries(new FormData(form)));
  assert.equal(data.position_scope_id, '10');
  await p.locator('#trade-form [name=account_id]').selectOption('2', {force:true});
  await p.waitForFunction(() => document.querySelector('#trade-scope-description').textContent.includes('no position holdings'));
  assert(await p.locator('#trade-form button[type=submit]').isDisabled());
  assert.equal(await scope.inputValue(), '');
});

test("multiple scopes require an explicit selection and expose the selected tax scheme", async (t) => {
  const p = await pageFixture(t, url => url === '/api/accounts/1/position-scopes' ? [
    {position_scope_id:'11',financial_account_id:'1',scope_code:'NISA',display_name:'NISA',tax_scheme_name:'Japan NISA'},
    {position_scope_id:'12',financial_account_id:'1',scope_code:'TOKUTEI',display_name:'Specified',tax_scheme_name:'Japan Specified'}
  ] : undefined);
  await p.waitForFunction(() => document.querySelector('#trade-form [name=position_scope_id]').options.length === 3);
  const scope = p.locator('#trade-form [name=position_scope_id]');
  assert.equal(await scope.inputValue(), '');
  assert.equal(await p.locator('#trade-scope-label').evaluate(el => el.hidden), false);
  assert.equal(await scope.evaluate(el => el.validity.valueMissing), true);
  await scope.selectOption('12', {force:true});
  assert((await p.locator('#trade-scope-description').textContent()).includes('Japan Specified'));
  const data = await p.locator('#trade-form').evaluate(form => Object.fromEntries(new FormData(form)));
  assert.equal(data.position_scope_id, '12');
});

test("late scope response cannot restore a previous account selection", async (t) => {
  const held = deferred(), entered = deferred();
  const p = await pageFixture(t, async url => {
    if(url === '/api/accounts/2/position-scopes') {
      entered.resolve(); await held.promise;
      return [{position_scope_id:'20',financial_account_id:'2',scope_code:'DEFAULT',display_name:'Bank holdings'}];
    }
  });
  await p.waitForFunction(() => document.querySelector('#trade-form [name=position_scope_id]').value === '10');
  await p.locator('#trade-form [name=account_id]').selectOption('2', {force:true});
  await entered.promise;
  assert(await p.locator('#trade-form button[type=submit]').isDisabled());
  await p.locator('#trade-form [name=account_id]').selectOption('1', {force:true});
  await p.waitForFunction(() => document.querySelector('#trade-form [name=position_scope_id]').value === '10');
  const response = p.waitForResponse(r => r.url().endsWith('/accounts/2/position-scopes'));
  held.resolve(); await response;
  await p.waitForTimeout(50);
  assert.equal(await p.locator('#trade-form [name=position_scope_id]').inputValue(), '10');
  assert.equal(await p.locator('#trade-form [name=account_id]').inputValue(), '1');
});

test("lowercase imported trade still offers scope mapping", async (t) => {
  let mapping;
  const scopedBatch = batch('101');
  scopedBatch.rows[0].status = 'ERROR';
  scopedBatch.rows[0].raw = {transaction_type:' trade ', effective_date:'2026-09-02',account_code:'BROKER'};
  const p = await pageFixture(t, (url, req) => {
    if(url === '/api/accounts/1/position-scopes') return [
      {position_scope_id:'11',financial_account_id:'1',scope_code:'NISA',display_name:'NISA'},
      {position_scope_id:'12',financial_account_id:'1',scope_code:'TOKUTEI',display_name:'Specified'}];
    if(url === '/api/import-rows/101') {mapping = req.postDataJSON().mapping; return scopedBatch.rows[0];}
    if(url === '/api/imports/101' || url === '/api/imports/101/preview') return scopedBatch;
  });
  await p.locator('[data-page=imports]').click();
  await p.getByRole('button', {name:'#101 101.csv',exact:true}).click();
  await p.getByRole('button', {name:'Adjust Mapping',exact:true}).click();
  await p.locator('#import-result [name=position_scope_code]').selectOption('NISA');
  await p.getByRole('button', {name:'Save Mapping and Preview',exact:true}).click();
  await p.waitForResponse(r => r.url().endsWith('/imports/101/preview'));
  assert.equal(mapping.position_scope_code, 'NISA');
});
