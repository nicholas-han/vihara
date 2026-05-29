/**
@file  ptpricers.cpp
@brief Implementation of portfolio pricing functions
*/

#include <orflib/pricers/ptpricers.hpp>
#include <orflib/math/linalg/linalg.hpp>
#include <orflib/utils.hpp>
#include <cmath>

using namespace arma;

BEGIN_NAMESPACE(orf)

/** Validates the inputs and returns the number of assets */
size_t validatePtInputs(Vector const& assetRets, Vector const& assetVols, Matrix const& correlMat)
{
  // get the number of assets and check inputs for size
  size_t nassets = assetRets.size();
  ORF_ASSERT(nassets > 0, "must have at least one asset return!");
  ORF_ASSERT(assetVols.size() == nassets, "need as many volatilities as asset returns!");
  for (size_t i = 0; i < nassets; ++i)
    ORF_ASSERT(assetVols[i] > 0.0, "volatilities must be positive!");
  ORF_ASSERT(correlMat.n_rows == nassets, "need as many correlation matrix rows as asset returns!");
  ORF_ASSERT(correlMat.n_cols == nassets, "the correlation matrix must be square!");
  for (size_t i = 0; i < nassets; ++i) {
    for (size_t j = 0; j < i; ++j) {
      ORF_ASSERT(correlMat(i, j) == correlMat(j, i), "the correlation matrix must be symmetric!");
    }
  }
  return nassets;
}

/** The mean return and standard deviation of returns for the portfolio.
    The first element of the tuple is the mean and the second is the stdev
*/
std::tuple<double, double> ptRisk(Vector const& weights,
                                  Vector const& assetRets,
                                  Vector const& assetVols,
                                  Matrix const& correlMat)
{
  size_t nassets = validatePtInputs(assetRets, assetVols, correlMat);
  ORF_ASSERT(weights.size() == nassets, "number of weights must equal the number of asset returns");

  Matrix Sigma = correlMat;
  // convert correlation to covariance matrix
  for (size_t i = 0; i < nassets; ++i)
    for (size_t j = 0; j < nassets; ++j)
      Sigma(i, j) *= assetVols(i) * assetVols(j);

  double meanret = dot(weights, assetRets);
  double ptvar = dot(weights, Sigma * weights);
  double ptvol = sqrt(ptvar);
  return std::make_tuple(meanret, ptvol);
}

/** The weights of the minimum variance portfolio */
Vector mvpWeights(Vector const& assetRets, Vector const& assetVols, Matrix const& correlMat)
{
  size_t nassets = validatePtInputs(assetRets, assetVols, correlMat);
  Vector iota(nassets, fill::ones);
  Matrix SigmaInv = correlMat;
  // convert correlation to covariance matrix
  for (size_t i = 0; i < SigmaInv.n_rows; ++i)
    for (size_t j = 0; j < SigmaInv.n_cols; ++j)
      SigmaInv(i, j) *= assetVols(i) * assetVols(j);

  SigmaInv = SigmaInv.i();   // invert in place
  Vector wghts = SigmaInv * iota;
  double c = dot(iota, wghts);
  wghts = (1.0 / c) * wghts;
  return wghts;
}


/** The weights of the CAPM market portfolio */
Vector mktWeights(Vector const& assetRets, Vector const& assetVols, Matrix const& correlMat, double rfreeRate)
{
  size_t nassets = validatePtInputs(assetRets, assetVols, correlMat);
  Vector iota(nassets, fill::ones);
  Matrix SigmaInv = correlMat;
  // convert to covariance matrix
  for (size_t i = 0; i < SigmaInv.n_rows; ++i)
    for (size_t j = 0; j < SigmaInv.n_cols; ++j)
      SigmaInv(i, j) *= assetVols(i) * assetVols(j);

  SigmaInv = SigmaInv.i();   // invert in place
  Vector wghts = SigmaInv * (assetRets - rfreeRate *iota);
  double lambda_mkt = 1.0 / dot(iota, wghts);
  wghts = lambda_mkt * wghts;
  return wghts;
}

