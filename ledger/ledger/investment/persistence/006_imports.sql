CREATE TABLE import_batches(batch_id INTEGER PRIMARY KEY AUTOINCREMENT, filename TEXT NOT NULL, file_hash TEXT NOT NULL UNIQUE);
CREATE TABLE import_rows(row_id INTEGER PRIMARY KEY AUTOINCREMENT, batch_id INTEGER NOT NULL REFERENCES import_batches(batch_id), row_number INTEGER NOT NULL, raw_json TEXT NOT NULL, override_json TEXT NOT NULL DEFAULT '{}', status TEXT NOT NULL DEFAULT 'STAGED' CHECK(status IN ('STAGED','READY','ERROR','COMMITTED','DUPLICATE','UNMAPPED','ZERO_EVIDENCE')), payload_json TEXT, error_json TEXT, UNIQUE(batch_id,row_number));
CREATE TABLE import_links(row_id INTEGER PRIMARY KEY REFERENCES import_rows(row_id), transaction_id INTEGER NOT NULL REFERENCES transactions(transaction_id), dedup_key TEXT NOT NULL, payload_hash TEXT NOT NULL, source_hash TEXT NOT NULL);
CREATE INDEX ix_import_dedup ON import_links(dedup_key);
CREATE TRIGGER import_link_no_update BEFORE UPDATE ON import_links BEGIN SELECT RAISE(ABORT,'Import links are immutable'); END;
CREATE TRIGGER import_link_no_delete BEFORE DELETE ON import_links BEGIN SELECT RAISE(ABORT,'Import links are immutable'); END;
CREATE TRIGGER import_committed_no_update BEFORE UPDATE ON import_rows WHEN EXISTS(SELECT 1 FROM import_links WHERE row_id=OLD.row_id) BEGIN SELECT RAISE(ABORT,'Committed import rows are immutable'); END;
