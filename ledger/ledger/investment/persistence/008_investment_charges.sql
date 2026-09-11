CREATE TABLE investment_charge_categories(id INTEGER PRIMARY KEY AUTOINCREMENT,
 code TEXT NOT NULL UNIQUE CHECK(length(trim(code))>0), display_name TEXT NOT NULL CHECK(length(trim(display_name))>0),
 ledger_account_code TEXT NOT NULL REFERENCES ledger_account_definitions(ledger_account_code)
 CHECK(ledger_account_code IN ('INVESTMENT_FEES','INVESTMENT_TAXES','INVESTMENT_FINANCING_INTEREST')));
CREATE TABLE investment_charges(transaction_id INTEGER PRIMARY KEY REFERENCES transactions(transaction_id),
 investment_charge_category_id INTEGER NOT NULL REFERENCES investment_charge_categories(id),
 currency TEXT NOT NULL REFERENCES currencies(currency_code), amount TEXT NOT NULL CHECK(typeof(amount)='text' AND amount NOT IN ('0','-0')));
CREATE TABLE investment_charge_source_mappings(id INTEGER PRIMARY KEY AUTOINCREMENT,
 financial_account_id INTEGER NOT NULL REFERENCES financial_accounts(financial_account_id),
 source_label_raw TEXT NOT NULL CHECK(length(trim(source_label_raw))>0), source_label_normalized TEXT NOT NULL CHECK(length(trim(source_label_normalized))>0),
 investment_charge_category_id INTEGER NOT NULL REFERENCES investment_charge_categories(id), description TEXT,
 UNIQUE(financial_account_id,source_label_normalized));
CREATE TRIGGER charge_no_update BEFORE UPDATE ON investment_charges BEGIN SELECT RAISE(ABORT,'Canonical records are immutable'); END;
CREATE TRIGGER charge_no_delete BEFORE DELETE ON investment_charges BEGIN SELECT RAISE(ABORT,'Canonical records are immutable'); END;
CREATE TRIGGER charge_subtype BEFORE INSERT ON investment_charges WHEN (SELECT transaction_type FROM transactions WHERE transaction_id=NEW.transaction_id)<>'INVESTMENT_CHARGE'
BEGIN SELECT RAISE(ABORT,'Invalid charge subtype'); END;
CREATE TRIGGER category_meaning_locked BEFORE UPDATE OF id,code,ledger_account_code ON investment_charge_categories
WHEN EXISTS(SELECT 1 FROM investment_charges WHERE investment_charge_category_id=OLD.id)
BEGIN SELECT RAISE(ABORT,'Used category meaning is immutable'); END;
CREATE TRIGGER reverses_no_update BEFORE UPDATE ON transaction_relationships WHEN OLD.relationship_type='REVERSES' OR NEW.relationship_type='REVERSES'
BEGIN SELECT RAISE(ABORT,'REVERSES is immutable'); END;
CREATE TRIGGER reverses_no_delete BEFORE DELETE ON transaction_relationships WHEN OLD.relationship_type='REVERSES'
BEGIN SELECT RAISE(ABORT,'REVERSES is immutable'); END;
CREATE TRIGGER relationship_endpoints_insert BEFORE INSERT ON transaction_relationships
WHEN (NEW.relationship_type='CHARGE_FOR' AND ((SELECT transaction_type FROM transactions WHERE transaction_id=NEW.subject_transaction_id)<>'INVESTMENT_CHARGE' OR (SELECT transaction_type FROM transactions WHERE transaction_id=NEW.object_transaction_id) IN ('INVESTMENT_CHARGE','REVERSAL')))
OR (NEW.relationship_type='REVERSES' AND ((SELECT transaction_type FROM transactions WHERE transaction_id=NEW.subject_transaction_id)<>'REVERSAL' OR (SELECT transaction_type FROM transactions WHERE transaction_id=NEW.object_transaction_id)='REVERSAL'))
BEGIN SELECT RAISE(ABORT,'Invalid relationship endpoints'); END;
CREATE TRIGGER relationship_endpoints_update BEFORE UPDATE ON transaction_relationships
WHEN NEW.relationship_type='CHARGE_FOR' AND ((SELECT transaction_type FROM transactions WHERE transaction_id=NEW.subject_transaction_id)<>'INVESTMENT_CHARGE' OR (SELECT transaction_type FROM transactions WHERE transaction_id=NEW.object_transaction_id) IN ('INVESTMENT_CHARGE','REVERSAL'))
BEGIN SELECT RAISE(ABORT,'Invalid CHARGE_FOR endpoints'); END;
CREATE INDEX ix_relationship_object ON transaction_relationships(object_transaction_id,relationship_type);
