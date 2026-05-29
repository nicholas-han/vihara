/**
@file  xlfunctions4.cpp
@brief Implementation of Excel callable functions
*/

#include <orflib/market/market.hpp>
#include <orflib/products/europeancallput.hpp>
#include <orflib/products/digitalcallput.hpp>
#include <orflib/methods/pde/pde1dsolver.hpp>

#include <xlorflib/xlutils.hpp>
#include <xlw/xlw.h>

#include <cmath>

using namespace xlw;
using namespace orf;

BEGIN_EXTERN_C

LPXLFOPER EXCEL_EXPORT xlOrfEuroBSPDE(LPXLFOPER xlPayoffType,
                                      LPXLFOPER xlStrike,
                                      LPXLFOPER xlTimeToExp,
                                      LPXLFOPER xlSpot,
                                      LPXLFOPER xlDiscountCrv,
                                      LPXLFOPER xlDivYield,
                                      LPXLFOPER xlVolatility,
                                      LPXLFOPER xlPdeParams,
                                      LPXLFOPER xlHeaders)
{
  EXCEL_BEGIN;

  if (XlfExcel::Instance().IsCalledByFuncWiz())
    return XlfOper(true);

  int payoffType = XlfOper(xlPayoffType).AsInt();
  double spot = XlfOper(xlSpot).AsDouble();
  double strike = XlfOper(xlStrike).AsDouble();
  double timeToExp = XlfOper(xlTimeToExp).AsDouble();

  std::string name = xlStripTick(XlfOper(xlDiscountCrv).AsString());
  SPtrYieldCurve spyc = market().yieldCurves().get(name);
  ORF_ASSERT(spyc, "error: yield curve " + name + " not found");

  double divYield = XlfOper(xlDivYield).AsDouble();

  // vol curve
  std::string volname;
  if (XlfOper(xlVolatility).IsNumber()) {
	  // create flat vol curve
	  double vol = XlfOper(xlVolatility).AsDouble();
	  volname = "VOLTS";
	  Vector tmats({ 100 });
	  Vector vals({ vol });
	  VolatilityTermStructure::VolType voltype = VolatilityTermStructure::SPOTVOL;
	  std::pair<std::string, unsigned long> pair = market().volatilities().set(volname,
			  new VolatilityTermStructure(tmats.begin(), tmats.end(), vals.begin(), vals.end(), voltype));
  }
  else {
	  volname = xlStripTick(XlfOper(xlVolatility).AsString());
  }
  SPtrVolatilityTermStructure spvc = market().volatilities().get(volname);
  ORF_ASSERT(spvc, "error: vol curve " + volname + " not found");

  // read the PDE parameters
  PdeParams pdeparams = xlOperToPdeParams(xlPdeParams);
  // handling the xlHeaders argument
  bool headers;
  if (XlfOper(xlHeaders).IsMissing() || XlfOper(xlHeaders).IsNil())
    headers = false;
  else
    headers = XlfOper(xlHeaders).AsBool();

  // create the product
  SPtrProduct spprod(new EuropeanCallPut(payoffType, strike, timeToExp));
  // create the PDE solver
  Pde1DResults results;
  Pde1DSolver solver(spprod, spyc, spot, divYield, spvc, results);
  solver.solve(pdeparams);

  // write results to the outbound XlfOper
  RW offset = headers ? 1 : 0;
  XlfOper xlRet(1 + offset, 1); // construct a range of size 2 x 1
  if (headers) {
    xlRet(0, 0) = "Price";
  }
  xlRet(offset, 0) = results.prices[0];

  return xlRet;

  EXCEL_END;
}


LPXLFOPER EXCEL_EXPORT xlOrfDigiBSPDE(LPXLFOPER xlPayoffType,
	LPXLFOPER xlStrike,
	LPXLFOPER xlTimeToExp,
	LPXLFOPER xlSpot,
	LPXLFOPER xlDiscountCrv,
	LPXLFOPER xlDivYield,
	LPXLFOPER xlVolatility,
	LPXLFOPER xlPdeParams,
	LPXLFOPER xlHeaders)
{
	EXCEL_BEGIN;

	if (XlfExcel::Instance().IsCalledByFuncWiz())
		return XlfOper(true);

	int payoffType = XlfOper(xlPayoffType).AsInt();
	double spot = XlfOper(xlSpot).AsDouble();
	double strike = XlfOper(xlStrike).AsDouble();
	double timeToExp = XlfOper(xlTimeToExp).AsDouble();

	std::string name = xlStripTick(XlfOper(xlDiscountCrv).AsString());
	SPtrYieldCurve spyc = market().yieldCurves().get(name);
	ORF_ASSERT(spyc, "error: yield curve " + name + " not found");

	double divYield = XlfOper(xlDivYield).AsDouble();

	// vol curve
	std::string volname;
	if (XlfOper(xlVolatility).IsNumber()) {
		// create flat vol curve
		double vol = XlfOper(xlVolatility).AsDouble();
		volname = "VOLTS";
		Vector tmats({ 100 });
		Vector vals({ vol });
		VolatilityTermStructure::VolType voltype = VolatilityTermStructure::SPOTVOL;
		std::pair<std::string, unsigned long> pair =
			market().volatilities().set(volname,
				new VolatilityTermStructure(tmats.begin(), tmats.end(), vals.begin(), vals.end(), voltype));
	}
	else {
		volname = xlStripTick(XlfOper(xlVolatility).AsString());
	}
	SPtrVolatilityTermStructure spvc = market().volatilities().get(volname);
	ORF_ASSERT(spvc, "error: vol curve " + volname + " not found");


	// read the PDE parameters
	PdeParams pdeparams = xlOperToPdeParams(xlPdeParams);
	// handling the xlHeaders argument
	bool headers;
	if (XlfOper(xlHeaders).IsMissing() || XlfOper(xlHeaders).IsNil())
		headers = false;
	else
		headers = XlfOper(xlHeaders).AsBool();

	// create the product
	SPtrProduct spprod(new DigitalCallPut(payoffType, strike, timeToExp));
	// create the PDE solver
	Pde1DResults results;
	Pde1DSolver solver(spprod, spyc, spot, divYield, spvc, results);
	solver.solve(pdeparams);

	// write results to the outbound XlfOper
	RW offset = headers ? 1 : 0;
	XlfOper xlRet(1 + offset, 1); // construct a range of size 2 x 1
	if (headers) {
		xlRet(0, 0) = "Price";
	}
	xlRet(offset, 0) = results.prices[0];

	return xlRet;

	EXCEL_END;
}

END_EXTERN_C
