'use strict';
const $ = id => document.getElementById(id);
let sport = 'mlb', tab = 'sheets', data = null, requestNumber = 0;
let serverAtLoad = 0, monotonicAtLoad = 0, wallAtLoad = 0;
const names = {sheets: 'Best supported edges', moneylines: 'Moneyline research', props: 'Player-prop research', touchdowns: 'Anytime touchdown research'};
const pct = v => Number.isFinite(v) ? (v * 100).toFixed(1) + '%' : '—';
const el = (tag, text, cls) => {
  const n = document.createElement(tag);
  if (text !== undefined) n.textContent = text;
  if (cls) n.className = cls;
  return n;
};
function message(text) { $('message').textContent = text; $('message').hidden = !text; }
function clearData() {
  data = null;
  $('rows').replaceChildren();
  $('downloads').replaceChildren();
  for (const id of ['games', 'modeled', 'showing']) $(id).textContent = '0';
  $('snapshot').textContent = '';
  $('coverage').textContent = '';
  $('empty').textContent = 'No verified current research snapshot. Refresh to check availability.';
  $('empty').hidden = false;
}
function login(text) {
  ++requestNumber; // invalidate any concurrent successful response
  clearData();
  $('workspace').hidden = true;
  $('logout').hidden = true;
  $('login').hidden = false;
  $('refresh').disabled = false;
  message(text || '');
}
async function api(path, options = {}) {
  const r = await fetch(path, {credentials: 'same-origin', ...options});
  if (!r.ok) {
    let body = {};
    try { body = await r.json(); } catch {}
    if (r.status === 401) login(body.detail);
    throw new Error(typeof body.detail === 'string' ? body.detail : 'Research is temporarily unavailable.');
  }
  return r.json();
}
function option(select, value, label) { const n = el('option', label); n.value = value; select.append(n); }
function serverNow() {
  // Anchor to server time; advance even across browser suspension. Moving the
  // device clock backward must not extend a price or session's validity.
  return serverAtLoad + Math.max(0, performance.now() - monotonicAtLoad, Date.now() - wallAtLoad);
}
function currentRows() {
  const now = serverNow();
  return (data?.rows || []).filter(r =>
    Number.isFinite(Date.parse(r.valid_until)) && Date.parse(r.valid_until) > now &&
    Number.isFinite(Date.parse(r.starts_at)) && Date.parse(r.starts_at) > now
  );
}
function table() {
  if (!data) return;
  if (Date.parse(data.session_expires_at) <= serverNow()) {
    login('Your session expired. Type !vip in Discord for a fresh private link.');
    return;
  }
  const all = currentRows();
  $('games').textContent = new Set(all.map(r => r.event_id || r.event)).size;
  $('modeled').textContent = all.filter(r => Number.isFinite(r.model_probability)).length;
  const query = $('search').value.trim().toLowerCase(), day = $('date').value, side = $('side').value;
  const rows = all.filter(r =>
    (!query || [r.event, r.player, r.selection].join(' ').toLowerCase().includes(query)) &&
    (!day || (r.starts_at || '').slice(0, 10) === day) &&
    (!side || (r.side || '').toLowerCase() === side)
  );
  const sort = $('sort').value;
  if (sort !== 'start') {
    const field = {value: 'conservative_roi', edge: 'edge', model: 'model_probability', market: 'market_probability'}[sort];
    rows.sort((a, b) => (b[field] ?? -Infinity) - (a[field] ?? -Infinity));
  } else rows.sort((a, b) => (a.starts_at || '').localeCompare(b.starts_at || ''));
  $('rows').replaceChildren();
  for (const r of rows) {
    const item = el('article', undefined, 'data-row');
    const match = el('div', undefined, 'match');
    match.append(el('div', r.player || r.event, 'row-title'));
    match.append(el('span', r.player ? r.event : new Date(r.starts_at).toLocaleString(undefined, {month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit'}), 'row-sub'));
    const selection = el('div', undefined, 'selection');
    selection.append(el('div', r.selection, 'row-title'));
    selection.append(el('span', [r.odds, r.book, 'Research only'].filter(Boolean).join(' · '), 'row-sub'));
    selection.title = 'Model: ' + r.model_version + '\nPrice checked: ' + r.price_at +
      '\nEstimated ROI: ' + pct(r.expected_roi) + '\nPolicy-adjusted ROI: ' + pct(r.conservative_roi) +
      '\nUncertainty haircut: ' + pct(r.uncertainty) + ' (policy setting, not a confidence interval)';
    item.append(match, selection);
    for (const [label, value, cls] of [
      ['Model', pct(r.model_probability), ''],
      ['Market', pct(r.market_probability), ''],
      ['Edge', Number.isFinite(r.edge) ? (r.edge >= 0 ? '+' : '') + (r.edge * 100).toFixed(1) + ' pp' : '—', Number.isFinite(r.edge) ? (r.edge >= 0 ? 'positive' : 'negative') : '']
    ]) {
      const metric = el('div', undefined, 'metric ' + cls);
      metric.append(el('span', label, 'metric-label'), el('span', value));
      item.append(metric);
    }
    $('rows').append(item);
  }
  $('showing').textContent = rows.length;
  $('empty').hidden = rows.length > 0;
  $('empty').textContent = all.length ? 'No research edges match these filters.' :
    'No qualifying fresh research edges. Prices may have expired, models may be unavailable, or no positive value passed the filters. Only the owner can run a new scan.';
  if (!all.length) $('downloads').replaceChildren();
}
async function load() {
  const n = ++requestNumber;
  message('');
  clearData(); // no old sport/tab/failed-request results left looking current
  $('data-section').hidden = tab === 'insights' || tab === 'learn';
  $('insights-section').hidden = tab !== 'insights';
  $('learn-section').hidden = tab !== 'learn';
  $('refresh').disabled = false;
  if (tab === 'insights') return;
  if (tab === 'learn') {
    $('lessons').replaceChildren();
    try {
      const lessons = await api('/v1/member/learn');
      if (n !== requestNumber) return;
      for (const lesson of lessons) {
        const details = el('details');
        details.append(el('summary', lesson.title), el('p', lesson.body));
        $('lessons').append(details);
      }
    } catch (e) { if (n === requestNumber) message(e.message); }
    return;
  }
  $('section-title').textContent = names[tab];
  $('league-label').textContent = sport.toUpperCase() + ' RESEARCH';
  $('refresh').disabled = true;
  try {
    const selectedMarket = $('market').value;
    const result = await api('/v1/member/sheets?' + new URLSearchParams({sport, tab, market: selectedMarket}));
    if (n !== requestNumber) return;
    data = result;
    serverAtLoad = Date.parse(result.server_time);
    monotonicAtLoad = performance.now();
    wallAtLoad = Date.now();
    // No server timestamp = no basis for asserting that these rows are current.
    if (!Number.isFinite(serverAtLoad)) data.rows = [];
    $('snapshot').textContent = result.completed_at ? 'Snapshot ' + new Date(result.completed_at).toLocaleString() : '';
    $('coverage').textContent = result.state === 'UNAVAILABLE' ? result.notice :
      'Experimental estimates—not official picks. Only positive, fresh research edges are shown. ' +
      (result.partial ? 'Market coverage is partial. ' : '') +
      'Refresh reads saved data; it does not run the owner scanner.';
    const dateValue = $('date').value;
    $('date').replaceChildren(); option($('date'), '', 'All upcoming dates');
    for (const d of [...new Set(result.rows.map(r => (r.starts_at || '').slice(0, 10)).filter(Boolean))].sort()) option($('date'), d, d);
    $('date').value = dateValue;
    $('market').replaceChildren(); option($('market'), '', 'All markets');
    for (const m of result.markets || []) option($('market'), m, m.replaceAll('_', ' '));
    $('market').value = selectedMarket;
    if (tab === 'sheets') {
      for (let g = 0; g < 3; g++) for (let p = 1; p <= (result.image_pages?.[g] || 0); p++) {
        const a = el('a', [ 'Games', sport === 'mlb' ? 'Pitchers' : 'Props', sport === 'nfl' ? 'Anytime TD' : sport === 'mlb' ? 'Batters' : 'Periods' ][g] + ' · image ' + p);
        a.href = '/v1/member/image/' + sport + '/' + g + '/' + p + '.png?featured=1';
        a.target = '_blank'; a.rel = 'noopener'; $('downloads').append(a);
      }
    }
    table();
  } catch (e) { if (n === requestNumber) { clearData(); message(e.message); } }
  finally { if (n === requestNumber) $('refresh').disabled = false; }
}
for (const b of document.querySelectorAll('[data-sport]')) b.addEventListener('click', () => {
  sport = b.dataset.sport;
  for (const t of document.querySelectorAll('[data-sport]')) t.setAttribute('aria-pressed', t === b);
  $('market').value = ''; $('date').value = ''; load();
});
for (const b of document.querySelectorAll('[data-tab]')) b.addEventListener('click', () => {
  tab = b.dataset.tab;
  for (const t of document.querySelectorAll('[data-tab]')) t.setAttribute('aria-pressed', t === b);
  $('market').value = ''; $('date').value = ''; load();
});
for (const id of ['search', 'date', 'side', 'sort']) $(id).addEventListener(id === 'search' ? 'input' : 'change', table);
$('market').addEventListener('change', load);
$('refresh').addEventListener('click', load);
$('logout').addEventListener('click', async () => {
  try { await api('/v1/member/logout', {method: 'POST'}); login('Signed out.'); }
  catch (e) { login(e.message); }
});
// No network traffic or provider usage: expiry only clears local rows.
setInterval(table, 1000);
document.addEventListener('visibilitychange', () => {
  if (!document.hidden) { clearData(); if (!$('workspace').hidden) load(); }
});
(async () => {
  const token = new URLSearchParams(location.hash.slice(1)).get('access');
  if (location.hash) history.replaceState(null, '', '/vip');
  try {
    const info = await api('/vip/info');
    if (info.icon_url) {
      $('brand-icon').src = info.icon_url; $('brand-icon').hidden = false; $('lettermark').hidden = true;
      for (const rel of ['icon', 'apple-touch-icon']) {
        const icon = el('link'); icon.rel = rel; icon.href = info.icon_url; document.head.append(icon);
      }
    }
  } catch {}
  if (token) {
    try { await api('/v1/member/session', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({ticket: token})}); }
    catch (e) { login(e.message); return; }
  }
  $('login').hidden = true; $('workspace').hidden = false; $('logout').hidden = false;
  await load();
})();
