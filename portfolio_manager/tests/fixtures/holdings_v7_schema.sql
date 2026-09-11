-- Frozen v7 DDL fixture for explicit reference-only preparation tests.

CREATE TABLE schema_migrations(version INTEGER PRIMARY KEY);
CREATE TABLE holdings_metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL);
INSERT INTO holdings_metadata VALUES ('application', 'vihara.portfolio-holdings');
CREATE TABLE currencies(currency_code TEXT PRIMARY KEY, observable_id TEXT NOT NULL UNIQUE);
CREATE TABLE owners(owner_id INTEGER PRIMARY KEY, owner_code TEXT NOT NULL UNIQUE, display_name TEXT NOT NULL);
CREATE TABLE financial_accounts(financial_account_id INTEGER PRIMARY KEY AUTOINCREMENT,
 account_code TEXT NOT NULL UNIQUE CHECK(length(trim(account_code))>0), display_name TEXT NOT NULL CHECK(length(trim(display_name))>0),
 country_or_region TEXT, institution_type TEXT NOT NULL CHECK(institution_type IN ('BANK','BROKER-DEALER','INSURER')));
CREATE TABLE tax_schemes(tax_scheme_id INTEGER PRIMARY KEY AUTOINCREMENT, scheme_code TEXT NOT NULL UNIQUE CHECK(length(trim(scheme_code))>0), display_name TEXT NOT NULL CHECK(length(trim(display_name))>0), country_or_region TEXT);
CREATE TABLE position_scopes(position_scope_id INTEGER PRIMARY KEY AUTOINCREMENT, financial_account_id INTEGER NOT NULL REFERENCES financial_accounts(financial_account_id), scope_code TEXT NOT NULL CHECK(length(trim(scope_code))>0), display_name TEXT NOT NULL CHECK(length(trim(display_name))>0), tax_scheme_id INTEGER REFERENCES tax_schemes(tax_scheme_id), UNIQUE(financial_account_id,scope_code));
CREATE TABLE external_account_references(external_account_reference_id INTEGER PRIMARY KEY AUTOINCREMENT, financial_account_id INTEGER NOT NULL REFERENCES financial_accounts(financial_account_id), external_account_number TEXT NOT NULL CHECK(typeof(external_account_number)='text' AND length(trim(external_account_number))>0), UNIQUE(financial_account_id,external_account_number));
CREATE TRIGGER scope_identity_immutable BEFORE UPDATE OF position_scope_id,financial_account_id ON position_scopes
BEGIN SELECT RAISE(ABORT,'Position Scope identity and account are immutable'); END;
CREATE TRIGGER tax_identity_immutable BEFORE UPDATE OF tax_scheme_id ON tax_schemes
BEGIN SELECT RAISE(ABORT,'TaxScheme identity is immutable'); END;
CREATE TABLE accounting_config(singleton INTEGER PRIMARY KEY CHECK(singleton=1),
 functional_currency TEXT NOT NULL REFERENCES currencies(currency_code));
CREATE TABLE ledger_account_definitions(ledger_account_code TEXT PRIMARY KEY,
 ledger_account_class TEXT NOT NULL CHECK(ledger_account_class IN ('ASSET','LIABILITY','EQUITY','INCOME','EXPENSE')),
 normal_side TEXT NOT NULL CHECK(normal_side IN ('DEBIT','CREDIT')));
CREATE TABLE transactions(transaction_id INTEGER PRIMARY KEY AUTOINCREMENT,
 transaction_type TEXT NOT NULL CHECK(transaction_type IN ('TRADE','CASH_TRANSFER','FX_CONVERSION','DIVIDEND_RECEIPT','REVERSAL')),
 effective_date TEXT NOT NULL, memo TEXT);
CREATE INDEX ix_transactions_replay ON transactions(effective_date, transaction_id);
CREATE TABLE transaction_relationships(subject_transaction_id INTEGER NOT NULL REFERENCES transactions(transaction_id),
 relationship_type TEXT NOT NULL CHECK(relationship_type='REVERSES'),
 object_transaction_id INTEGER NOT NULL REFERENCES transactions(transaction_id),
 PRIMARY KEY(subject_transaction_id,relationship_type,object_transaction_id),
 CHECK(subject_transaction_id<>object_transaction_id));
