# Financial Instruments NoSQL Database Design

## Overview

This design uses a document-based NoSQL database (MongoDB-style) to store financial instruments with multiple dimensions and hierarchical relationships. The schema supports:

* **Asset Class Dimension**: Equity, Fixed Income, Commodities, Currencies, etc.
  * **Hierarchical Relationships**: Listed vs OTC equity, Government vs Corporate bonds, etc.
* **Instrument Type Dimension**: Spot, Index, ETF/ETN, Forwards, Options, etc.
* **Multi-layered Classifications**: Options on futures, futures on indices, etc.

## Core Collections

### 1. Asset Classes Collection

Reference data for asset class hierarchies:

```json
{
  "_id": "EQUITY",
  "assetClassId": "EQUITY",
  "name": "Equity",
  "description": "Ownership interests in companies",
  "hierarchy": {
    "level": 1,
    "parent": null,
    "children": ["LISTED_EQUITY"]
  },
  "subClasses": [
    {
      "_id": "LISTED_EQUITY",
      "name": "Listed Equity",
      "description": "Equity traded on public exchanges",
      "hierarchy": {
        "level": 2,
        "parent": "EQUITY",
        "children": ["COMMON_STOCK", "PREFERRED_STOCK", "REIT", "MLP"]
      },
      "subClasses": [
        {
          "_id": "COMMON_STOCK",
          "name": "Common Stock",
          "description": "Ordinary shares with voting rights",
          "hierarchy": {
            "level": 3,
            "parent": "LISTED_EQUITY",
            "children": []
          }
        },
        {
          "_id": "PREFERRED_STOCK",
          "name": "Preferred Stock",
          "description": "Shares with priority over common stock",
          "hierarchy": {
            "level": 3,
            "parent": "LISTED_EQUITY",
            "children": []
          }
        },
        {
          "_id": "REIT",
          "name": "Real Estate Investment Trust",
          "description": "Company that owns income-producing real estate",
          "hierarchy": {
            "level": 3,
            "parent": "LISTED_EQUITY",
            "children": []
          }
        }
      ]
    },
    {
      "_id": "OTC_EQUITY",
      "name": "Over-the-Counter Equity",
      "description": "Equity traded off-exchange",
      "hierarchy": {
        "level": 2,
        "parent": "EQUITY",
        "children": ["PINK_SHEET", "OTCBB"]
      },
      "subClasses": [
        {
          "_id": "PINK_SHEET",
          "name": "Pink Sheet",
          "description": "OTC equity traded on pink sheets",
          "hierarchy": {
            "level": 3,
            "parent": "OTC_EQUITY",
            "children": []
          }
        },
        {
          "_id": "OTCBB",
          "name": "OTC Bulletin Board",
          "description": "OTC equity traded on bulletin board",
          "hierarchy": {
            "level": 3,
            "parent": "OTC_EQUITY",
            "children": []
          }
        }
      ]
    },
    {
      "_id": "PRIVATE_EQUITY",
      "name": "Private Equity",
      "description": "Equity in privately held companies",
      "hierarchy": {
        "level": 2,
        "parent": "EQUITY",
        "children": []
      }
    }
  ]
}
```

### 2. Instrument Types Collection

Reference data for instrument type hierarchies:

```json
{
  "_id": "OPTION",
  "instrumentTypeId": "OPTION",
  "name": "Option",
  "description": "Derivative contract giving the right to buy/sell",
  "hierarchy": {
    "level": 1,
    "parent": null,
    "children": ["CALL_OPTION", "PUT_OPTION", "EXOTIC_OPTION"]
  },
  "subTypes": [
    {
      "_id": "CALL_OPTION",
      "instrumentTypeId": "CALL_OPTION",
      "name": "Call Option",
      "description": "Right to buy underlying asset",
      "hierarchy": {
        "level": 2,
        "parent": "OPTION",
        "children": []
      },
      "styles": ["AMERICAN", "EUROPEAN", "BERMUDAN"]
    },
    {
      "_id": "PUT_OPTION",
      "instrumentTypeId": "PUT_OPTION",
      "name": "Put Option", 
      "description": "Right to sell underlying asset",
      "hierarchy": {
        "level": 2,
        "parent": "OPTION",
        "children": []
      },
      "styles": ["AMERICAN", "EUROPEAN", "BERMUDAN"]
    },
    {
      "_id": "EXOTIC_OPTION",
      "instrumentTypeId": "EXOTIC_OPTION",
      "name": "Exotic Option",
      "description": "Complex option with non-standard features",
      "hierarchy": {
        "level": 2,
        "parent": "OPTION",
        "children": ["BARRIER_OPTION", "BINARY_OPTION", "ASIAN_OPTION"]
      },
      "subTypes": [
        {
          "_id": "BARRIER_OPTION",
          "instrumentTypeId": "BARRIER_OPTION",
          "name": "Barrier Option",
          "description": "Option that becomes active/inactive when barrier is hit",
          "hierarchy": {
            "level": 3,
            "parent": "EXOTIC_OPTION",
            "children": []
          }
        },
        {
          "_id": "BINARY_OPTION",
          "instrumentTypeId": "BINARY_OPTION",
          "name": "Binary Option",
          "description": "Option with fixed payout or nothing",
          "hierarchy": {
            "level": 3,
            "parent": "EXOTIC_OPTION",
            "children": []
          }
        },
        {
          "_id": "ASIAN_OPTION",
          "instrumentTypeId": "ASIAN_OPTION",
          "name": "Asian Option",
          "description": "Option based on average price over time",
          "hierarchy": {
            "level": 3,
            "parent": "EXOTIC_OPTION",
            "children": []
          }
        }
      ]
    }
  ],
  "characteristics": {
    "leverage": "HIGH",
    "timeDecay": true,
    "volatilitySensitive": true,
    "requiresUnderlying": true
  }
}
```

