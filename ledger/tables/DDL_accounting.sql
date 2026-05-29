DROP DATABASE IF EXISTS `accounting`;
CREATE DATABASE `accounting`; 
USE `accounting`;

SET NAMES utf8;
SET character_set_client = utf8mb4; 

CREATE TABLE `DebitCredit` (
	`Dr_Cr_ID` INT NOT NULL,
	`Dr_Cr_Name` VARCHAR(6) NOT NULL UNIQUE,
	PRIMARY KEY (`Dr_Cr_ID`)
);
INSERT INTO `DebitCredit` VALUES
	(0,'Debit'),
	(1,'Credit');

CREATE TABLE `Currency` (
	`Currency_ID` INT NOT NULL AUTO_INCREMENT,
	`Currency_Abbr` CHAR(3) NOT NULL UNIQUE,
	`Currency_Name` VARCHAR(30) NOT NULL UNIQUE,
	PRIMARY KEY (`Currency_ID`)
);
INSERT INTO `Currency` VALUES
	(DEFAULT,'CNY', 'Chinese Yuan / Renminbi'),
	(DEFAULT,'USD', 'U.S. Dollar'),
	(DEFAULT,'HKD', 'Hong Kong Dollar'),
	(DEFAULT,'JPY', 'Japanese Yen'),
	(DEFAULT,'EUR', 'Euro'),
	(DEFAULT,'GBP', 'British Pound / Sterling');

CREATE TABLE `ExchangeRate` (
	`Currency_ID1` INT NOT NULL,
	`Currency_ID2` INT NOT NULL,
	`Date` DATE NOT NULL,
	`Exchange_Rate` FLOAT NOT NULL,
	PRIMARY KEY (`Currency_ID1`, `Currency_ID2`, `Date`),
	FOREIGN KEY (`Currency_ID2`) REFERENCES `Currency`(`Currency_ID`),
	FOREIGN KEY (`Currency_ID1`) REFERENCES `Currency`(`Currency_ID`)
);

CREATE TABLE `FinancialStatement` (
	`FS_ID` INT NOT NULL AUTO_INCREMENT,
	`FS_Name` VARCHAR(30) NOT NULL UNIQUE,
	PRIMARY KEY (`FS_ID`)
);
INSERT INTO `FinancialStatement` VALUES
	(DEFAULT,'Balance Sheet'),
    (DEFAULT,'Income Statement'),
    (DEFAULT,'Statement of Cash Flow');

CREATE TABLE `Ledger` (
	`Ledger_ID` INT NOT NULL AUTO_INCREMENT,
	`FS_ID` INT NOT NULL,
	`Ledger_Name` VARCHAR(30) NOT NULL UNIQUE,
	PRIMARY KEY (`Ledger_ID`),
	FOREIGN KEY (`FS_ID`) REFERENCES `FinancialStatement`(`FS_ID`)
);
INSERT INTO `Ledger` VALUES
	(DEFAULT,1,'Assets'),
    (DEFAULT,1,'Liabilities'),
    (DEFAULT,1,'Net Wealth'),
	(DEFAULT,2,'Income'),
	(DEFAULT,2,'Expenditure');

CREATE TABLE `Account` (
	`Acct_ID` INT NOT NULL AUTO_INCREMENT,
	`Ledger_ID` INT NOT NULL,
	`Acct_Name` VARCHAR(30) NOT NULL UNIQUE,
	`Dr_Cr_Polarity` INT NOT NULL,
	PRIMARY KEY (`Acct_ID`),
	FOREIGN KEY (`Dr_Cr_Polarity`) REFERENCES `DebitCredit`(`Dr_Cr_ID`),
	FOREIGN KEY (`Ledger_ID`) REFERENCES `Ledger`(`Ledger_ID`)
);
INSERT INTO `Account` VALUES
	(DEFAULT,1,'Cash',0), /* Cash account db */
    (DEFAULT,1,'Held-for-Trading',0), /* Securities account db */
	(DEFAULT,1,'Available-for-Sale',0), /* Securities account db */
    (DEFAULT,1,'Held-to-Maturity',0), /* Securities account db */
    (DEFAULT,1,'Prepaid Deposits',0), /* ad hoc */
	(DEFAULT,1,'Real Estate',0), /* Real Estate db */
	(DEFAULT,1,'Retirement Pensions',0), /* ad hoc */
	(DEFAULT,2,'Credit Card Payables',1), /* Credit card db */
	(DEFAULT,2,'Loan Payables',1), /* ad hoc */
	(DEFAULT,2,'Father\'s Sponsorship',1),
	(DEFAULT,3,'My Stake',1),
	(DEFAULT,4,'Labor Income',1), /* ad hoc */
	(DEFAULT,4,'Investing Income',1),
	(DEFAULT,5,'Food & Groceries',0),
	(DEFAULT,5,'Rent',0), /* ad hoc */
	(DEFAULT,5,'Utility Bills & Subscriptions',0),  /* subscription management db */
	(DEFAULT,5,'Transportation',0),
	(DEFAULT,5,'Services & Commodities',0), /* Services, Commodities, Apparal, Electronics */
	(DEFAULT,5,'Self-Cultivation',0), /* Books, Classes, Sports, Entertainment */
	(DEFAULT,5,'Trading Costs',0),
	(DEFAULT,5,'Treating',0),
    (DEFAULT,5,'Event',0) /* ad hoc */;

CREATE TABLE `SubAccount` (
	`Sub_Acct_ID` INT NOT NULL AUTO_INCREMENT,
	`Acct_ID` INT NOT NULL,
	`Sub_Acct_Name` VARCHAR(30) NOT NULL UNIQUE,
	PRIMARY KEY (`Sub_Acct_ID`),
	FOREIGN KEY (`Acct_ID`) REFERENCES `Account`(`Acct_ID`)
);


CREATE TABLE `Transaction` (
	`Trx_ID` INT NOT NULL AUTO_INCREMENT,
	`Datetime` DATETIME NOT NULL,
	`Location` VARCHAR(30) DEFAULT NULL,
	`Description` VARCHAR(100) DEFAULT NULL,
	PRIMARY KEY (`Trx_ID`)
);

CREATE TABLE `TransactionJournalEntry` (
	`Trx_ID` INT NOT NULL,
	`Acct_ID` INT NOT NULL,
	`Amount` FLOAT DEFAULT 0,
	`Debit_or_Credit` INT NOT NULL,
	`Currency_ID`  INT NOT NULL,
	PRIMARY KEY (`Trx_ID`, `Acct_ID`),
	FOREIGN KEY (`Trx_ID`) REFERENCES `Transaction`(`Trx_ID`),
	FOREIGN KEY (`Acct_ID`) REFERENCES `Account`(`Acct_ID`),
	FOREIGN KEY (`Debit_or_Credit`) REFERENCES `DebitCredit`(`Dr_Cr_ID`),
	FOREIGN KEY (`Currency_ID`) REFERENCES `Currency`(`Currency_ID`)
);

CREATE TABLE `AccountSnapshot` (
	`Acct_ID` INT NOT NULL,
	`Date` DATE NOT NULL,
	`Amount` FLOAT DEFAULT 0,
	PRIMARY KEY (`Acct_ID`, `Date`),
	FOREIGN KEY (`Acct_ID`) REFERENCES `Account`(`Acct_ID`)
);