CREATE UNIQUE INDEX uq_reversal_subject ON transaction_relationships(subject_transaction_id) WHERE relationship_type='REVERSES';
CREATE UNIQUE INDEX uq_reversal_target ON transaction_relationships(object_transaction_id) WHERE relationship_type='REVERSES';
CREATE TABLE reference_catalog_pins(target_type TEXT NOT NULL, target_id TEXT NOT NULL,
 economics_hash TEXT NOT NULL, PRIMARY KEY(target_type,target_id));
CREATE TABLE book_fx_observations(observation_id INTEGER PRIMARY KEY AUTOINCREMENT,
 base_currency TEXT NOT NULL REFERENCES currencies(currency_code),
 quote_currency TEXT NOT NULL REFERENCES currencies(currency_code),
 effective_date TEXT NOT NULL, revision INTEGER NOT NULL CHECK(revision>0),
 rate TEXT NOT NULL CHECK(typeof(rate)='text' AND length(rate)>0), source TEXT NOT NULL CHECK(length(trim(source))>0),
 UNIQUE(base_currency,quote_currency,effective_date,revision), CHECK(base_currency<>quote_currency));
CREATE TABLE book_fx_evidence(transaction_id INTEGER NOT NULL REFERENCES transactions(transaction_id),
 observation_id INTEGER NOT NULL REFERENCES book_fx_observations(observation_id),
 PRIMARY KEY(transaction_id,observation_id));
CREATE TRIGGER account_identity_immutable BEFORE UPDATE OF financial_account_id ON financial_accounts
BEGIN SELECT RAISE(ABORT,'Account identity is immutable'); END;
CREATE TRIGGER config_locked BEFORE UPDATE ON accounting_config WHEN EXISTS(SELECT 1 FROM transactions)
BEGIN SELECT RAISE(ABORT,'Functional currency is locked'); END;
CREATE TRIGGER config_no_delete BEFORE DELETE ON accounting_config
BEGIN SELECT RAISE(ABORT,'Accounting config cannot be deleted'); END;

CREATE TABLE transaction_accounts(transaction_id INTEGER NOT NULL REFERENCES transactions(transaction_id), account_role TEXT NOT NULL CHECK(account_role IN ('ACCOUNT','SOURCE','DESTINATION')), financial_account_id INTEGER NOT NULL REFERENCES financial_accounts(financial_account_id), PRIMARY KEY(transaction_id,account_role));
CREATE TABLE cash_transfers(transaction_id INTEGER PRIMARY KEY REFERENCES transactions(transaction_id), currency TEXT NOT NULL REFERENCES currencies(currency_code), amount TEXT NOT NULL CHECK(typeof(amount)='text'));
CREATE TABLE positions(position_id INTEGER PRIMARY KEY AUTOINCREMENT, observable_id TEXT NOT NULL UNIQUE);
CREATE TABLE journal_entries(journal_entry_id INTEGER PRIMARY KEY AUTOINCREMENT, source_transaction_id INTEGER NOT NULL UNIQUE REFERENCES transactions(transaction_id));
CREATE TABLE journal_lines(journal_line_id INTEGER PRIMARY KEY AUTOINCREMENT, journal_entry_id INTEGER NOT NULL REFERENCES journal_entries(journal_entry_id), ledger_account_code TEXT NOT NULL REFERENCES ledger_account_definitions(ledger_account_code), side TEXT NOT NULL CHECK(side IN ('DEBIT','CREDIT')), book_amount TEXT NOT NULL CHECK(typeof(book_amount)='text'), financial_account_id INTEGER REFERENCES financial_accounts(financial_account_id), native_currency TEXT REFERENCES currencies(currency_code), native_amount TEXT CHECK(native_amount IS NULL OR typeof(native_amount)='text'), position_id INTEGER REFERENCES positions(position_id), CHECK((ledger_account_code='CASH' AND financial_account_id IS NOT NULL AND native_currency IS NOT NULL AND native_amount IS NOT NULL AND position_id IS NULL) OR (ledger_account_code='INVESTMENT' AND position_id IS NOT NULL AND financial_account_id IS NULL AND native_currency IS NULL AND native_amount IS NULL) OR (ledger_account_code NOT IN ('CASH','INVESTMENT') AND financial_account_id IS NULL AND native_currency IS NULL AND native_amount IS NULL AND position_id IS NULL)));
CREATE INDEX ix_journal_cash ON journal_lines(financial_account_id,native_currency);
CREATE TABLE command_receipts(request_key TEXT PRIMARY KEY, payload_hash TEXT NOT NULL, transaction_id INTEGER NOT NULL UNIQUE REFERENCES transactions(transaction_id));

