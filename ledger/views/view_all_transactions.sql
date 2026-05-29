USE `accounting`;
CREATE OR REPLACE VIEW `all_transactions` AS

SELECT Datetime,Dr_Cr_Name,Ledger_Name,Acct_Name,Amount,Currency_Abbr,Location,Description
FROM TransactionJournalEntry
JOIN Transaction USING (Trx_ID)
JOIN Account USING (Acct_ID)
JOIN Ledger USING (Ledger_ID)
JOIN FinancialStatement USING (FS_ID)
JOIN DebitCredit ON Debit_or_Credit=Dr_Cr_ID
JOIN Currency USING (Currency_ID)
ORDER BY Datetime,Dr_Cr_ID