'use strict';
const $ = id => document.getElementById(id);
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const number = (n, digits = 2) => Number(n).toLocaleString('en-US', {maximumFractionDigits: digits});
const pct = rate => `${(Number(rate) * 100).toFixed(6)}%`;
const utc = value => new Date(value).toISOString().replace('T', ' ').replace('.000Z', '').replace('Z', '');
let data = null, selected = '', page = 0, busy = false, pollTimer;
const pageSize = 50;
function showError(message) { $('error').hidden = !message; $('error').textContent = message || ''; }
function setBusy(value) { busy = value; $('load').disabled = value; $('import').disabled = value; $('load').textContent = value ? '正在获取…' : '↻ 获取最新数据'; }
function selectedRows() { return data ? data.funding.filter(row => row.coin === selected).sort((a,b) => a.time - b.time) : []; }
function validateData(value) {
  if (!value || !Array.isArray(value.markets) || !Array.isArray(value.funding) || !value.markets.length) throw Error('JSON 必须包含非空 markets 数组和 funding 数组。请导入下载脚本导出的文件。');
  const coins = new Set();
  value.markets.forEach(m => { if (typeof m.coin !== 'string' || coins.has(m.coin) || !Number.isFinite(Number(m.dayNtlVlm)) || Number(m.dayNtlVlm) < 0) throw Error('合约或成交额字段无效'); coins.add(m.coin); });
  value.funding.forEach(r => { if (!coins.has(r.coin) || !Number.isFinite(Number(r.fundingRate)) || !Number.isSafeInteger(r.time) || !Number.isFinite(new Date(r.time).getTime())) throw Error('资金费率或时间字段无效'); });
  return value;
}
function loadedRange() {
  const times = data.funding.map(row=>row.time);
  const start = Date.parse(data.start_utc_inclusive || data.start_utc);
  const end = Date.parse(data.end_utc_exclusive || data.end_utc);
  return {start:Number.isFinite(start)?start:times.reduce((a,b)=>Math.min(a,b),Infinity), end:Number.isFinite(end)?end:times.reduce((a,b)=>Math.max(a,b),-Infinity)+1};
}
function cumulativeRange() {
  const loaded = loadedRange(), chosen = Date.parse($('cumulative-start').value);
  return {start:Number.isFinite(chosen)?Math.max(chosen,loaded.start):loaded.start,end:loaded.end,
          clipped:Number.isFinite(chosen)&&chosen<loaded.start};
}
function renderCumulative() {
  const range = cumulativeRange(), raw = selectedRows();
  const rows = fundingMath.aggregate(raw, $('frequency').value, range.start, range.end);
  $('cumulative-range').textContent = range.start < range.end ? `累计范围 ${utc(range.start)} → ${utc(range.end)} UTC（结束不含）。${range.clipped?'起始日期早于缓存范围，仅显示已下载部分；更早数据请在上方设置下载开始日期并刷新。':''}` : '累计起始日期晚于已下载区间，请调整日期。';
  $('cumulative-body').innerHTML=rows.map(r=>`<tr><td>${esc(r.period)}</td><td>${esc(r.coin)}</td><td>${r.cumulativeRate===null?'—':r.cumulativeRate.toFixed(8)}</td><td class="${r.cumulativeRate<0?'negative':'positive'}">${r.cumulativeRatePct===null?'—':r.cumulativeRatePct.toFixed(5)+'%'}</td><td>${r.annualizedRatePct===null?'—':r.annualizedRatePct.toFixed(4)+'%'}</td><td>${r.fundingRecords}</td><td>${r.completePeriod?'完整周期':r.fundingRecords?'部分周期':'无记录'}${r.missingHours?' · 区间缺 '+r.missingHours+' 小时':''}</td></tr>`).join('')||'<tr><td colspan="7" class="empty">该合约在所选区间没有记录。</td></tr>';
  drawCumulativeChart(rows);
  const currentMonth=new Date().toISOString().slice(0,7);
  const month=fundingMath.aggregate(raw,'month',range.start,range.end).find(r=>r.period===currentMonth);
  $('month-label').textContent=`${currentMonth} 当月累计（UTC）`;
  $('month-total').textContent=month?.cumulativeRatePct==null?'—':month.cumulativeRatePct.toFixed(5)+'%';
  $('month-coverage').textContent=month?.fundingRecords?`${month.fundingRecords} 条 · 已选区间内，截至 ${utc(month.lastTime)} UTC${month.missingHours?' · 区间存在缺失':''}`:'所选区间没有当月记录';
}
function drawCumulativeChart(rows) {
  const valid=rows.filter(row=>row.cumulativeRatePct!==null);
  $('cumulative-chart-title').textContent=`${selected} · 累计费率`;
  if(!valid.length){$('cumulative-chart-stats').textContent='暂无累计记录';$('cumulative-chart').innerHTML='<p class="empty">该合约在所选区间没有累计记录。</p>';return;}
  const W=1100,H=270,L=82,R=24,T=20,B=42, values=valid.map(r=>r.cumulativeRatePct), low=Math.min(0,...values), high=Math.max(0,...values), span=high-low||.001;
  const y=v=>T+(high+span*.12-v)/(span*1.24)*(H-T-B), x=i=>rows.length===1?(L+W-R)/2:L+i/(rows.length-1)*(W-L-R);
  let svg=`<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(selected)} 历史累计费率折线图"><title>${esc(selected)} 历史累计费率（%）</title>`;
  for(let i=0;i<5;i++){const v=low+span*1.24*i/4-span*.12;svg+=`<line class="grid" x1="${L}" x2="${W-R}" y1="${y(v)}" y2="${y(v)}"/><text class="axis" x="${L-12}" y="${y(v)+3}" text-anchor="end">${v.toFixed(4)}%</text>`;}
  const zeroY=y(0);svg+=`<line class="zero" x1="${L}" x2="${W-R}" y1="${zeroY}" y2="${zeroY}"/>`;
  let path='', connected=false;
  rows.forEach((row,i)=>{if(row.cumulativeRatePct===null){connected=false;return;}path+=`${connected?'L':'M'}${x(i).toFixed(2)},${y(row.cumulativeRatePct).toFixed(2)} `;connected=true;});
  svg+=`<path class="line cumulative-line" d="${path}"/>`;
  rows.forEach((row,i)=>{if(row.cumulativeRatePct!==null)svg+=`<circle class="point" cx="${x(i)}" cy="${y(row.cumulativeRatePct)}" r="3"><title>${esc(row.period)} · ${row.cumulativeRatePct.toFixed(5)}% · ${row.completePeriod?'完整周期':'部分周期'}${row.missingHours?' · 缺失 '+row.missingHours+' 小时':''}</title></circle>`;});
  rows.forEach((row,i)=>{if(rows.length<=6||i===0||i===rows.length-1||i%Math.ceil(rows.length/5)===0)svg+=`<text class="axis" x="${x(i)}" y="${H-16}" text-anchor="${rows.length===1?'middle':i===0?'start':i===rows.length-1?'end':'middle'}">${esc(row.period)}</text>`;});
  $('cumulative-chart').innerHTML=svg+'</svg>';
  const latest=valid.at(-1), min=Math.min(...values), max=Math.max(...values);$('cumulative-chart-stats').textContent=`${valid.length} 个周期 · 最新 ${latest.cumulativeRatePct.toFixed(5)}% · 区间 ${min.toFixed(5)}% 至 ${max.toFixed(5)}%`;
}
function present(result, source) {
  data = validateData(result); page = 0;
  if (!data.markets.some(m => m.coin === selected)) selected = data.markets[0].coin;
  $('source').textContent = source;
  $('metric-markets').textContent = data.markets.length;
  $('metric-records').textContent = number(data.funding.length,0);
  const start = data.start_utc_inclusive || data.start_utc, end = data.end_utc_exclusive || data.end_utc;
  $('metric-range').textContent = start && end ? `${start.slice(0,10)} → ${end.slice(0,10)} · UTC` : '区间以记录为准';
  const snapshot = data.snapshot_end_utc || data.snapshot_utc;
  $('snapshot').textContent = snapshot ? `排名快照 ${utc(snapshot)} UTC` : '文件未提供排名快照时间';
  $('coin').innerHTML = data.markets.map(m => `<option value="${esc(m.coin)}">${esc(m.coin)}</option>`).join('');
  $('coin').disabled = false; $('coin').value = selected;
  $('export-json').disabled = false;
  $('metric-frequency').textContent = `${data.funding_spec?.label || '每小时'}`;
  const unknown = Array.isArray(data.unclassified) ? data.unclassified : [];
  $('unknown-count').textContent = `· ${unknown.length} 个未识别市场`;
  $('unknown').innerHTML = unknown.length ? `<table><thead><tr><th>未识别合约</th><th>24h 名义成交额</th></tr></thead><tbody>${unknown.slice(0,100).map(m=>`<tr><td>${esc(m.coin)}</td><td>${number(m.dayNtlVlm)}</td></tr>`).join('')}</tbody></table><p>显示成交额最高的前 ${Math.min(unknown.length,100)} 个；完整列表可导出 JSON。</p>` : '<p>没有未识别市场记录。</p>';
  const errors = Object.entries(data.errors || {});
  showError(errors.length ? errors.map(([coin,message])=>`${coin}：${message}`).join('；') : '');
  const loaded = loadedRange();
  if(Number.isFinite(loaded.start)) $('cumulative-start').value=new Date(loaded.start).toISOString().slice(0,10);
  renderSelected();
}
function renderSelected() {
  $('coin').value = selected;
  const latest = new Map(), counts = new Map();
  data.funding.forEach(row => { if (!latest.has(row.coin) || latest.get(row.coin).time < row.time) latest.set(row.coin,row); counts.set(row.coin,(counts.get(row.coin)||0)+1); });
  $('ranking-body').innerHTML = data.markets.map((m,index) => {
    const row = latest.get(m.coin), state = m.status || (counts.get(m.coin) ? 'ok' : 'empty');
    const annual = row ? Number(row.annualizedRatePct ?? Number(row.fundingRate)*8760*100).toFixed(3) : '—';
    return `<tr class="${m.coin === selected ? 'active-row' : ''}"><td class="rank">${String(m.rank || index+1).padStart(2,'0')}</td><td><button class="coin-button" data-coin="${esc(m.coin)}">${esc(m.coin)}</button><span class="dex">${esc(m.dex || 'native')}</span></td><td>${number(m.dayNtlVlm)}</td><td>${esc(m.funding_frequency?.label || data.funding_spec?.label || '每小时')}</td><td class="${row && Number(row.fundingRate)<0 ? 'negative' : 'positive'}">${row ? `${pct(row.fundingRate)} / ${annual}%` : '—'}</td><td>${number(counts.get(m.coin)||0,0)}</td><td><span class="badge ${state === 'error' ? 'error' : state === 'empty' ? 'empty' : ''}">${({ok:'已获取',empty:'空历史',error:'失败'})[state] || '未知'}</span></td></tr>`;
  }).join('');
  drawChart(selectedRows()); renderPage(); renderCumulative();
}
function renderPage() {
  const rows = selectedRows().reverse(), totalPages = Math.max(1,Math.ceil(rows.length/pageSize));
  page = Math.max(0,Math.min(page,totalPages-1));
  $('funding-body').innerHTML = rows.slice(page*pageSize,(page+1)*pageSize).map(r => `<tr><td>${esc(utc(r.time))}</td><td>${esc(r.coin)}</td><td>${esc(r.fundingRate)}</td><td class="${Number(r.fundingRate)<0?'negative':'positive'}">${pct(r.fundingRate)}</td><td>${Number(r.annualizedRatePct ?? Number(r.fundingRate)*8760*100).toFixed(4)}%</td><td>${esc(r.premium)}</td></tr>`).join('') || '<tr><td colspan="6" class="empty">该合约在所选区间没有资金费率记录。空历史不代表零费率。</td></tr>';
  $('count').textContent = `· ${number(rows.length,0)} 条`;
  $('page-info').textContent = `第 ${page+1} / ${totalPages} 页 · 每页 ${pageSize} 条 · 最新在前`;
  $('prev').disabled = page===0; $('next').disabled = page>=totalPages-1;
  $('export-csv').disabled = !rows.length;
  const latest=selectedRows().at(-1); $('annualized').textContent=latest ? `${Number(latest.annualizedRatePct ?? Number(latest.fundingRate)*8760*100).toFixed(4)}%` : '—';
}
function drawChart(rows) {
  $('chart-coin').textContent = selected;
  if (!rows.length) { $('chart').innerHTML='<p class="empty">该时间范围没有可绘制的记录。</p>'; $('chart-stats').textContent='暂无历史费率'; return; }
  const rates = rows.map(r=>Number(r.fundingRate)*100), W=1100,H=270,L=82,R=24,T=20,B=42;
  let low=Math.min(0,...rates), high=Math.max(0,...rates), span=high-low || .001;
  low-=span*.12; high+=span*.12;
  const from=rows[0].time, to=rows.at(-1).time;
  const x=t=>L+(t-from)/(to-from||1)*(W-L-R), y=v=>T+(high-v)/(high-low)*(H-T-B);
  let svg=`<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(selected)} 历史资金费率百分比曲线"><title>${esc(selected)} 历史资金费率（%）</title>`;
  for(let i=0;i<5;i++){const v=low+(high-low)*i/4;svg+=`<line class="grid" x1="${L}" x2="${W-R}" y1="${y(v)}" y2="${y(v)}"/><text class="axis" x="${L-12}" y="${y(v)+3}" text-anchor="end">${v.toFixed(5)}%</text>`;}
  const labels=from===to?1:5;
  for(let i=0;i<labels;i++){const t=from+(to-from)*i/4;svg+=`<text class="axis" x="${x(t)}" y="${H-16}" text-anchor="${i===0?'start':i===4?'end':'middle'}">${utc(t).slice(5,16)}</text>`;}
  svg+=`<line class="zero" x1="${L}" x2="${W-R}" y1="${y(0)}" y2="${y(0)}"/>`;
  let path='';rows.forEach((r,i)=>{path+=`${i===0||r.time-rows[i-1].time>7200000?'M':'L'}${x(r.time).toFixed(2)},${y(rates[i]).toFixed(2)} `;});
  svg+=`<path class="line" d="${path}"/>`;
  const stride=Math.max(1,Math.ceil(rows.length/1000));
  rows.forEach((r,i)=>{if(i%stride===0||i===rows.length-1)svg+=`<circle class="point" cx="${x(r.time)}" cy="${y(rates[i])}" r="2"><title>${esc(utc(r.time))} UTC · ${pct(r.fundingRate)}</title></circle>`;});
  $('chart').innerHTML=svg+'</svg>';
  $('chart-stats').textContent=`最新 ${pct(rows.at(-1).fundingRate)} · 均值 ${(rates.reduce((a,b)=>a+b,0)/rates.length).toFixed(6)}% · 每次记录，非年化`;
}
async function request(url,options) { const r=await fetch(url,options);const body=await r.json();if(!r.ok)throw Error(body.error||`HTTP ${r.status}`);return body; }
async function poll() {
  try {
    const state=await request('/api/state'); $('status').textContent=state.progress;
    setBusy(state.running);
    if(state.running){pollTimer=setTimeout(poll,1200);return;}
    if(state.has_result){const final=await request('/api/result');present(final.result,'服务器快照');}
    if(state.error)showError(state.error);
  } catch(e){setBusy(false);showError(`本地服务连接失败：${e.message}。确认 Python 服务仍在运行。`);}
}
$('query').addEventListener('submit',async event=>{
  event.preventDefault();if(busy)return;clearTimeout(pollTimer);showError('');setBusy(true);
  try {await request('/api/refresh',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({top:Number($('top').value),days:Number($('days').value),dex:$('dex').value,start:$('start').value,end:$('end').value})});await poll();}
  catch(e){setBusy(false);showError(e.message);}
});
$('coin').addEventListener('change',()=>{selected=$('coin').value;page=0;renderSelected();});
$('frequency').addEventListener('change',()=>{if(data)renderCumulative();});
$('cumulative-start').addEventListener('change',()=>{if(data)renderCumulative();});
$('ranking-body').addEventListener('click',event=>{const button=event.target.closest('[data-coin]');if(button){selected=button.dataset.coin;page=0;renderSelected();}});
$('prev').onclick=()=>{page--;renderPage();};$('next').onclick=()=>{page++;renderPage();};
function download(text,type,name){const url=URL.createObjectURL(new Blob([text],{type}));const a=document.createElement('a');a.href=url;a.download=name;document.body.appendChild(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);}
$('export-json').onclick=()=>{const range=cumulativeRange(); const enriched={...data, funding:data.funding.map(r=>({...r,fundingIntervalHours:1,annualizedRatePct:String(fundingMath.annualPercent(r.fundingRate))})),cumulative:fundingMath.aggregate(data.funding,$('frequency').value,range.start,range.end),cumulative_options:{frequency:$('frequency').value,start:range.start,end:range.end}};download(JSON.stringify(enriched,null,2),'application/json','tradfi_funding.json');};
$('export-csv').onclick=()=>{
  const quote=v=>`"${String(v??'').replace(/"/g,'""')}"`;
  const fields=['coin','time','time_utc','fundingRate','fundingRatePct','fundingIntervalHours','annualizedRatePct','premium'];
  const rows=selectedRows().map(r=>({...r,time_utc:new Date(r.time).toISOString(),fundingRatePct:Number(r.fundingRate)*100,fundingIntervalHours:1,annualizedRatePct:fundingMath.annualPercent(r.fundingRate)}));
  download('\uFEFF'+[fields.join(','),...rows.map(r=>fields.map(f=>quote(r[f])).join(','))].join('\r\n'),'text/csv;charset=utf-8',`${selected.replace(/[^a-zA-Z0-9_-]/g,'_')}_funding.csv`);
};
$('import').addEventListener('change',async()=>{const file=$('import').files[0];if(!file)return;try{present(JSON.parse(await file.text()),`导入 · ${file.name}`);$('status').textContent='本地快照已加载；尚未刷新市场。';}catch(e){showError(`导入失败：${e.message}`);}finally{$('import').value='';}});
(async()=>{try{const state=await request('/api/result');if(state.result)present(state.result,'本地缓存快照');$('status').textContent=state.progress;if(state.error)showError(state.error);if(state.running){setBusy(true);poll();}}catch(e){showError(e.message);}})();
