USE `accounting`;
CREATE OR REPLACE VIEW `all_accounts` AS

SELECT FS_Name AS FS, Ledger_Name AS Ledger, Acct_Name AS Account, Dr_Cr_Name AS Debit_Credit
FROM account
JOIN Ledger USING (Ledger_ID)
JOIN FinancialStatement USING (FS_ID)
JOIN DebitCredit ON Dr_Cr_Polarity=Dr_Cr_ID
ORDER BY account.Acct_ID