### 3. Instruments Collection

The main collection storing all financial instruments with flexible schema:

```json
{
  "_id": "AAPL_OPTION_20241215_200_C",
  "instrumentId": "AAPL_OPTION_20241215_200_C",
  "name": "Apple Inc. Call Option",
  "symbol": "AAPL241215C200",
  "description": "Apple Inc. Call Option expiring Dec 15, 2024, Strike $200",
  
  // Primary Classification Dimensions
  "assetClass": {
    "primary": "EQUITY",
    "secondary": "LISTED_EQUITY",
    "tertiary": "COMMON_STOCK"
  },
  
  "instrumentType": {
    "primary": "OPTION",
    "subType": "CALL_OPTION",
    "style": "AMERICAN"
  },
  
  // Market Information
  "market": {
    "exchange": "NASDAQ",
    "marketType": "LISTED",
    "tradingHours": "09:30-16:00 EST",
    "currency": "USD"
  },
  
  // Option-Specific Fields
  "optionDetails": {
    "underlyingAsset": "AAPL",
    "strikePrice": 200.00,
    "expirationDate": "2024-12-15",
    "optionType": "CALL",
    "multiplier": 100,
    "settlementType": "PHYSICAL"
  },
  
  // Pricing Information
  "pricing": {
    "lastPrice": 15.50,
    "bid": 15.25,
    "ask": 15.75,
    "volume": 1250000,
    "openInterest": 2500000,
    "lastUpdate": "2024-01-15T16:00:00Z"
  },
  
  // Relationships to Other Instruments
  "relationships": {
    "underlying": "AAPL",
    "derivativeOf": ["AAPL"],
    "hasDerivatives": [],
    "partOfIndex": ["SPX", "QQQ"],
    "trackedBy": []
  },
  
  // Regulatory and Compliance
  "regulatory": {
    "cusip": "037833100",
    "isin": "US0378331005",
    "sedol": "2046251",
    "lei": "HWUPKR0MPOU8FGXBT394",
    "assetClassCode": "EQ",
    "instrumentTypeCode": "OPT"
  },
  
  // Metadata
  "metadata": {
    "createdAt": "2024-01-01T00:00:00Z",
    "updatedAt": "2024-01-15T16:00:00Z",
    "status": "ACTIVE",
    "dataSource": "BLOOMBERG",
    "version": 1
  }
}
```

### 4. Relationships Collection

Explicit relationship mapping between instruments:

```json
{
  "_id": "AAPL_OPTION_20241215_200_C_UNDERLYING",
  "relationshipId": "AAPL_OPTION_20241215_200_C_UNDERLYING",
  "fromInstrument": "AAPL_OPTION_20241215_200_C",
  "toInstrument": "AAPL",
  "relationshipType": "UNDERLYING",
  "relationshipDirection": "OUTGOING",
  "metadata": {
    "hedgeRatio": 1.0,
    "correlation": 0.85,
    "createdAt": "2024-01-01T00:00:00Z"
  }
}
```

### 5. Indices Collection

For index instruments and their constituents:

```json
{
  "_id": "SPX",
  "indexId": "SPX",
  "name": "S&P 500 Index",
  "symbol": "SPX",
  "description": "Market-cap weighted index of 500 large-cap US stocks",
  
  "indexDetails": {
    "provider": "S&P_DOW_JONES",
    "methodology": "MARKET_CAP_WEIGHTED",
    "baseDate": "1926-01-01",
    "baseValue": 10.0,
    "rebalancingFrequency": "QUARTERLY",
    "currency": "USD"
  },
  
  "constituents": [
    {
      "instrumentId": "AAPL",
      "weight": 0.0723,
      "shares": 15000000000,
      "marketCap": 3000000000000,
      "sector": "TECHNOLOGY"
    },
    {
      "instrumentId": "MSFT", 
      "weight": 0.0689,
      "shares": 7500000000,
      "marketCap": 2800000000000,
      "sector": "TECHNOLOGY"
    }
  ],
  
  "pricing": {
    "currentValue": 4850.25,
    "dailyChange": 12.50,
    "dailyChangePercent": 0.26,
    "lastUpdate": "2024-01-15T16:00:00Z"
  }
}
```

## Complex Instrument Examples

