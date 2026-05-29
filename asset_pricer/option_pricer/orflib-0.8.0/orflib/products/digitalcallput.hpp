/**
@file  digitalcallput.hpp
@brief The payoff of a Digital Call/Put option
*/

#ifndef ORF_DIGITALCALLPUT_HPP
#define ORF_DIGITALCALLPUT_HPP

#include <orflib/products/product.hpp>

BEGIN_NAMESPACE(orf)

/** Digital call/put class
*/
class DigitalCallPut : public Product
{
public:
	/** Initializing ctor */
	DigitalCallPut(int payoffType, double strike, double timeToExp);

	/** The number of assets this product depends on */
	virtual size_t nAssets() const override { return 1; }

	/** Evaluates the product given the passed-in path
	The "pricePath" matrix must have as many rows as
	the number of fixing times
	*/
	virtual void eval(Matrix const& pricePath) override;

	/** Evaluates the product at fixing time index idx
	*/
	virtual void eval(size_t idx, Vector const& spots, double contValue) override;

private:
	int payoffType_;     // 1: call; -1 put
	double strike_;
	double timeToExp_;
};

///////////////////////////////////////////////////////////////////////////////
// Inline definitions

inline DigitalCallPut::DigitalCallPut(int payoffType, double strike, double timeToExp)
	: payoffType_(payoffType), strike_(strike), timeToExp_(timeToExp)
{
	ORF_ASSERT(payoffType == 1 || payoffType == -1, "DigitalCallPut: the payoff type must be 1 (call) or -1 (put)!");
	ORF_ASSERT(strike > 0.0, "DigitalCallPut: the strike must be positive!");
	ORF_ASSERT(timeToExp > 0.0, "DigitalCallPut: the time to expiration must be positive!");

	// resize
	fixTimes_.resize(1);
	fixTimes_[0] = timeToExp_;

	payTimes_.resize(1);
	payTimes_[0] = timeToExp_;

	payAmounts_.resize(1);
}

inline void DigitalCallPut::eval(Matrix const& pricePath)
{
	double S_T = pricePath(0, 0);
	payAmounts_[0] = payoffType_ == 1 ? (S_T >= strike_ ? 1.0 : 0.0) : (S_T >= strike_ ? 0.0 : 1.0);
}

inline void DigitalCallPut::eval(size_t idx, Vector const& spots, double contValue)
{
	ORF_ASSERT(idx == 0, "DigitalCallPut: fixing time index is wrong!");
	double S_T = spots[idx];
	payAmounts_[idx] = payoffType_ == 1 ? (S_T >= strike_ ? 1.0 : 0.0) : (S_T >= strike_ ? 0.0 : 1.0);

}
END_NAMESPACE(orf)

#endif // ORF_EUROPEANCALLPUT_HPP