CREATE TABLE trades(transaction_id INTEGER PRIMARY KEY REFERENCES transactions(transaction_id), product_id TEXT NOT NULL, listing_id TEXT, position_scope_id INTEGER NOT NULL REFERENCES position_scopes(position_scope_id), side TEXT NOT NULL CHECK(side IN ('BUY','SELL')), quantity TEXT NOT NULL CHECK(typeof(quantity)='text'), price TEXT NOT NULL CHECK(typeof(price)='text'), trade_date TEXT NOT NULL, trade_time TEXT, scheduled_settlement_date TEXT);
CREATE TABLE trade_fees(trade_transaction_id INTEGER NOT NULL REFERENCES trades(transaction_id), fee_type TEXT NOT NULL CHECK(fee_type IN ('COMMISSION','EXCHANGE_FEE','REGULATORY_FEE','OTHER')), amount TEXT NOT NULL CHECK(typeof(amount)='text'), PRIMARY KEY(trade_transaction_id,fee_type));
CREATE TABLE position_entries(position_entry_id INTEGER PRIMARY KEY AUTOINCREMENT, source_transaction_id INTEGER NOT NULL UNIQUE REFERENCES transactions(transaction_id));
CREATE TABLE position_lines(position_line_id INTEGER PRIMARY KEY AUTOINCREMENT, position_entry_id INTEGER NOT NULL REFERENCES position_entries(position_entry_id), position_id INTEGER NOT NULL REFERENCES positions(position_id), line_type TEXT NOT NULL CHECK(line_type IN ('OWNERSHIP','LOCATION')), quantity_delta TEXT NOT NULL CHECK(typeof(quantity_delta)='text'), owner_id INTEGER REFERENCES owners(owner_id), position_scope_id INTEGER REFERENCES position_scopes(position_scope_id), CHECK((line_type='OWNERSHIP' AND owner_id IS NOT NULL AND position_scope_id IS NULL) OR (line_type='LOCATION' AND position_scope_id IS NOT NULL AND owner_id IS NULL)));
CREATE TABLE position_cost_basis_lots(cost_basis_lot_id INTEGER PRIMARY KEY AUTOINCREMENT, source_transaction_id INTEGER NOT NULL UNIQUE REFERENCES transactions(transaction_id), position_id INTEGER NOT NULL REFERENCES positions(position_id), owner_id INTEGER NOT NULL REFERENCES owners(owner_id), position_scope_id INTEGER NOT NULL REFERENCES position_scopes(position_scope_id), quantity_acquired TEXT NOT NULL CHECK(typeof(quantity_acquired)='text'), book_cost_basis TEXT NOT NULL CHECK(typeof(book_cost_basis)='text'));
CREATE TABLE position_cost_basis_allocations(investment_journal_line_id INTEGER NOT NULL REFERENCES journal_lines(journal_line_id), source_cost_basis_lot_id INTEGER NOT NULL REFERENCES position_cost_basis_lots(cost_basis_lot_id), quantity_disposed TEXT NOT NULL CHECK(typeof(quantity_disposed)='text'), book_cost_disposed TEXT NOT NULL CHECK(typeof(book_cost_disposed)='text'), PRIMARY KEY(investment_journal_line_id,source_cost_basis_lot_id));
CREATE INDEX ix_position_bucket ON position_lines(position_id,position_scope_id);
CREATE INDEX ix_lot_bucket ON position_cost_basis_lots(position_id,owner_id,position_scope_id);
CREATE INDEX ix_trade_scope ON trades(position_scope_id,transaction_id);

