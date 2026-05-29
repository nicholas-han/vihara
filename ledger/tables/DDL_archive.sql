DROP DATABASE IF EXISTS `archive`;
CREATE DATABASE `archive`; 
USE `archive`;

SET NAMES utf8;
SET character_set_client = utf8mb4; 

CREATE TABLE `CountryRegion` (
	`CountryRegion_ID` INT NOT NULL AUTO_INCREMENT,
	`CountryRegion_2L_Code` VARCHAR(5) NOT NULL UNIQUE,
    `CountryRegion_3L_Code` VARCHAR(5) NOT NULL UNIQUE,
    `CountryRegion_Name` VARCHAR(20),
	PRIMARY KEY (`CountryRegion_ID`)
);
INSERT INTO `CountryRegion` VALUES
	(DEFAULT, 'CN', 'CHN', 'China'),
	(DEFAULT, 'HK', 'HKG', 'Hong Kong, SAR China'),
	(DEFAULT, 'TW', 'TWN', 'Taiwan, Province of China'),
	(DEFAULT, 'US', 'USA', 'United States of America'),
	(DEFAULT, 'JP', 'JPN', 'Japan');


CREATE TABLE `Language` (
	`Lang_ID` INT NOT NULL AUTO_INCREMENT,
	`Lang_Code` VARCHAR(5) NOT NULL UNIQUE,
    `Lang_Name` VARCHAR(20),
    `CountryRegion_ID` INT,
	PRIMARY KEY (`Lang_ID`),
	FOREIGN KEY (`CountryRegion_ID`) REFERENCES `CountryRegion`(`CountryRegion_ID`)
);
INSERT INTO `Language` VALUES
	(DEFAULT,'ZH','Chinese', 'CN'),
	(DEFAULT,'EN','English', 'US'),
	(DEFAULT,'JA','Japanese', 'JP');