### Futures on Index
```json
{
  "_id": "ES_FUTURE_202403",
  "instrumentId": "ES_FUTURE_202403",
  "name": "E-mini S&P 500 March 2024 Future",
  "symbol": "ESH24",
  
  "assetClass": {
    "primary": "EQUITY",
    "secondary": "EQUITY_INDEX"
  },
  
  "instrumentType": {
    "primary": "FUTURE",
    "subType": "EQUITY_INDEX_FUTURE"
  },
  
  "futureDetails": {
    "underlyingIndex": "SPX",
    "contractSize": 50,
    "tickSize": 0.25,
    "tickValue": 12.50,
    "expirationDate": "2024-03-15",
    "settlementType": "CASH",
    "marginRequirement": 13200
  },
  
  "relationships": {
    "underlying": "SPX",
    "derivativeOf": ["SPX"],
    "hasDerivatives": ["ES_OPTION_202403_5000_C"]
  }
}
```

### Option on Future
```json
{
  "_id": "ES_OPTION_202403_5000_C",
  "instrumentId": "ES_OPTION_202403_5000_C", 
  "name": "E-mini S&P 500 Call Option on March Future",
  "symbol": "ESH24C5000",
  
  "assetClass": {
    "primary": "EQUITY",
    "secondary": "EQUITY_INDEX"
  },
  
  "instrumentType": {
    "primary": "OPTION",
    "subType": "CALL_OPTION"
  },
  
  "optionDetails": {
    "underlyingAsset": "ES_FUTURE_202403",
    "strikePrice": 5000.00,
    "expirationDate": "2024-03-08",
    "optionType": "CALL",
    "multiplier": 50,
    "settlementType": "CASH"
  },
  
  "relationships": {
    "underlying": "ES_FUTURE_202403",
    "derivativeOf": ["ES_FUTURE_202403", "SPX"],
    "hasDerivatives": []
  }
}
```

### Fixed Income Example
```json
{
  "_id": "US10Y_BOND",
  "instrumentId": "US10Y_BOND",
  "name": "US 10-Year Treasury Bond",
  "symbol": "US10Y",
  
  "assetClass": {
    "primary": "FIXED_INCOME",
    "secondary": "GOVERNMENT_BOND",
    "tertiary": "TREASURY_BOND"
  },
  
  "instrumentType": {
    "primary": "BOND",
    "subType": "GOVERNMENT_BOND"
  },
  
  "bondDetails": {
    "issuer": "US_TREASURY",
    "maturityDate": "2034-02-15",
    "couponRate": 4.25,
    "couponFrequency": "SEMI_ANNUAL",
    "faceValue": 1000,
    "creditRating": "AAA",
    "yieldToMaturity": 4.15,
    "duration": 8.2,
    "convexity": 0.75
  },
  
  "pricing": {
    "cleanPrice": 98.75,
    "dirtyPrice": 99.12,
    "accruedInterest": 0.37,
    "yield": 4.15,
    "lastUpdate": "2024-01-15T16:00:00Z"
  }
}
```

## Database Design Principles

### 1. Flexible Schema
- Use embedded documents for instrument-specific details
- Allow different fields based on instrument type
- Use arrays for multi-valued attributes

### 2. Hierarchical Relationships
- Store both embedded relationships and separate relationship collection
- Support multiple relationship types (underlying, derivative, constituent)
- Enable recursive queries for complex instrument chains

### 3. Performance Optimization
- Create compound indexes on frequently queried fields:
  ```javascript
  // Asset class and instrument type
  db.instruments.createIndex({"assetClass.primary": 1, "instrumentType.primary": 1})
  
  // Symbol and market
  db.instruments.createIndex({"symbol": 1, "market.exchange": 1})
  
  // Relationships
  db.relationships.createIndex({"fromInstrument": 1, "relationshipType": 1})
  ```

### 4. Data Integrity
- Use reference data collections for asset classes and instrument types
- Implement validation rules based on instrument type
- Maintain referential integrity through application logic

### 5. Scalability Considerations
- Partition by asset class or exchange for large datasets
- Use sharding for global deployments
- Implement caching for frequently accessed reference data

## Query Examples

### Find all options on equity instruments
```javascript
db.instruments.find({
  "instrumentType.primary": "OPTION",
  "assetClass.primary": "EQUITY"
})
```

### Find all derivatives of a specific underlying
```javascript
db.instruments.find({
  "relationships.derivativeOf": "AAPL"
})
```

### Find instruments by asset class hierarchy
```javascript
db.instruments.find({
  "assetClass.secondary": "LISTED_EQUITY"
})
```

### Complex relationship query (options on futures on indices)
```javascript
db.instruments.find({
  "relationships.derivativeOf": {
    $in: db.instruments.find({
      "relationships.derivativeOf": "SPX",
      "instrumentType.primary": "FUTURE"
    }).map(i => i._id)
  },
  "instrumentType.primary": "OPTION"
})
```

This design provides a flexible, scalable foundation for storing complex financial instruments with their multi-dimensional classifications and hierarchical relationships.