CREATE TABLE fx_conversions(transaction_id INTEGER PRIMARY KEY REFERENCES transactions(transaction_id), sell_currency TEXT NOT NULL REFERENCES currencies(currency_code), sell_amount TEXT NOT NULL CHECK(typeof(sell_amount)='text'), buy_currency TEXT NOT NULL REFERENCES currencies(currency_code), buy_amount TEXT NOT NULL CHECK(typeof(buy_amount)='text'), CHECK(sell_currency<>buy_currency));
CREATE TABLE dividend_receipts(transaction_id INTEGER PRIMARY KEY REFERENCES transactions(transaction_id), observable_id TEXT NOT NULL, currency TEXT NOT NULL REFERENCES currencies(currency_code), amount TEXT NOT NULL CHECK(typeof(amount)='text'));

CREATE TABLE market_prices(observation_id INTEGER PRIMARY KEY AUTOINCREMENT, observable_id TEXT NOT NULL, price TEXT NOT NULL CHECK(typeof(price)='text'), currency TEXT NOT NULL REFERENCES currencies(currency_code), as_of TEXT NOT NULL, source TEXT NOT NULL);
CREATE INDEX ix_market_price_date ON market_prices(observable_id,as_of);
CREATE TABLE market_fx(observation_id INTEGER PRIMARY KEY AUTOINCREMENT, base_currency TEXT NOT NULL REFERENCES currencies(currency_code), quote_currency TEXT NOT NULL REFERENCES currencies(currency_code), rate TEXT NOT NULL CHECK(typeof(rate)='text'), as_of TEXT NOT NULL, source TEXT NOT NULL, CHECK(base_currency<>quote_currency));
CREATE INDEX ix_market_fx_date ON market_fx(base_currency,quote_currency,as_of);

CREATE TABLE import_batches(batch_id INTEGER PRIMARY KEY AUTOINCREMENT, filename TEXT NOT NULL, file_hash TEXT NOT NULL UNIQUE);
CREATE TABLE import_rows(row_id INTEGER PRIMARY KEY AUTOINCREMENT, batch_id INTEGER NOT NULL REFERENCES import_batches(batch_id), row_number INTEGER NOT NULL, raw_json TEXT NOT NULL, override_json TEXT NOT NULL DEFAULT '{}', status TEXT NOT NULL DEFAULT 'STAGED' CHECK(status IN ('STAGED','READY','ERROR','COMMITTED','DUPLICATE')), payload_json TEXT, error_json TEXT, UNIQUE(batch_id,row_number));
CREATE TABLE import_links(row_id INTEGER PRIMARY KEY REFERENCES import_rows(row_id), transaction_id INTEGER NOT NULL REFERENCES transactions(transaction_id), dedup_key TEXT NOT NULL, payload_hash TEXT NOT NULL);
CREATE INDEX ix_import_dedup ON import_links(dedup_key);
CREATE TRIGGER import_link_no_update BEFORE UPDATE ON import_links BEGIN SELECT RAISE(ABORT,'Import links are immutable'); END;
CREATE TRIGGER import_link_no_delete BEFORE DELETE ON import_links BEGIN SELECT RAISE(ABORT,'Import links are immutable'); END;
CREATE TRIGGER import_committed_no_update BEFORE UPDATE ON import_rows WHEN EXISTS(SELECT 1 FROM import_links WHERE row_id=OLD.row_id) BEGIN SELECT RAISE(ABORT,'Committed import rows are immutable'); END;

INSERT INTO schema_migrations VALUES (7);
