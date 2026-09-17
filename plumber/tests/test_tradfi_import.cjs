const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const math = require('../plumber/hyperliquid/web/funding_math.js');

// Exercise the actual import event, validation and rendering with DOM containers.
// This also detects references to removed/renamed HTML IDs.
test('one-year ten-contract exports larger than 30 MB can be reopened', async () => {
  const web = path.join(__dirname, '../plumber/hyperliquid/web');
  const html = fs.readFileSync(path.join(web, 'index.html'), 'utf8');
  const elements = new Map([...html.matchAll(/\bid="([^"]+)"/g)].map(m => [m[1], {
    value: '', textContent: '', innerHTML: '', handlers: {},
    addEventListener(event, callback) { this.handlers[event] = callback; }
  }]));
  elements.get('frequency').value = 'month';
  const context = vm.createContext({document: {getElementById: id => elements.get(id)},
    fundingMath: math, setTimeout, clearTimeout,
    fetch: async () => ({ok: true, json: async () => ({result: null, progress: '就绪'})})});
  vm.runInContext(fs.readFileSync(path.join(web, 'app.js'), 'utf8'), context);
  await new Promise(resolve => setImmediate(resolve));

  const start = Date.parse('2025-01-01T00:00:00Z');
  const markets = Array.from({length:10},(_,i)=>({coin:`xyz:TEST${i}`,dex:'xyz',dayNtlVlm:'123456789.123',rank:i+1}));
  const funding = markets.flatMap(m => Array.from({length:365*24},(_,i)=>({
    coin:m.coin,time:start+i*math.HOUR+19,time_utc:new Date(start+i*math.HOUR+19).toISOString(),
    fundingRate:'0.0000125',fundingRatePct:'0.0012500',annualizedRate:'0.1095000',
    annualizedRatePct:'10.9500000',fundingIntervalHours:1,premium:'0.00001',rank:m.rank,dayNtlVlm:m.dayNtlVlm
  })));
  const text = JSON.stringify({markets,funding,start_utc_inclusive:'2025-01-01T00:00:00Z',end_utc_exclusive:'2026-01-01T00:00:00Z',errors:{}},null,2);
  assert.ok(Buffer.byteLength(text)>30*1024*1024);
  elements.get('import').files = [{name:'one-year.json',size:Buffer.byteLength(text),text:async()=>text}];
  await elements.get('import').handlers.change();
  assert.equal(elements.get('error').hidden,true);
  assert.equal(elements.get('metric-records').textContent,'87,600');
  assert.match(elements.get('status').textContent,/本地快照已加载/);
  assert.match(elements.get('cumulative-body').innerHTML,/2025-12/);
  assert.match(elements.get('chart').innerHTML,/<svg/);
});
