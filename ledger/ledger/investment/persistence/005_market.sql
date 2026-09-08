CREATE TABLE market_prices(observation_id INTEGER PRIMARY KEY AUTOINCREMENT, observable_id TEXT NOT NULL, price TEXT NOT NULL CHECK(typeof(price)='text'), currency TEXT NOT NULL REFERENCES currencies(currency_code), as_of TEXT NOT NULL, source TEXT NOT NULL);
CREATE INDEX ix_market_price_date ON market_prices(observable_id,as_of);
CREATE TABLE market_fx(observation_id INTEGER PRIMARY KEY AUTOINCREMENT, base_currency TEXT NOT NULL REFERENCES currencies(currency_code), quote_currency TEXT NOT NULL REFERENCES currencies(currency_code), rate TEXT NOT NULL CHECK(typeof(rate)='text'), as_of TEXT NOT NULL, source TEXT NOT NULL, CHECK(base_currency<>quote_currency));
CREATE INDEX ix_market_fx_date ON market_fx(base_currency,quote_currency,as_of);
