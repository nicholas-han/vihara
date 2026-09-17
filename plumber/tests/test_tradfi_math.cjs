const test = require('node:test');
const assert = require('node:assert/strict');
const {HOUR, annualPercent, aggregate} = require('../plumber/hyperliquid/web/funding_math.js');
const row = (time, rate='0.0001', coin='xyz:TEST') => ({coin,time:Date.parse(time),fundingRate:rate});

test('hourly simple annualization keeps sign and does not compound',()=>{
  assert.ok(Math.abs(annualPercent('0.0001')-87.6)<1e-10);
  assert.ok(Math.abs(annualPercent('-0.0001')+87.6)<1e-10);
});
test('monthly buckets reset and respect UTC boundaries',()=>{
  const result=aggregate([row('2026-01-31T23:00:00.019Z','0.001'),row('2026-02-01T00:00:00.008Z','-0.0002')],'month');
  assert.deepEqual(result.map(r=>r.period),['2026-01','2026-02']);
  assert.equal(result[0].cumulativeRatePct,.1);
  assert.equal(result[1].cumulativeRatePct,-.02);
  assert.equal(result[0].completePeriod,false);
});
test('missing hours are reported and never dilute sample annualization',()=>{
  const result=aggregate([row('2026-01-01T00:00:00.01Z'),row('2026-01-01T02:00:00.02Z')],'day',Date.parse('2026-01-01'),Date.parse('2026-01-01T03:00:00Z'))[0];
  assert.equal(result.missingHours,1);
  assert.equal(result.coverageHours,2);
  assert.ok(Math.abs(result.annualizedRatePct-87.6)<1e-10);
});
test('empty intervening periods have null sums rather than zeros',()=>{
  const result=aggregate([row('2026-01-01'),row('2026-03-01')],'month');
  assert.equal(result[1].period,'2026-02');
  assert.equal(result[1].cumulativeRate,null);
  assert.equal(result[1].missingHours,28*24);
});
test('complete leap February requires 696 hourly observations',()=>{
  const start=Date.parse('2024-02-01'), rows=Array.from({length:696},(_,i)=>({coin:'xyz:TEST',time:start+i*HOUR+19,fundingRate:'.0001'}));
  const result=aggregate(rows,'month',start,Date.parse('2024-03-01'))[0];
  assert.equal(result.completePeriod,true);
  assert.equal(result.missingHours,0);
  assert.equal(result.fullPeriodHours,696);
});
test('Monday weeks work across year boundaries; start filter is inclusive',()=>{
  const rows=[row('2025-12-31'),row('2026-01-01'),row('2026-01-05')];
  const result=aggregate(rows,'week',Date.parse('2026-01-01'),Date.parse('2026-01-06'));
  assert.deepEqual(result.map(r=>r.period),['2025-12-29','2026-01-05']);
  assert.equal(result[0].fundingRecords,1);
});
test('duplicate hourly records fail instead of doubling cumulative fees',()=>{
  assert.throws(()=>aggregate([row('2026-01-01'),row('2026-01-01T00:00:01Z')],'month'),/重复/);
});
