CREATE TABLE schema_migrations(version INTEGER PRIMARY KEY);
CREATE TABLE holdings_metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL);
INSERT INTO holdings_metadata VALUES ('application', 'vihara.portfolio-holdings');
CREATE TABLE currencies(currency_code TEXT PRIMARY KEY, observable_id TEXT NOT NULL UNIQUE);
CREATE TABLE owners(owner_id INTEGER PRIMARY KEY, owner_code TEXT NOT NULL UNIQUE, display_name TEXT NOT NULL);
CREATE TABLE financial_accounts(financial_account_id INTEGER PRIMARY KEY AUTOINCREMENT,
 account_code TEXT NOT NULL UNIQUE, display_name TEXT NOT NULL CHECK(length(trim(display_name))>0));
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
CREATE TRIGGER account_identity_immutable BEFORE UPDATE OF financial_account_id,account_code ON financial_accounts
BEGIN SELECT RAISE(ABORT,'Account identity is immutable'); END;
CREATE TRIGGER config_locked BEFORE UPDATE ON accounting_config WHEN EXISTS(SELECT 1 FROM transactions)
BEGIN SELECT RAISE(ABORT,'Functional currency is locked'); END;
CREATE TRIGGER config_no_delete BEFORE DELETE ON accounting_config
BEGIN SELECT RAISE(ABORT,'Accounting config cannot be deleted'); END;
