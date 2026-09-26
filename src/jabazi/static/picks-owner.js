'use strict';
const $ = id => document.getElementById(id);
const node = (tag, text) => { const n = document.createElement(tag); n.textContent = text; return n; };
let credential = '', draft = null, busy = false;
const notice = text => { $('notice').textContent = text; };
function lock() { credential = ''; draft = null; $('key').value = ''; $('desk').hidden = true; $('cards').replaceChildren(); $('preview').textContent = ''; $('publish').hidden = true; }
async function request(path, body) {
  const r = await fetch(path, {method: body ? 'POST' : 'GET', credentials: 'omit', headers: {'Authorization': 'Bearer ' + credential, ...(body ? {'Content-Type': 'application/json'} : {})}, ...(body ? {body: JSON.stringify(body)} : {})});
  const result = await r.json();
  if (!r.ok) { if (r.status === 401 || r.status === 403) lock(); throw new Error(typeof result.detail === 'string' ? result.detail : 'Check the required fields. The card was not accepted.'); }
  return result;
}
function decimal(a) { const n = Number(a); if (!Number.isFinite(n) || Math.abs(n) < 100) throw Error('American odds must be at least +100 or at most -100.'); return String(n > 0 ? 1+n/100 : 1+100/-n); }
async function load() {
  const data = await request('/v1/official'); $('cards').replaceChildren();
  if (!data.cards.length) $('cards').append(node('p','No official cards issued yet.'));
  for (const p of data.cards) {
    const article = node('article', ''); article.className = 'panel';
    article.append(node('h3', p.selection), node('p', `${p.card} · ${p.event} · ${p.status} · revision ${p.revision}`), node('p', p.id));
    const form = node('form','');
    const type = node('select',''); type.setAttribute('aria-label','Update or result');
    for (const t of ['WATCH','WITHDRAWN','win','loss','push','void']) { const o=node('option',t);o.value=t;type.append(o); }
    const reason=node('textarea','');reason.placeholder='Reason or result evidence (required)';reason.required=true;reason.minLength=10;reason.maxLength=500;reason.setAttribute('aria-label','Reason or evidence');
    const correction=node('input','');correction.placeholder='Correction reason (required to revise a result)';correction.setAttribute('aria-label','Correction reason');
    const button=node('button','Record update');form.append(type,reason,correction,button);
    let command = null;
    form.addEventListener('input',()=>{command=null;});
    form.addEventListener('submit',async e=>{
      e.preventDefault(); if (busy) return; busy=true;button.disabled=true;
      const isUpdate=['WATCH','WITHDRAWN'].includes(type.value);
      command ||= {idempotency_key:crypto.randomUUID(),expected_revision:p.revision,...(isUpdate?{status:type.value,reason:reason.value}:{result:type.value,evidence:reason.value,correction_reason:correction.value||null})};
      try { await request('/v1/official/'+p.id+(isUpdate?'/update':'/result'),command);notice('Update recorded. Original history retained.');await load(); }
      catch(e){notice(e.message);}finally{busy=false;button.disabled=false;}
    });
    article.append(form);$('cards').append(article);
  }
}
$('connect').addEventListener('click',async()=>{credential=$('key').value.trim();$('key').value='';try{await load();$('desk').hidden=false;notice('Owner desk connected.');}catch(e){notice(e.message);}});
$('lock').addEventListener('click',()=>{lock();notice('Desk locked.');});
$('issue').addEventListener('input',()=>{draft=null;$('publish').hidden=true;$('preview').textContent='';});
$('issue').addEventListener('submit',e=>{
  e.preventDefault();
  try {
    const f=Object.fromEntries(new FormData(e.target));
    draft={idempotency_key:crypto.randomUUID(),card:f.card,sport:f.sport,event_id:f.event_id,event:f.event,starts_at:new Date(f.starts_at).toISOString(),market:f.market,selection:f.selection,line:f.line||null,participant:f.participant||null,sportsbook:f.sportsbook,decimal_odds:decimal(f.american),minimum_decimal:decimal(f.play_to),price_observed_at:new Date().toISOString(),stake_units:f.stake_units,reasoning:f.reasoning,evidence:f.evidence,risks:f.risks,position_id:f.position_id||null,owner_reviewed:$('reviewed').checked};
    if(Number(draft.minimum_decimal)>Number(draft.decimal_odds))throw Error('Offered price is beyond your play-to limit.');
    $('preview').textContent=`${f.card.toUpperCase()} · ${f.event}\n${f.selection} ${f.line} · ${f.american} · ${f.sportsbook}\n${f.stake_units}u · Play to ${f.play_to} or better\n${f.reasoning}\nRisks: ${f.risks}\nOwner-issued. This does not approve any research model for betting.`;
    $('publish').hidden=false;
  }catch(e){draft=null;notice(e.message);}
});
$('publish').addEventListener('click',async()=>{
  if(!draft||busy)return;busy=true;$('publish').disabled=true;
  try{await request('/v1/official',draft);draft=null;$('issue').reset();$('publish').hidden=true;$('preview').textContent='';notice('Official card recorded. Delivery is tracked separately by the worker.');await load();}
  catch(e){notice(e.message);}finally{busy=false;$('publish').disabled=false;}
});
window.addEventListener('pagehide',lock);
