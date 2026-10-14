'use strict';
const $=id=>document.getElementById(id);
const node=(tag,text,cls)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n;};
const pct=v=>Number.isFinite(v)?(v*100).toFixed(1)+'%':'—';
const odds=v=>Number.isFinite(v)&&v>1?(v>=2?'+'+Math.round((v-1)*100):String(Math.round(-100/(v-1)))):'—';
const when=v=>v?new Date(v).toLocaleString('en-US',{timeZone:'America/Chicago',month:'short',day:'numeric',hour:'numeric',minute:'2-digit'})+' CT':'Not available';
let me=null,serial=0,serverAnchor=Date.now(),monoAnchor=performance.now(),wallAnchor=Date.now();
function now(){return serverAnchor+Math.max(0,performance.now()-monoAnchor,Date.now()-wallAnchor);}
function chicagoDate(at=now()){return new Intl.DateTimeFormat('en-CA',{timeZone:'America/Chicago',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date(at));}
let slateMode='auto';
function activeSlateDate(){const hour=Number(new Intl.DateTimeFormat('en-US',{timeZone:'America/Chicago',hour:'numeric',hourCycle:'h23'}).format(new Date(now())));const add=slateMode==='tomorrow'||(slateMode==='auto'&&hour>=23);return add?new Date(Date.parse(chicagoDate()+'T12:00:00Z')+86400000).toISOString().slice(0,10):chicagoDate();}
function slateKey(){return activeSlateDate()+'|'+chicagoDate();}
function slateControls(root){const panel=node('div',undefined,'panel');const[l,i]=select('Slate date',[['auto','Automatic · next day at 11 PM CT'],['today','Current calendar day'],['tomorrow','Next calendar day']],slateMode);i.addEventListener('change',()=>{slateMode=i.value;render();});panel.append(l,node('p','Viewing '+activeSlateDate()+' · America/Chicago · '+(activeSlateDate()===chicagoDate()?'Current day':'Next-day research preview'),'muted'),link('Current-day results','#performance'));root.prepend(panel);}
let renderedDate=slateKey();
function live(r){return Number.isFinite(Date.parse(r.starts_at))&&chicagoDate(Date.parse(r.starts_at))===activeSlateDate()&&r.fresh&&Date.parse(r.price_at)+300000>now()&&Date.parse(r.starts_at)>now();}
function say(s){$('notice').textContent=s||'';}
function lock(message){++serial;me=null;$('workspace').hidden=true;$('navigation').hidden=true;$('signout').hidden=true;$('login').hidden=false;$('content').replaceChildren();if(message){let p=$('login-message');if(!p){p=node('p',undefined,'muted');p.id='login-message';$('login').append(p);}p.textContent=message;let retry=$('login-retry');if(!retry){retry=node('button','Retry existing session','button');retry.id='login-retry';retry.addEventListener('click',async()=>{retry.disabled=true;try{const data=await get('me');me=data;$('login').hidden=true;$('workspace').hidden=false;$('navigation').hidden=false;$('signout').hidden=false;$('access-badge').textContent=me.tier+' ACCESS';render();}catch(e){p.textContent=e.message;}finally{retry.disabled=false;}});$('login').append(retry);}}}
async function api(path,options={}){const controller=new AbortController();const timeout=setTimeout(()=>controller.abort(),12000);try{const r=await fetch(path,{credentials:'same-origin',cache:'no-store',...options,signal:controller.signal});let d={};try{d=await r.json();}catch{}if(!r.ok){if((r.status===401||(r.status===403&&String(d.detail||'').startsWith('VIP access')))&&path!=='/v1/member/session')lock(d.detail||'Open a fresh /vip link from Discord.');throw Error(typeof d.detail==='string'?d.detail:'Research is temporarily unavailable.');}if(d.server_time){serverAnchor=Date.parse(d.server_time);monoAnchor=performance.now();wallAnchor=Date.now();}return d;}catch(e){if(e.name==='AbortError')throw Error('The app is taking too long to respond. Check your connection and try again.');throw e;}finally{clearTimeout(timeout);}}
const get=(path)=>api('/v1/vip/'+path+(path.includes('?')?'&':'?')+'slate_date='+activeSlateDate());
const send=(path,body,method='POST')=>api('/v1/vip/'+path,{method,headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
function link(text,href,cls='button'){const n=node('a',text,cls);n.href=href.startsWith('/v1/vip/')?href+(href.includes('?')?'&':'?')+'slate_date='+activeSlateDate():href;return n;}
function badge(text){return node('span',text,'badge '+(/BET NOW|HEALTHY|ACTIVE|PRODUCTION_APPROVED/.test(text)?'good':/QUARANTINED|UNAVAILABLE|INVALIDATED/.test(text)?'bad':/WATCH|STALE|PRICE CHECK|LIMITED/.test(text)?'warn':''));}
function empty(title,body){const n=node('div',undefined,'empty');n.append(node('strong',title),node('p',body));return n;}
function section(title,href,text='View all →'){const n=node('div',undefined,'section');n.append(node('h2',title));if(href)n.append(link(text,href,''));return n;}
function metrics(values){const n=node('div',undefined,'metrics');for(const [label,v]of values){const d=node('div');d.append(node('small',label),node('strong',v));n.append(d);}return n;}
function card(r){const n=link('', '#detail='+encodeURIComponent(r.id),'opportunity');const top=node('div',undefined,'top');const state=r.historical?'HISTORICAL':['QUARANTINED','INVALIDATED'].includes(r.status)?r.status:live(r)?r.status:'PRICE CHECK';top.append(node('span',r.sport+' · '+String(r.market||'').replaceAll('_',' '),'eyebrow'),badge(state));n.append(top,node('h3',[r.player||r.selection,r.line??''].join(' ')),node('div',r.event,'sub'),node('div',[odds(r.decimal),r.book||'No price',when(r.price_at)].join(' · '),'sub'));n.append(metrics([['Model',pct(r.model_probability)],['No-vig market',pct(r.market_probability)],['Edge',Number.isFinite(r.edge)?(r.edge*100).toFixed(1)+' pp':'—']]));if(r.why)n.append(node('p',r.why,'muted'));if(!live(r))n.append(node('small',r.historical?'Original snapshot price. Not current.':'Observed price is not verified current.'));return n;}
function cards(rows,root,none='No supported opportunities here yet.'){if(!rows.length){root.append(empty(none,'An empty board is valid. Model and data standards stay unchanged.'));return;}for(const r of rows)root.append(card(r));}
function gridLinks(root,items){const g=node('div',undefined,'grid');for(const [title,body,href]of items){const p=link('',href,'panel');p.append(node('h3',title),node('p',body,'muted'));g.append(p);}root.append(g);}
function field(label,type,value){const l=node('label',label);const i=node('input');i.type=type;i.value=value??'';l.append(i);return[l,i];}
function select(label,values,value=''){const l=node('label',label),i=node('select');for(const [v,t]of values){const o=node('option',t);o.value=v;i.append(o);}i.value=value;l.append(i);return[l,i];}
function page(title){$('title').textContent=title;$('content').replaceChildren();say('');}
function sportConfig(sport){
  return {
    MLB:{label:'MLB',subtitle:'Game lines, pitcher markets, batter markets and home-run research.',topKind:'hr',topLabel:'MLB Home Run Top 10',markets:[['Board',''],['Moneylines','h2h'],['Run lines','spreads'],['Totals','totals'],['F5','first_5_innings'],['Team totals','team_totals'],['Pitcher Ks','pitcher_strikeouts'],['Pitcher outs','pitcher_outs'],['Home runs','batter_home_runs']]},
    NFL:{label:'NFL',subtitle:'Game lines, player props, alternates and anytime-touchdown research.',topKind:'td',topLabel:'NFL Anytime TD Top 10',markets:[['Board',''],['Moneylines','h2h'],['Spreads','spreads'],['Totals','totals'],['Team totals','team_totals'],['Anytime TD','player_anytime_td'],['Pass yards','player_pass_yds'],['Rush yards','player_rush_yds'],['Receiving','player_reception_yds'],['Receptions','player_receptions']]},
    CFB:{label:'CFB',subtitle:'Louisiana-safe game markets: moneylines, spreads, totals and team derivatives.',topKind:null,topLabel:null,markets:[['Board',''],['Moneylines','h2h'],['Spreads','spreads'],['Totals','totals'],['Team totals','team_totals'],['Alternate spreads','alternate_spreads'],['Alternate totals','alternate_totals']]},
    NBA:{label:'NBA',subtitle:'Game markets and validated player-prop research, separated by market family.',topKind:'nba_props',topLabel:'NBA Props Top 10',markets:[['Board',''],['Moneylines','h2h'],['Spreads','spreads'],['Totals','totals'],['Team totals','team_totals'],['Points','player_points'],['Rebounds','player_rebounds'],['Assists','player_assists'],['Threes','player_threes'],['PRA','player_points_rebounds_assists']]},
    NHL:{label:'NHL',subtitle:'Game lines, goalie context, shots and validated goal-scorer research.',topKind:'nhl_goals',topLabel:'NHL Goal Scorer Top 10',markets:[['Board',''],['Moneylines','h2h'],['Puck lines','spreads'],['Totals','totals'],['Team totals','team_totals'],['Shots','player_shots_on_goal'],['Goals','player_goals']]}
  }[sport]||null;
}
function setSportbar(route,arg){
  for(const a of $('sportbar').querySelectorAll('a')){
    const active=(route==='home'&&a.dataset.sport==='HOME')||(route==='sport'&&a.dataset.sport===arg);
    a.setAttribute('aria-current',active?'page':'false');
  }
}
function rankingCards(rows,root,message){
  if(!rows.length){root.append(empty('No supported entries',message));return;}
  for(const r of rows){const panel=node('article',undefined,'panel');
    panel.append(badge(r.evidence_label),node('h3',[r.player||r.selection,r.line??'',r.player?r.selection:''].join(' ')),node('p',r.event+' · '+when(r.starts_at),'muted'));
    panel.append(metrics([['Model probability',pct(r.model_probability)],['Market no-vig',pct(r.market_probability)],['Observed price',odds(r.decimal)]]));
    panel.append(node('p',(r.book||'Book unavailable')+' · Price observed '+when(r.price_at),'muted'),node('p',r.why||'Research only.','muted'));
    if(r.model_probability!==null)panel.append(node('p','Model: '+r.model_version+' · '+r.model_stage,'muted'));
    panel.append(link('Open game','#matchup='+encodeURIComponent(r.sport)+'|'+encodeURIComponent(r.event_id)));
    root.append(panel);
  }
}
async function render(){if(!me)return;renderedDate=slateKey();if(!navigator.onLine){$('content').replaceChildren();$('offline').hidden=false;return;}$('offline').hidden=true;const n=++serial;const raw=location.hash.slice(1)||'home';const parts=raw.split('&'),first=parts.shift(),params=new URLSearchParams(parts.join('&'));const [route,arg]=first.split('=');for(const a of $('navigation').querySelectorAll('a'))a.setAttribute('aria-current',a.hash==='#'+route?'page':'false');setSportbar(route,arg);page(({home:'Today’s board',sport:(arg||'Sport')+' research',sports:'Sports',board:'Research board',sheets:'Daily cheat sheets',top10:'Today’s rankings',rankings:'Today’s rankings',search:'Find your research',detail:'Research detail',watchlist:'Your watchlist',performance:'The honest record',models:'Model center',ask:'Ask JABBAZI',changes:'What changed since 9 AM?',more:'Your terminal',settings:'My board & preferences',admin:'Operations',promo:'Boost research',academy:'JABBAZI Academy',picks:'Official JABBAZI picks',archive:'Historical sheets',matchups:'Matchup center',matchup:'Game breakdown',sim:'Game simulator',firsttd:'First touchdown research',props:'Player props',simdetail:'Game simulation',firsttddetail:'First touchdown board',playoftheday:'Play of the Day'})[route]||'Research');$('content').append(node('div',undefined,'loading'));$('refresh').disabled=true;
try{let build;
if(route==='home'||route==='sports'){const d=await get('home');build=root=>{if(route==='home'){const hero=node('article',undefined,'panel hero');hero.append(node('span','JABBAZI VIP RESEARCH','eyebrow'),node('h2',d.load_strategy==='on_demand'?'Your VIP terminal is ready':d.top_play?'Today’s top play':'No top play yet'),node('p',d.notice,'muted'),badge(d.state));root.append(hero);gridLinks(root,[['Daily cheat sheet','Open today’s frozen game sheets when available.','#sheets'],['Official Main Card','View issued JABBAZI positions.','#picks'],['Play of the Day','One official selection only when qualified.','#playoftheday'],['Research board','Browse current market evidence on demand.','#board'],['Matchup center','Game-by-game market and model evidence.','#matchups'],['Game Sim','Joint score simulations when a validated event model is connected.','#sim'],['First TD','Dedicated first-touchdown research, separate from anytime TD.','#firsttd'],['Player Props','Exact player lines and model status.','#props'],['Today’s rankings','Likely winners, scoring candidates and supported value, with evidence labels.','#top10'],['Today’s recap','Official ledger results, including losses and unsettled positions.','#performance'],['What changed?','Compare the morning baseline with later market observations.','#changes']]);if(d.load_strategy!=='on_demand'){root.append(section('Official Main Card','#picks'));cards(d.official,root,'No current official recommendations.');root.append(section('Research to explore','#board'));cards(d.research,root,'No fresh research available.');}}else{const items=d.sports.map(s=>[s.sport,s.events===null?'Open today’s research and model status':s.status+' · '+s.events+' observed events · '+s.fresh_rows+' fresh rows','#board&sport='+s.sport]);gridLinks(root,items);root.append(node('p','Active means an observed upcoming slate with fresh research. It does not mean the model is production-approved.','muted'));}if(d.snapshot_at)root.append(node('p','Latest snapshot: '+when(d.snapshot_at),'muted'));};}
else if(route==='sport'){
  const cfg=sportConfig((arg||'').toUpperCase());
  if(!cfg){build=root=>root.append(empty('Sport unavailable','This sport workspace is not configured.'));}else{
    const results=await Promise.allSettled([
      get('board?'+new URLSearchParams({sport:cfg.label,sort:'edge',offset:'0'})),
      get('rankings?sport='+cfg.label),
      get('models'),
      get('slate?sport='+cfg.label)
    ]);
    const defaults=[{rows:[]},{moneyline_likely:[],anytime_td:[],notice:''},{models:[]},{games:[]}];
    const [boardData,topData,modelData,slateData]=results.map((r,i)=>r.status==='fulfilled'?r.value:defaults[i]);
    build=root=>{
      results.forEach((r,i)=>{if(r.status==='rejected')root.append(empty(['Research board','Player rankings','Model evidence','Game schedule'][i]+' could not load',r.reason.message));});
      const model=modelData.models.find(m=>m.sport===cfg.label)||{};
      const hero=node('article',undefined,'panel workspace-hero');
      hero.append(node('span','JABBAZI · '+cfg.label+' MODEL WORKSPACE','eyebrow'),node('h2',cfg.label+' Research Terminal','workspace-title'),node('p',cfg.subtitle,'muted'));
      const k=node('div',undefined,'workspace-kpis');
      const fresh=boardData.rows.filter(r=>r.fresh).length;
      const prod=(model.market_buckets?Object.values(model.market_buckets).filter(x=>x.stage==='PRODUCTION_APPROVED').length:0)+(model.player_market_buckets?Object.values(model.player_market_buckets).filter(x=>x.stage==='PRODUCTION_APPROVED').length:0);
      for(const [a,b]of[['Fresh rows',String(fresh)],['Model status',model.status||'UNAVAILABLE'],['Approved families',String(prod)]]){const d=node('div');d.append(node('small',a),node('strong',b));k.append(d);}
      hero.append(k);root.append(hero);
      const games=node('div',undefined,'market-strip');games.append(link('ALL GAMES','#board&sport='+cfg.label,''));for(const game of slateData.games.slice(0,20))games.append(link(game.event,'#matchup='+cfg.label+'|'+encodeURIComponent(game.event_id),''));root.append(games);
      const strip=node('div',undefined,'market-strip');
      for(const [label,market]of cfg.markets)strip.append(link(label,'#board&sport='+cfg.label+(market?'&market='+encodeURIComponent(market):''),''));
      strip.append(link('Cheat sheet','#sheets&sport='+cfg.label,''));
      root.append(strip);
      root.append(node('p','Slate: '+activeSlateDate()+' · America/Chicago · '+slateData.games.length+' eligible games.','muted'));
      if(!slateData.games.length)root.append(empty('No games today','This sport has no eligible upcoming games in the current feed. Future games are not substituted.'));
      root.append(section('Today’s most likely winners','#rankings&sport='+cfg.label));
      rankingCards(topData.moneyline_likely||[],root,'Fresh moneyline evidence is unavailable.');
      if(cfg.label==='NFL'){
        root.append(section('Anytime touchdown candidates','#rankings&sport=NFL'));
        rankingCards(topData.anytime_td||[],root,'No fresh anytime-touchdown model or market evidence is available today.');
      }
      root.append(link('All daily rankings and value comparisons','#rankings&sport='+cfg.label));
      root.append(node('p',topData.notice||'Research only. Read each evidence label.','muted'));
      root.append(section(cfg.label+' model board','#board&sport='+cfg.label,'Open full board →'));
      cards(boardData.rows.slice(0,8),root,'No fresh '+cfg.label+' research is available.');
      root.append(section('Model evidence','#models','Open Model Center →'));
      root.append(node('p','Workspace outputs come from the same canonical backend used by the scanner and Discord. Model stage controls whether research can become actionable.','muted'));
    };
  }
}
else if(route==='matchups'||route==='sim'||route==='firsttd'||route==='props'){
  const sport=route==='firsttd'?'NFL':(params.get('sport')||'');
  if(route==='props'){
    const offset=Number(params.get('offset')||0),event_id=params.get('event_id')||'';
    const d=await get('board?'+new URLSearchParams({sport,event_id,family:'props',offset:String(offset)}));
    build=root=>{root.append(node('p','Player props are research only. Probabilities are displayed only when an independent model and the exact line are supported.','muted'));
      const rows=d.rows;
      cards(rows,root,d.reason||'No supported player-prop rows are available in the current snapshot.');
      root.append(node('p','Last research update: '+when(d.snapshot_at),'muted'));
      if(offset>0)root.append(link('Previous props','#props&sport='+sport+'&event_id='+encodeURIComponent(event_id)+'&offset='+Math.max(0,offset-50)));
      if(d.next!==null)root.append(link('More props','#props&sport='+sport+'&event_id='+encodeURIComponent(event_id)+'&offset='+d.next));
      root.append(node('small',d.total+' eligible prop rows today'));
    };
  }else{
    const d=await get('matchups?'+new URLSearchParams({sport}));
    build=root=>{
      const headline=route==='sim'?'GAME SIMULATOR':route==='firsttd'?'FIRST TOUCHDOWN LAB':'MATCHUP CENTER';
      root.append(node('h2',headline),node('p',route==='sim'?'Validated event-specific score distributions only. No invented scores or Monte Carlo outputs.':route==='firsttd'?'A dedicated first touchdown model is required; anytime TD is not a substitute.':d.notice,'muted'));
      const filters=node('div',undefined,'pills');
      for(const s of ['','NFL','CFB','NBA','MLB','NHL'])filters.append(link(s||'ALL','#'+route+(s?'&sport='+s:''),s===sport?'selected':''));
      root.append(filters);
      if(!d.games.length)root.append(empty('No current games available','The research feed has no eligible upcoming games for this view.'));
      for(const g of d.games){
        const href=(route==='sim'?'#simdetail=':route==='firsttd'?'#firsttddetail=':'#matchup=')+encodeURIComponent(g.sport)+'|'+encodeURIComponent(g.event_id);
        const p=link('',href,'panel opportunity');
        p.append(node('span',g.sport+' · '+when(g.starts_at),'eyebrow'),node('h3',g.event||g.event_id),badge(g.state),node('p',g.markets.join(' · '),'muted'));
        p.append(node('small',g.fresh_rows+' fresh market rows · '+g.model_supported_rows+' model-supported rows'));
        root.append(p);
      }
    };
  }
}
else if(route==='simdetail'||route==='firsttddetail'){
  const [sport,eventId]=(arg||'').split('|').map(decodeURIComponent);
  if(!sport||!eventId)throw Error('Select a game from the matchup list.');
  const scenario=new URLSearchParams();
  for(const key of ['spread_line','total_line'])if(params.has(key))scenario.set(key,params.get(key));
  const d=await get(route==='simdetail'?'sim/'+encodeURIComponent(sport)+'/'+encodeURIComponent(eventId)+'?'+scenario:'firsttd/'+encodeURIComponent(eventId));
  build=root=>{
    root.append(node('h2',d.event||'Game research'),badge(d.state),node('p',d.reason||d.notice||'','muted'));
    if(d.state==='SHADOW_ONLY'&&d.summary){
      const form=node('form',undefined,'filters');
      const [sl,spread]=field('Home spread (scenario)','number',params.get('spread_line')||'');
      const [tl,total]=field('Game total (scenario)','number',params.get('total_line')||'');
      spread.step=total.step='0.5';spread.min='-300';spread.max='300';total.min='0';total.max='500';
      const calculate=node('button','Evaluate lines','button');calculate.type='submit';
      form.append(sl,tl,calculate);
      form.addEventListener('submit',e=>{e.preventDefault();const q=new URLSearchParams();if(spread.value!=='')q.set('spread_line',spread.value);if(total.value!=='')q.set('total_line',total.value);location.hash='simdetail='+encodeURIComponent(sport)+'|'+encodeURIComponent(eventId)+'&'+q;});
      root.append(form,node('p','Scenario lines are your inputs, not quoted sportsbook prices.','muted'));
      root.append(metrics([['Projected '+d.home,Number(d.summary.expected_home_points).toFixed(1)],['Projected '+d.away,Number(d.summary.expected_away_points).toFixed(1)],['Total mean',Number(d.summary.expected_total).toFixed(1)],[d.summary.count_label||'Simulated score scenarios',String(d.summary.sample_count)]]));
      if(d.settlement)root.append(node('p','Score convention: '+d.settlement.replaceAll('_',' ')+'. Book-specific settlement has not been verified.','muted'));
      root.append(metrics([['Home win',pct(d.home_win.win)],['Away win',pct(d.away_win.win)],['Tie',pct(d.home_win.push)]]));
      if(d.spread)root.append(metrics([['Home '+d.spread.home_line+' cover',pct(d.spread.win)],['Spread push',pct(d.spread.push)],['Spread loss',pct(d.spread.loss)]]));
      if(d.total)root.append(metrics([['Over '+d.total.line,pct(d.total.win)],['Total push',pct(d.total.push)],['Under '+d.total.line,pct(d.total.loss)]]));
      root.append(metrics([['Margin: 90% scenario interval',d.summary.margin_predictive_interval_90.join(' to ')],['Total: 90% scenario interval',d.summary.total_predictive_interval_90.join(' to ')]]));
      const chart=node('div',undefined,'simulation-chart'),bar=node('div',undefined,'simulation-bar');
      const homeBar=node('span',undefined,'simulation-home'),awayBar=node('span',undefined,'simulation-away');
      const homePct=Math.max(0,Math.min(100,Number(d.home_win.win)*100));
      const awayPct=Math.max(0,Math.min(100,Number(d.away_win.win)*100));
      homeBar.style.width=homePct+'%';awayBar.style.width=awayPct+'%';
      bar.append(homeBar,awayBar);
      chart.append(node('p',d.home+' '+homePct.toFixed(1)+'%  ·  '+d.away+' '+awayPct.toFixed(1)+'%','muted'),bar);
      root.append(chart);
      root.append(node('p','Model: '+d.model_version+' · '+(d.summary.count_label||'paired score samples')+', research only. Not approved for betting.','muted'));
      root.append(node('p','Inputs observed: '+when(d.input_observed_at)+' · '+(d.scenario_basis||''),'muted'));
      for(const [kind,label] of [['margin','Home margin distribution'],['total','Total score distribution']]){
        if(!d.histograms?.[kind])continue;
        root.append(section(label));const table=node('table',undefined,'distribution-table');const caption=node('caption','Probability mass across model score outcomes');table.append(caption);
        for(const bin of d.histograms[kind]){const tr=node('tr'),range=bin.low===bin.high?String(bin.low):bin.low+' to '+bin.high;const bar=node('progress');bar.max=1;bar.value=bin.probability;bar.setAttribute('aria-label',range+': '+pct(bin.probability));const cell=node('td');cell.append(bar);tr.append(node('th',range),cell,node('td',pct(bin.probability)));table.append(tr);}root.append(table);
      }
      const exportSim=link('Download simulation graphic','/v1/vip/graphic/'+encodeURIComponent(sport)+'/'+encodeURIComponent(eventId)+'?kind=simulation');exportSim.download='JABBAZI-simulation.png';root.append(exportSim);
    }else if(d.players&&d.players.length){
      for(const player of d.players){const p=node('article',undefined,'panel');p.append(node('h3',player.name),node('p',pct(player.probability)));root.append(p);}
    }else root.append(empty('Verified projections unavailable',d.reason||'This market requires validated event-specific inputs.'));
    root.append(link('Back to matchups','#matchups'));
  };
}
else if(route==='matchup'){
  const [sport,eventId]=(arg||'').split('|').map(decodeURIComponent);
  if(!sport||!eventId)throw Error('Choose a matchup from the Matchup Center.');
  const d=await get('matchup/'+encodeURIComponent(sport)+'/'+encodeURIComponent(eventId));
  build=root=>{
    root.append(node('span',d.sport+' · '+when(d.starts_at),'eyebrow'),node('h2',d.event||'Matchup'),badge(d.projection.source));
    if(d.projection.model_version)root.append(badge(d.projection.model_stage),node('p','Model: '+d.projection.model_version,'muted'));
    root.append(metrics([['Projected winner',d.projection.selection||'Unavailable'],['Independent model',pct(d.projection.model_probability)],['Market no-vig',pct(d.projection.market_no_vig_probability)],['Observed markets',String(d.markets.length)]]));
    if(d.pick_explanation){const why=node('article',undefined,'panel');why.append(node('h3',d.projection.selection?'Why this pick':'Why no pick yet'),node('p',d.pick_explanation.reason),node('p',d.pick_explanation.caution,'muted'));if(d.pick_explanation.observed_at)why.append(node('p','Evidence observed: '+when(d.pick_explanation.observed_at),'muted'));root.append(why);}
    root.append(node('p','Projected winner is not an official wager. Research snapshot: '+when(d.snapshot_at),'muted'));
    const exportMatchup=link('Download matchup graphic','/v1/vip/graphic/'+encodeURIComponent(sport)+'/'+encodeURIComponent(eventId));exportMatchup.download='JABBAZI-matchup.png';root.append(exportMatchup);
    gridLinks(root,[['Today’s rankings','Winner, touchdown and prop research for this matchup.','#rankings&sport='+sport+'&event_id='+encodeURIComponent(eventId)],['Game Sim','Open the current model distribution and input status.','#simdetail='+encodeURIComponent(sport)+'|'+encodeURIComponent(eventId)],['First TD',d.first_td.reason,'#firsttddetail='+encodeURIComponent(sport)+'|'+encodeURIComponent(eventId)],['Player Props','View player research for this game.','#props&sport='+sport+'&event_id='+encodeURIComponent(eventId)]]);
    root.append(section('Injuries and lineups'),node('p',d.lineup_notice||'Verified lineup context is unavailable.','muted'));
    if(d.cheatsheet_available){const sheet=link('Download this game’s cheat sheet','/v1/vip/graphic/'+encodeURIComponent(sport)+'/'+encodeURIComponent(eventId)+'?kind=cheatsheet');sheet.download='JABBAZI-cheatsheet.png';root.append(sheet);}
    root.append(section('Issued official picks'));cards(d.official||[],root,'No current issued official picks for this game.');
    if(d.research_evidence?.length){root.append(section('Reviewed sources'));for(const e of d.research_evidence)root.append(link(e.source,e.source_url),node('p','Retrieved '+when(e.retrieved_at),'muted'));}
    root.append(section('Observed matchup markets'));
    cards(d.research,root,'No research rows for this game.');
  };
}
else if(route==='board'||route==='search'){const sport=params.get('sport')||'',q=params.get('q')||'',market=params.get('market')||'',status=params.get('status')||'',sort=params.get('sort')||'edge';const d=await get((route==='search'?'search?':'board?')+new URLSearchParams({sport,q,market,status,sort,offset:params.get('offset')||'0'}));build=root=>{const f=node('form',undefined,'filters');const[l,input]=field('Search team, player, market or book','search',q);l.className='wide';input.placeholder='Judge HR, KC, NFL totals…';const[sl,si]=select('Sport',[['','All sports'],...['MLB','NFL','CFB','NBA','NHL','WNBA','TENNIS','SOCCER'].map(x=>[x,x])],sport);const[st,sti]=select('State',[['','All states'],['WATCH','Watch'],['PASS','Pass'],['PRICE CHECK','Price check'],['QUARANTINED','Quarantined']],status);const[so,soi]=select('Sort',[['edge','Model / market edge'],['time','Game time'],['model','Model probability']],sort);f.append(l,sl,st,so);let timer;input.addEventListener('input',()=>{clearTimeout(timer);timer=setTimeout(apply,400);});function apply(){location.hash=route+'&'+new URLSearchParams({q:input.value,sport:si.value,status:sti.value,sort:soi.value});}for(const e of[si,sti,soi])e.addEventListener('change',apply);f.addEventListener('submit',e=>{e.preventDefault();apply();});root.append(f);if(d.navigation){const nav=node('div',undefined,'pills');for(const item of d.navigation)nav.append(link(item.label,item.href,''));root.append(nav);}if(sport){const pills=node('div',undefined,'pills');for(const[label,href]of[['Morning sheet','#sheets&sport='+sport],['Moneylines','#board&sport='+sport+'&market=h2h'],['All markets','#board&sport='+sport]])pills.append(link(label,href,''));root.append(pills);}root.append(node('p',`${d.total} matching research rows · ${d.state} · ${when(d.snapshot_at)}`,'muted'));cards(d.rows,root,'No research matches this search.');if(d.next!==null&&d.next!==undefined)root.append(link('Next 50 →','#'+route+'&'+new URLSearchParams({sport,q,market,status,sort,offset:d.next})));};}
else if(route==='sheets'){const d=await get('sheets?'+params);build=root=>{const filters=node('div',undefined,'filters');const[l,i]=field('Archive date','date',d.date);i.addEventListener('change',()=>{location.hash='sheets&day='+i.value;});filters.append(l,link('Browse archive','#archive'));root.append(filters,node('p',d.state==='FROZEN'?`9 AM INITIAL · frozen ${when(d.generated_at)} · original prices retained`:d.notice,'muted'));if(d.rows.length){if(d.date===activeSlateDate()){const download=link('Download complete daily slate','/v1/vip/slate.png');download.download='JABBAZI-daily-slate.png';root.append(download);}for(const r of d.rows){const c=card(r);c.href='#board&sport='+r.sport+'&q='+encodeURIComponent(r.event);root.append(c);}}else root.append(empty('Morning sheet not available',d.notice));};}
else if(route==='archive'){const d=await get('archive');build=root=>{if(!d.sheets.length)root.append(empty('No published sheets yet','Healthy frozen sheets will appear here automatically.'));for(const s of d.sheets)root.append(link(s.entity+' · Frozen original','#sheets&day='+s.entity,'linkrow'));};}
else if(route==='top10'||route==='rankings'){
  const sport=params.get('sport')||({td:'NFL',hr:'MLB',nba_props:'NBA',nhl_goals:'NHL'}[params.get('kind')]||'NFL');
  const d=await get('rankings?'+new URLSearchParams({sport,event_id:params.get('event_id')||''}));
  build=root=>{const nav=node('div',undefined,'pills');for(const name of ['NFL','CFB','NBA','MLB','NHL'])nav.append(link(name,'#rankings&sport='+name,name===sport?'selected':''));root.append(nav,node('h2',sport+(activeSlateDate()===chicagoDate()?' · Today’s research rankings':' · Next-day research rankings')),node('p',d.date+' · America/Chicago · '+d.game_count+' games · Snapshot '+when(d.snapshot_at),'muted'),node('p',d.notice,'muted'));
    for(const [key,title] of [['moneyline_likely','Most likely moneyline winners'],['moneyline_value','Moneyline value supported by approved models'],...(sport==='NFL'?[['anytime_td','Most likely anytime touchdown scorers'],['anytime_td_value','Anytime touchdown value'],['receiving_overs','Receiving overs at exact lines'],['receiving_unders','Receiving unders at exact lines'],['receiving_value','Receiving over/under value supported by approved models']]:[])]){root.append(section(title));rankingCards(d[key]||[],root,d.game_count?'No fresh, supported evidence qualifies for this list.':'No eligible upcoming games for this slate.');}
    if(sport==='NFL')root.append(node('p',d.receiving_totals_reason,'muted'));
    if(sport!=='NFL')for(const [market,rows] of Object.entries(d.player_markets||{})){root.append(section('Player research · '+market.replaceAll('_',' ')));rankingCards(rows,root,'No supported entries.');}
    root.append(section('Reviewed web research'),node('p',d.web_research_notice,'muted'));
    for(const e of d.web_leans||[]){const p=node('article',undefined,'panel');p.append(badge(e.evidence_label),node('h3',e.selection),node('p',e.event),link(e.source,e.source_url),node('p','Published '+when(e.published_at)+' · Retrieved '+when(e.retrieved_at),'muted'));root.append(p);}
    if((d.conflicting_events||[]).length)root.append(node('p','Some reviewed sources disagree; those selections are withheld.','muted'));
    root.append(node('p','Stale rows excluded: '+d.stale_rows,'muted'));
  };
}
else if(route==='detail'){const d=await get('detail/'+encodeURIComponent(arg));build=root=>{const r=d.row;root.append(card(r));const actions=node('div',undefined,'panel'),[l,i]=field('Alert when decimal odds reach (optional)','number','');i.step='.01';i.min='1.01';const save=node('button','☆ Add to watchlist','primary');save.addEventListener('click',async()=>{save.disabled=true;try{await send('watchlist',{candidate_id:r.id,minimum_decimal:i.value?Number(i.value):null});say('Added to your private watchlist. Alerts appear in your in-app inbox.');}catch(e){say(e.message);}save.disabled=false;});actions.append(l,save);root.append(actions);const details=node('dl',undefined,'detail-list');for(const[k,v]of[['Status',live(r)?r.status:'PRICE CHECK'],['Price observed',when(r.price_at)],['Model updated',when(r.model_at)],['Injury source',r.injury_at?when(r.injury_at):'Not sourced'],['Lineup / starter',r.lineup_at?when(r.lineup_at):'Not sourced'],['Weather',r.weather_at?when(r.weather_at):'Not sourced'],['Start time',when(r.starts_at)],['Fair price',odds(r.fair_decimal)],['Maximum playable price',odds(r.play_to_decimal)],['Estimated research EV',pct(r.ev)],['Calibrated probability',pct(r.calibrated_probability)],['No-vig market',pct(r.market_probability)],['Model version',r.model_version||'Unavailable'],['Model stage',r.model_stage],['Uncertainty',pct(r.uncertainty)+' · '+r.uncertainty_kind],['Data health',r.data_health],['Snapshot ID',r.snapshot_id]]){const div=node('div');div.append(node('dt',k),node('dd',v));details.append(div);}const panel=node('article',undefined,'panel');panel.append(node('h2','Behind the research'),node('p',r.why),details);if((r.key_factors||[]).length){panel.append(node('h3','Key factors'));for(const factor of r.key_factors)panel.append(node('p',factor,'muted'));}for(const risk of r.risks)panel.append(node('p',risk,'muted'));root.append(panel);if(r.other_prices.length){root.append(section('Observed sportsbook prices'));for(const b of r.other_prices)root.append(node('p',b.book+' · '+odds(b.decimal)+' · same snapshot timestamp'));}if(d.alternates.length){root.append(section('Alternate expressions'));cards(d.alternates,root);}root.append(section('Game center'));cards(d.related,root,'No other supported markets for this event.');};}
else if(route==='watchlist'){const d=await get('watchlist');build=root=>{root.append(node('p',d.delivery,'muted'));if(!d.items.length)root.append(empty('Your board, your interests','Open any research opportunity and select Add to watchlist.'));for(const w of d.items){const p=node('div',undefined,'panel');if(w.current)p.append(card(w.current));else p.append(node('h3',w.event),badge('UNAVAILABLE'),node('p',w.selection));if(w.threshold)p.append(node('p','Your price target: '+odds(w.threshold)));const remove=node('button','Remove');remove.addEventListener('click',async()=>{try{await api('/v1/vip/watchlist/'+w.id,{method:'DELETE'});render();}catch(e){say(e.message);}});p.append(remove);root.append(p);}root.append(section('Your alert inbox'));for(const a of d.alerts){const p=node('article',undefined,'panel');p.append(badge(a.state),node('h3',a.event),node('p',a.selection+' · '+a.before+' → '+a.state),node('small',when(a.at)+' · '+a.notice));root.append(p);}if(!d.alerts.length)root.append(node('p','No watchlist changes to report.','muted'));};}
else if(route==='playoftheday'){
  const d=await get('playoftheday');
  build=root=>{
    root.append(node('h2','JABBAZI PLAY OF THE DAY'),badge(d.state),node('p',d.notice,'muted'));
    if(d.play){root.append(card(d.play));const a=link('Download Play of the Day graphic','/v1/vip/pick-graphic/'+encodeURIComponent(d.play.id)+'?kind=playoftheday');a.download='JABBAZI-play-of-the-day.png';root.append(a);}
    else root.append(empty('No Play of the Day', 'No qualifying official position has been issued. PASS is a valid result.'));
  };
}
else if(route==='picks'){const d=await get('picks');build=root=>{root.append(node('p',d.notice,'muted'));cards(d.rows,root,'No wagers currently meet the official publication gates.');for(const r of d.rows.filter(r=>r.graphic_available)){const a=link('Download official graphic: '+r.selection,'/v1/vip/pick-graphic/'+encodeURIComponent(r.id));a.download='JABBAZI-official-pick.png';root.append(a);}};}
else if(route==='performance'){const d=await get('performance');build=root=>{root.append(node('p',d.provenance+' · '+d.notice,'muted'));for(const period of d.periods){const p=node('article',undefined,'panel');p.append(node('h2',period.label),node('small',period.from+' through '+period.through));if(period.groups.some(g=>g.settled>0)){const download=link('Download performance graphic','/v1/vip/performance-graphic?period='+encodeURIComponent(period.label));download.download='JABBAZI-performance.png';p.append(download);}for(const g of period.groups){p.append(node('h3',g.kind),metrics([['Record',g.wins+'–'+g.losses],['Net units',Number(g.profit_units).toFixed(2)+'u'],['ROI',g.roi===null?'—':pct(Number(g.roi))]]),node('p',g.pushes_or_voids+' pushes/voids · '+g.settled+' settled','muted'),node('p',(g.unsettled??0)+' unsettled · stake '+Number(g.unsettled_stake||0).toFixed(2)+' · excluded from settled ROI','muted'),node('p','Settled stake '+Number(g.settled_stake||0).toFixed(2)+' · returns '+Number(g.settled_returns||0).toFixed(2)+' · net '+Number(g.profit||0).toFixed(2),'muted'));}root.append(p);}root.append(node('p',d.clv_notice,'muted'));};}
else if(route==='ask'){build=root=>{const panel=node('article',undefined,'panel'),[label,input]=field('Ask about the current JABBAZI board','search',params.get('q')||'');input.placeholder='Show NFL touchdown candidates';const button=node('button','Ask JABBAZI','primary'),results=node('div');async function run(){if(input.value.trim().length<2)return;button.disabled=true;try{const d=await get('ask?'+new URLSearchParams({q:input.value.trim()}));results.replaceChildren(node('p',d.answer,'muted'));cards(d.rows,results,'No current evidence matches that question.');results.append(node('p',d.notice,'muted'));}catch(e){say(e.message);}button.disabled=false;}button.addEventListener('click',run);input.addEventListener('keydown',e=>{if(e.key==='Enter'){e.preventDefault();run();}});panel.append(label,button,results);root.append(panel);};}
else if(route==='models'){const d=await get('models');build=root=>{root.append(node('p',d.notice,'muted'));if(!d.models.length){root.append(empty('Model status is refreshing','The model registry is checked in the background; unverified model stages will not be displayed.'));const retry=node('button','Check model status again','button');retry.addEventListener('click',render);root.append(retry);}for(const m of d.models){const p=node('article',undefined,'panel');p.append(node('h3',m.sport),badge(m.status||'UNAVAILABLE'),node('p','Game model: '+(m.version||'Unavailable')),node('p','Markets: '+(m.supported_markets||[]).join(', '),'muted'),node('p','Player models: '+m.player_status,'muted'),node('small','Refreshed: '+when(m.state_refreshed_at)));const buckets=Object.entries(m.player_market_buckets||{});for(const[market,stats]of buckets){const details=node('details');details.append(node('summary',market.replaceAll('_',' ')+' · '+stats.stage),node('p','Validation samples: '+stats.test_sample_count+' · prospective: '+stats.prospective_sample_count,'muted'),node('p','Brier: '+(stats.brier??'Unavailable')+' · calibration error: '+(stats.ece??'Unavailable'),'muted'));p.append(details);}root.append(p);}if(d.has_errors)say('Some model metadata is unavailable.');};}
else if(route==='changes'){const d=await get('changes');build=root=>{root.append(node('p',d.notice,'muted'));if(!d.rows.length)root.append(empty('No verified changes to show','The comparison needs a published morning baseline and a later saved snapshot.'));for(const r of d.rows){const p=link('','#detail='+r.id,'panel opportunity');p.append(node('h3',r.event),node('p',r.selection),metrics([['Morning price',odds(r.before_price)],['Later price',odds(r.price)],['Model now',pct(r.model)]]),node('small',when(r.price_at)+(r.fresh?'':' · PRICE CHECK')));root.append(p);}};}
else if(route==='settings'){build=root=>{const p=node('section',undefined,'panel');const[ul,u]=field('Your unit size ($)','number',me.preferences.unit_size);u.min='.01';u.step='.01';const[bl,b]=field('Optional bankroll ($)','number',me.preferences.bankroll);b.min='.01';const[tl,t]=field('Favorite teams, separated by commas','text',(me.preferences.teams||[]).join(', '));const[kl,k]=field('Your sportsbooks, separated by commas','text',(me.preferences.books||[]).join(', '));p.append(ul,bl,tl,kl,node('h3','Favorite sports'));const sports=[];for(const s of['MLB','NFL','CFB','NBA','NHL','WNBA','TENNIS','SOCCER']){const l=node('label'),i=node('input');i.type='checkbox';i.checked=me.preferences.sports.includes(s);l.append(i,document.createTextNode(s));p.append(l);sports.push([s,i]);}const nl=node('label'),ni=node('input');ni.type='checkbox';ni.checked=me.preferences.notifications;nl.append(ni,document.createTextNode('Private in-app watchlist alerts'));const dl=node('label'),di=node('input');di.type='checkbox';di.checked=me.preferences.discord_dm===true;dl.append(di,document.createTextNode('Opt in to private Discord watchlist DMs (pregame only)'));const[ql,qs]=field('Quiet hours start (0–23, Chicago; blank disables)','number',me.preferences.quiet_start??'');const[el,qe]=field('Quiet hours end (0–23, Chicago)','number',me.preferences.quiet_end??'');qs.min=qe.min='0';qs.max=qe.max='23';const[cl,ci]=select('Watchlist DM category',[['both','Price and status changes'],['price','Price changes'],['status','Status changes']],(me.preferences.alert_categories||[]).length===1?me.preferences.alert_categories[0]:'both');p.append(dl,ql,el,cl,node('p','Favorite sports filter private DMs. Quiet-hour alerts expire instead of being replayed. Shared channel notifications remain controlled in Discord.','muted'));const save=node('button','Save preferences','primary');save.addEventListener('click',async()=>{try{const preferences={unit_size:Number(u.value),bankroll:b.value?Number(b.value):null,teams:t.value.split(',').map(v=>v.trim()).filter(Boolean),books:k.value.split(',').map(v=>v.trim()).filter(Boolean),sports:sports.filter(([,i])=>i.checked).map(([s])=>s),notifications:ni.checked,discord_dm:di.checked,quiet_start:qs.value===''?null:Number(qs.value),quiet_end:qe.value===''?null:Number(qe.value),alert_categories:ci.value==='both'?['price','status']:[ci.value]};await send('preferences',preferences,'PUT');me.preferences=preferences;say('Saved. Preferences change presentation, never model probabilities.');}catch(e){say(e.message);}});p.append(nl,save,node('p','Default reference: 1u = $30. Choose an amount you can afford. Bankroll storage is optional; live exposure tracking is not connected.','muted'));root.append(p);};}
else if(route==='admin'){const d=await get('admin');build=root=>{root.append(node('p',d.capability,'muted'));if(d.health){const h=d.health;root.append(section('Service health'),node('p',h.notice,'muted'),node('small','Checked: '+when(h.observed_at)));for(const [label,value] of [['API',h.api],['Database',h.database],['Discord worker heartbeat',h.worker],['Latest scan',h.scan],['Recorded owner authentication check',h.authentication_check]]){const p=node('article',undefined,'panel');p.append(node('h3',label),badge(value.state));if(value.observed_at)p.append(node('p','Observed: '+when(value.observed_at),'muted'));if(value.scope)p.append(node('p',value.scope,'muted'));if(value.commit)p.append(node('p','Deployed commit: '+value.commit,'muted'));if(value.last_successful_at)p.append(node('p','Last successful scan: '+when(value.last_successful_at),'muted'));if(value.error_count!==undefined)p.append(node('p','Recorded scan errors: '+(value.error_count??'Unavailable'),'muted'));if(value.pool&&Object.keys(value.pool).length)p.append(node('p','Process pool: '+Object.entries(value.pool).map(([k,v])=>k.replaceAll('_',' ')+': '+v).join(' · '),'muted'));root.append(p);}root.append(node('p','Not currently measured: '+h.unavailable_metrics.join('; '),'muted'));}root.append(section('Publishing controls'));for(const key of['pause_all','pause_mlb','pause_nfl','pause_cfb','pause_nba','pause_nhl']){const p=node('article',undefined,'panel');p.append(node('h3',key.replaceAll('_',' ')),badge(d.flags[key]?'PAUSED':'ENABLED'));const[l,i]=field('Reason for the change','text','');const b=node('button',d.flags[key]?'Resume publication':'Pause publication');b.addEventListener('click',async()=>{try{await send('admin/control',{key,value:!d.flags[key],reason:i.value});render();}catch(e){say(e.message);}});p.append(l,b);root.append(p);}root.append(section('Audit trail'));for(const a of d.audit)root.append(node('p',when(a.at)+' · '+a.key+' → '+a.after+' · '+a.reason,'muted'));};}
else if(route==='promo'){build=root=>{const p=node('article',undefined,'panel'),[ol,o]=field('Original decimal odds','number','2.00'),[bl,b]=field('Profit boost (%)','number','30'),[pl,prob]=field('Your assumed probability (0–1, optional)','number','');o.step=prob.step='.01';const run=node('button','Calculate boost','primary'),out=node('div');run.addEventListener('click',async()=>{try{const d=await send('promo',{decimal_odds:Number(o.value),boost_percent:Number(b.value),probability:prob.value?Number(prob.value):null});out.replaceChildren(metrics([['Boosted price',odds(d.boosted_decimal)],['Break-even',pct(d.break_even)],['Estimated EV',pct(d.boosted_ev)]]),node('p',d.notice,'muted'),node('p','Probability source: your assumption, not a JABBAZI forecast.','muted'));}catch(e){say(e.message);}});p.append(ol,bl,pl,run,out);root.append(p);};}
else if(route==='academy'){const lessons=await api('/v1/member/learn');build=root=>{for(const lesson of lessons){const d=node('details',undefined,'panel');d.append(node('summary',lesson.title),node('p',lesson.body));root.append(d);}};}
else {build=root=>{gridLinks(root,[['Cheat sheets','Frozen morning slate and history.','#sheets'],['Matchup Center','Research breakdowns for observed games.','#matchups'],['Game Sim','Validated joint-score distributions only.','#sim'],['First Touchdown','NFL first TD model status and research.','#firsttd'],['Player Props','Exact supported player lines.','#props'],['Top 10','Qualified player-model lists.','#top10'],['JABBAZI picks','Current official card.','#picks'],['Play of the Day','Never forced, official only.','#playoftheday'],['Performance','Authentic official ledger summaries.','#performance'],['Model center','Versions, stages and supported markets.','#models'],['Ask JABBAZI','Query the current canonical research board without invented probabilities.','#ask'],['What changed?','Morning versus later market observations.','#changes'],['My board','Sports, books, teams and your unit size.','#settings'],['Promo calculator','Evaluate a profit boost with explicit assumptions.','#promo'],['JABBAZI Academy','Understand EV, variance and price.','#academy'],...(me.features.admin?[['Operations','Audited publishing controls.','#admin']]:[])]);};}
if(n!==serial||!me)return;if(renderedDate!==slateKey()){render();return;}$('content').replaceChildren();build($('content'));slateControls($('content'));
if(route==='home'){
 const slot=node('section');$('content').prepend(slot);slot.append(node('p','Loading today’s games and recap…','muted'));
 get('today').then(d=>{
  if(n!==serial||!me)return;if(renderedDate!==slateKey()){render();return;}
  slot.replaceChildren(section('Slate '+activeSlateDate()+' · America/Chicago'),node('p','Research updated: '+when(d.snapshot_at),'muted'));
  if(d.reason)slot.append(node('p',d.reason,'muted'));
  const games=node('div',undefined,'pills');for(const g of d.games)games.append(link(g.event,'#matchup='+encodeURIComponent(g.sport)+'|'+encodeURIComponent(g.event_id),''));slot.append(games);
  if(!d.games.length)slot.append(node('p','No eligible upcoming games in the research snapshot.','muted'));
  slot.append(section('Issued official picks'));cards(d.official,slot,'No current issued official picks.');
  slot.append(section('Research leans — not official picks'));cards(d.research,slot,'No eligible research rows.');
  slot.append(section('Today’s ledger recap','#performance'));
  for(const g of d.recap.groups)slot.append(node('p',g.kind+': '+g.wins+' wins, '+g.losses+' losses · '+g.settled+' settled · '+(g.unsettled||0)+' unsettled · net '+Number(g.profit).toFixed(2),'muted'));
  slot.append(node('p','Owner-reported ledger; missing records do not imply zero bets. '+d.live_notice,'muted'));
 }).catch(e=>{if(n===serial&&me)slot.replaceChildren(empty('Today’s summary could not load',e.message));});
}

}catch(e){if(n===serial&&me){$('content').replaceChildren(empty('This view is unavailable',e.message));const retry=node('button','Retry this view','button');retry.addEventListener('click',render);$('content').append(retry);say(e.message);}}finally{if(n===serial)$('refresh').disabled=false;}}
$('refresh').addEventListener('click',render);
$('signout').addEventListener('click',async()=>{try{await api('/v1/member/logout',{method:'POST'});}finally{lock('Signed out.');}});
window.addEventListener('hashchange',render);
window.addEventListener('offline',()=>{$('offline').hidden=false;++serial;$('content').replaceChildren();});
window.addEventListener('online',render);
document.addEventListener('visibilitychange',()=>{if(!document.hidden&&me)render();});
setInterval(()=>{if(!me||document.hidden)return;if(Date.parse(me.expires_at)<=now()){lock('Session expired. Use /vip in Discord for a fresh private link.');return;}get('me').then(d=>{if(!me)return;me=d;$('access-badge').textContent=me.tier+' ACCESS';if(renderedDate!==slateKey()){++serial;$('content').replaceChildren();render();}}).catch(e=>{if(me)say(e.message);});},30000);
function accessView(value){return ['sim','firsttd','matchups','props','playoftheday'].includes(value)?value:'home';}
(async()=>{const hash=new URLSearchParams(location.hash.slice(1)),ticket=hash.get('access');$('access-badge').textContent=ticket?'VERIFYING ACCESS':'PRIVATE ACCESS';try{if(ticket){await api('/v1/member/session',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({ticket})});history.replaceState(null,'','/vip#'+accessView(hash.get('view')));}me=await get('me');$('login').hidden=true;$('workspace').hidden=false;$('navigation').hidden=false;$('signout').hidden=false;$('access-badge').textContent=me.tier+' ACCESS';render();}catch(e){if(ticket&&/expired|already used|invalid/i.test(e.message))history.replaceState(null,'','/vip#home');lock(e.message);}if('serviceWorker'in navigator)navigator.serviceWorker.getRegistrations().then(rs=>Promise.all(rs.filter(r=>new URL(r.scope).pathname.startsWith('/vip')).map(r=>r.unregister()))).catch(()=>{});})();
