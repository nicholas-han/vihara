#include <string>
#include <sstream>
#include <utility>

// Base class representing a generic financial instrument
class Instrument {
public:
    Instrument(std::string instrumentId,
                std::string instrumentSymbol,
                std::string instrumentName,
                Instrument* underlying)
        : id_(std::move(instrumentId)),
          name_(std::move(instrumentName)),
          symbol_(std::move(instrumentSymbol)),
          underlying_(underlying) {}

    virtual ~Instrument() = default;

    // Returns a stable identifier for the runtime type (e.g., "FUTURES", "OPTION")
    virtual std::string instrumentType() const = 0;

    // Serialize core and subclass fields to a compact JSON representation
    virtual std::string toJson() const = 0;

    // Accessors
    const std::string &getId() const { return id_; }
    const std::string &getSymbol() const { return symbol_; }
    const std::string &getName() const { return name_; }
    const Instrument* getUnderlying() const { return underlying_; }

protected:
    static std::string escapeJson(const std::string &value) {
        std::ostringstream out;
        for (char c : value) {
            switch (c) {
                case '"': out << "\\\""; break;
                case '\\': out << "\\\\"; break;
                case '\n': out << "\\n"; break;
                case '\r': out << "\\r"; break;
                case '\t': out << "\\t"; break;
                default: out << c; break;
            }
        }
        return out.str();
    }

private:
    std::string id_;
    std::string name_;
    std::string symbol_;
    Instrument* underlying_;
};

// Derived class representing a spot contract
class Spot : public Instrument {
public:
    Spot(std::string instrumentId,
         std::string instrumentSymbol,
         std::string instrumentName,
         Instrument* underlying,
         std::string assetClass)
        : Instrument(std::move(instrumentId),
                      std::move(instrumentSymbol),
                      std::move(instrumentName),
                      underlying),
          assetClass_(assetClass) {}
    
        // Returns a stable identifier for the runtime type (e.g., "FUTURES", "OPTION")
        std::string instrumentType() const override { return "SPOT"; }

private:
    std::string assetClass_;
};


// Derived class representing a futures contract
class Futures : public Instrument {
public:
    Futures(std::string instrumentId,
            std::string instrumentSymbol,
            std::string instrumentName,
            Instrument* underlying,
            int contractSize,
            double tickSize,
            double tickValue,
            std::string expirationDateIso,
            std::string settlementType)
        : Instrument(std::move(instrumentId),
                     std::move(instrumentSymbol),
                     std::move(instrumentName),
                     underlying),
          contractSizeUnits_(contractSize),
          tickSizePoints_(tickSize),
          tickValueCurrency_(tickValue),
          expirationDate_(std::move(expirationDateIso)),
          settlement_(std::move(settlementType)) {}

    std::string instrumentType() const override { return "FUTURE"; }

    int getContractSize() const { return contractSizeUnits_; }
    double getTickSize() const { return tickSizePoints_; }
    double getTickValue() const { return tickValueCurrency_; }
    const std::string &getExpirationDate() const { return expirationDate_; }
    const std::string &getSettlementType() const { return settlement_; }

    std::string toJson() const override {
        std::ostringstream os;
        os << '{'
           << "\"id\":\"" << escapeJson(id_) << "\"," 
           << "\"name\":\"" << escapeJson(name_) << "\"," 
           << "\"symbol\":\"" << escapeJson(symbol_) << "\"," 
           << "\"instrumentType\":\"" << instrumentType() << "\"," 
           << "\"futureDetails\":{"
           << "\"contractSize\":" << contractSizeUnits_ << ","
           << "\"tickSize\":" << tickSizePoints_ << ","
           << "\"tickValue\":" << tickValueCurrency_ << ","
           << "\"expirationDate\":\"" << escapeJson(expirationDate_) << "\"," 
           << "\"settlementType\":\"" << escapeJson(settlement_) << "\"}"
           << '}';
        return os.str();
    }

private:
    int contractSizeUnits_;
    double tickSizePoints_;
    double tickValueCurrency_;
    std::string expirationDate_;
    std::string settlement_;
};

// Derived class representing an option contract
class Option : public Instrument {
public:
    Option(std::string instrumentId,
           std::string instrumentName,
           std::string instrumentSymbol,
           std::string assetClassPrimary,
           std::string underlyingInstrumentId,
           double strikePrice,
           std::string expirationDateIso,
           std::string optionTypeCp,
           int multiplier,
           std::string settlementType,
           std::string style)
        : Instrument(std::move(instrumentId),
                      std::move(instrumentName),
                      std::move(instrumentSymbol),
                      std::move(assetClassPrimary),
                      "OPTION"),
          underlying(std::move(underlyingInstrumentId)),
          strike(strikePrice),
          expirationDate(std::move(expirationDateIso)),
          optionType(std::move(optionTypeCp)),
          contractMultiplier(multiplier),
          settlement(std::move(settlementType)),
          optionStyle(std::move(style)) {}

    std::string instrumentType() const override { return "OPTION"; }

    const std::string &getUnderlying() const { return underlying; }
    double getStrike() const { return strike; }
    const std::string &getExpirationDate() const { return expirationDate; }
    const std::string &getOptionType() const { return optionType; }
    int getMultiplier() const { return contractMultiplier; }
    const std::string &getSettlementType() const { return settlement; }
    const std::string &getStyle() const { return optionStyle; }

    std::string toJson() const override {
        std::ostringstream os;
        os << '{'
           << "\"id\":\"" << escapeJson(id) << "\"," 
           << "\"name\":\"" << escapeJson(name) << "\"," 
           << "\"symbol\":\"" << escapeJson(symbol) << "\"," 
           << "\"instrumentType\":\"" << instrumentType() << "\"," 
           << "\"optionDetails\":{"
           << "\"underlying\":\"" << escapeJson(underlying) << "\"," 
           << "\"strikePrice\":" << strike << ","
           << "\"expirationDate\":\"" << escapeJson(expirationDate) << "\"," 
           << "\"optionType\":\"" << escapeJson(optionType) << "\"," 
           << "\"multiplier\":" << contractMultiplier << ","
           << "\"settlementType\":\"" << escapeJson(settlement) << "\"," 
           << "\"style\":\"" << escapeJson(optionStyle) << "\"}"
           << '}';
        return os.str();
    }

private:
    std::string underlying;
    double strike;
    std::string expirationDate;
    std::string optionType;
    int contractMultiplier;
    std::string settlement;
    std::string optionStyle;
};


