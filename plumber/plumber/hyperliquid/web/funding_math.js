/* Pure calculations shared by the browser and Node regression tests. */
(function (root) {
  'use strict';
  const HOUR = 3600000, YEAR = 8760;
  const annualPercent = rate => Number(rate) * YEAR * 100;
  function periodBounds(time, frequency) {
    const date = new Date(time);
    let start = Date.UTC(date.getUTCFullYear(), date.getUTCMonth(), date.getUTCDate()), end;
    if (frequency === 'month') {
      start = Date.UTC(date.getUTCFullYear(), date.getUTCMonth(), 1);
      end = Date.UTC(date.getUTCFullYear(), date.getUTCMonth() + 1, 1);
    } else if (frequency === 'week') {
      start -= ((date.getUTCDay() + 6) % 7) * 24 * HOUR;
      end = start + 7 * 24 * HOUR;
    } else if (frequency === 'day') end = start + 24 * HOUR;
    else throw Error('Invalid aggregation frequency');
    return {start, end, period: new Date(start).toISOString().slice(0, frequency === 'month' ? 7 : 10)};
  }
  function aggregate(rows, frequency, start, end) {
    if (!rows.length) return [];
    const ordered = [...rows].sort((a,b)=>a.time-b.time);
    start ??= Math.floor(ordered[0].time / HOUR) * HOUR;
    end ??= (Math.floor(ordered.at(-1).time / HOUR) + 1) * HOUR;
    if (!(Number.isFinite(start) && Number.isFinite(end) && start < end)) return [];
    const coins = [...new Set(ordered.map(row=>row.coin))], buckets = new Map();
    for (const coin of coins) {
      for (let t = start; t < end;) {
        const b = periodBounds(t, frequency);
        buckets.set(`${coin}|${b.period}`, {...b, coin, rows: []}); t = b.end;
      }
    }
    const seen = new Set();
    for (const row of ordered) {
      if (row.time < start || row.time >= end) continue;
      const slot = `${row.coin}|${Math.floor(row.time / HOUR)}`;
      if (seen.has(slot)) throw Error(`重复的小时费率记录：${row.coin}`);
      seen.add(slot);
      const period = periodBounds(row.time, frequency).period;
      buckets.get(`${row.coin}|${period}`).rows.push(row);
    }
    return [...buckets.values()].map(b => {
      const count = b.rows.length;
      const total = count ? b.rows.reduce((sum,row)=>sum + Number(row.fundingRate),0) : null;
      const slots = new Set(b.rows.map(r=>Math.floor(r.time/HOUR)));
      const firstSlot = Math.ceil(Math.max(start,b.start)/HOUR), endSlot = Math.ceil(Math.min(end,b.end)/HOUR);
      let missing = Math.max(0,endSlot-firstSlot);
      for (const slot of slots) if (slot >= firstSlot && slot < endSlot) missing--;
      const fullHours = (b.end-b.start)/HOUR;
      return {coin:b.coin,period:b.period,cumulativeRate:total,cumulativeRatePct:total === null?null:total*100,
        annualizedRatePct:count?total/count*YEAR*100:null,fundingRecords:count,coverageHours:count,
        fullPeriodHours:fullHours,completePeriod:slots.size===fullHours,missingHours:missing,
        firstTime:count?b.rows[0].time:null,lastTime:count?b.rows.at(-1).time:null};
    }).sort((a,b)=>a.period.localeCompare(b.period)||a.coin.localeCompare(b.coin));
  }
  const api = {HOUR,YEAR,annualPercent,periodBounds,aggregate};
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.fundingMath = api;
})(typeof window === 'undefined' ? globalThis : window);
