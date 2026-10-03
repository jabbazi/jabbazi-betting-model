'use strict';
(() => {
  let credential = '', page = 1, total = 0, generation = 0;
  const el = id => document.getElementById(id);
  const text = (tag, value, parent) => {
    const node = document.createElement(tag);
    node.textContent = value == null || value === '' ? 'Unavailable' : String(value);
    parent.appendChild(node); return node;
  };
  const percent = value => value == null ? 'Unavailable' : `${(Number(value) * 100).toFixed(1)}%`;
  async function load() {
    const request = ++generation;
    el('cards').replaceChildren();
    if (!credential) { el('message').textContent = 'Enter your private credential to load research.'; return; }
    el('message').textContent = 'Loading research…';
    try {
      const query = new URLSearchParams({page: String(page)});
      if (el('sport').value) query.set('sport', el('sport').value);
      const response = await fetch(`/v1/owner/review?${query}`, {headers: {Authorization: `Bearer ${credential}`}, cache: 'no-store', credentials: 'omit'});
      if (!response.ok) throw new Error(response.status === 401 ? 'Private credential not accepted.' : 'Research unavailable. Try again later.');
      const data = await response.json();
      if (request !== generation) return;
      total = data.total;
      el('message').textContent = `${data.status} • ${total} archived rows • Page ${page}\nSnapshot: ${data.snapshot_time || 'Unavailable'}${data.truncated ? '\nArchive row limit reached; coverage incomplete.' : ''}`;
      for (const card of data.cards) {
        const article = document.createElement('article');
        text('h2', card.event, article);
        text('p', [card.participant, card.selection, card.line, card.market].filter(v => v != null && v !== '').join(' • '), article);
        text('p', card.decision, article).className = 'tag';
        const list = document.createElement('dl'); article.appendChild(list);
        for (const [label, value] of [
          ['Sportsbook', card.book], ['Decimal price', card.decimal_odds], ['Price timestamp', card.price_time_utc],
          ['Market no-vig probability', percent(card.market_no_vig_probability)], ['Research model probability', percent(card.research_probability)],
          ['Model version', card.model_version], ['Probability edge', percent(card.probability_edge)], ['Expected ROI', percent(card.expected_roi)],
          ['Uncertainty haircut', percent(card.uncertainty)], ['Stake', 'Unavailable — research only'], ['Play-to price', 'Unavailable — research only']
        ]) {text('dt', label, list); text('dd', value, list);}
        text('p', card.reason, article);
        const blocks = document.createElement('ul'); article.appendChild(blocks);
        card.blockers.forEach(block => text('li', block, blocks));
        el('cards').appendChild(article);
      }
      el('previous').disabled = page <= 1;
      el('next').disabled = page * 25 >= total;
    } catch (error) { if (request === generation) el('message').textContent = error.message; }
  }
  el('login').addEventListener('submit', event => {event.preventDefault(); credential = el('token').value; el('token').value = ''; page = 1; load();});
  el('refresh').onclick = load;
  el('sport').onchange = () => {page = 1; load();};
  el('previous').onclick = () => {if (page > 1) {page--; load();}};
  el('next').onclick = () => {if (page * 25 < total) {page++; load();}};
  el('lock').onclick = () => {credential = ''; el('token').value = ''; total = 0; page = 1; load();};
  window.addEventListener('pagehide', () => {credential = ''; generation++; el('cards').replaceChildren();});
})();