/** The mean return, volatility of return and lambda of the CAPM market portfolio
    The tuple contains these quantities in that order.
*/
std::tuple<double, double, double>
mktRisk(Vector const& assetRets, Vector const& assetVols, Matrix const& correlMat, double rfreeRate)
{
  size_t nassets = validatePtInputs(assetRets, assetVols, correlMat);
  Vector iota(nassets, fill::ones);
  Matrix SigmaInv = correlMat;
  // convert to covariance matrix
  for (size_t i = 0; i < SigmaInv.n_rows; ++i)
    for (size_t j = 0; j < SigmaInv.n_cols; ++j)
      SigmaInv(i, j) *= assetVols(i) * assetVols(j);

  SigmaInv = SigmaInv.i();   // invert in place
  Vector wghts = SigmaInv * (assetRets - rfreeRate * iota);
  double lambda_mkt = 1.0 / dot(iota, wghts);
  double h = dot((assetRets - rfreeRate *iota), wghts);

  double meanret = rfreeRate + lambda_mkt * h;
  double stdevret = lambda_mkt * sqrt(h);
  return std::make_tuple(meanret, stdevret, lambda_mkt);
}

// hw10
Vector tgtWeights(Vector const& assetRets, Vector const& assetVols, Matrix const& correlMat, double rp)
{
	size_t nassets = validatePtInputs(assetRets, assetVols, correlMat);
	Vector iota(nassets, fill::ones);
	Matrix corrMat = correlMat;

	for (size_t i=0, r= corrMat.n_rows; i<r; ++i)
		for (size_t j=0, c= corrMat.n_cols; j<c; ++j)
			corrMat(i, j) *= (assetVols(i) * assetVols(j));
	corrMat = corrMat.i();

	Vector w1 = corrMat * iota;
	Vector w2 = corrMat * assetRets;
	double a = dot(iota, w2), b = dot(assetRets, w2), c = dot(iota, w1), d = b*c - pow(a, 2);

	return corrMat*(b/d*iota-a/d*assetRets) + corrMat*(c/d*assetRets-a/d*iota)*rp;
}

Vector meanVarWeights(Vector const& assetRets, Vector const& assetVols, Matrix const& correlMat, double lambda)
{
	size_t nassets = validatePtInputs(assetRets, assetVols, correlMat);
	ORF_ASSERT(lambda >= 0, "risk aversion parameter must be non-negative");
	Vector iota(nassets, fill::ones);
	Matrix corrMat = correlMat;

	for (size_t i = 0, r = corrMat.n_rows; i<r; ++i)
		for (size_t j = 0, c = corrMat.n_cols; j<c; ++j)
			corrMat(i, j) *= assetVols(i) * assetVols(j);
	corrMat = corrMat.i();

	Vector w1 = corrMat * iota;
	Vector w2 = corrMat * assetRets;
	double a = dot(iota, w2);
	double c = dot(iota, w1);

	return (1.0/c)*w1 + lambda*(w2-(a/c)*w1);
}

std::tuple<double, double, double>
meanVarFront(Vector const& assetRets, Vector const& assetVols, Matrix const& correlMat, double lambda)
{
	size_t num_assets = validatePtInputs(assetRets, assetVols, correlMat);
	Vector iota(num_assets, fill::ones);
	Matrix corrMat = correlMat;

	for (size_t i = 0, r = corrMat.n_rows; i<r; ++i)
		for (size_t j = 0, c = corrMat.n_cols; j<c; ++j)
			corrMat(i, j) *= assetVols(i) * assetVols(j);
	corrMat = corrMat.i();

	Vector w1 = corrMat * iota;
	Vector w2 = corrMat * assetRets;
	double a = dot(iota, w2), b = dot(assetRets, w2), c = dot(iota, w1), d = b*c - a*a;
	double meanret = a/c + d/c*lambda, stdevret = sqrt(1.0/c+d/c*pow(lambda,2));

	return std::make_tuple(meanret, stdevret, lambda);

}

END_NAMESPACE(orf)
