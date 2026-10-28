// Synthetic UI contract checks. No production sessions or betting evidence.
const {chromium}=require('playwright');
const fs=require('fs');
const path=require('path');
const assert=require('node:assert/strict');
(async()=>{
 const browser=await chromium.launch({headless:true});
 try{
  const page=await browser.newPage({viewport:{width:390,height:844}}),errors=[],requests=[];
  await page.clock.install({time:new Date('2026-10-14T03:59:00Z')});
  page.on('pageerror',e=>errors.push(e.message));
  await page.route('**/*',async route=>{
   const u=new URL(route.request().url());requests.push(u.pathname+u.search);
   if(u.pathname==='/vip')return route.fulfill({contentType:'text/html',body:fs.readFileSync(path.join(__dirname,'../src/jabazi/static/terminal.html'),'utf8')});
   if(['/vip/terminal.js','/vip/terminal.css'].includes(u.pathname))return route.fulfill({contentType:u.pathname.endsWith('.js')?'application/javascript':'text/css',body:fs.readFileSync(path.join(__dirname,'../src/jabazi/static',path.basename(u.pathname)),'utf8')});
   let body={};
   if(u.pathname.endsWith('/me'))body={tier:'VIP',expires_at:'2026-10-14T05:15:00Z',features:{admin:false},preferences:{}};
   if(u.pathname.endsWith('/board'))body={rows:[],total:0,next:null};
   if(u.pathname.endsWith('/home'))body={load_strategy:'on_demand',state:'ON_DEMAND',notice:'Synthetic home',sports:[]};
   if(u.pathname.endsWith('/today'))body={games:[],research:[],official:[],recap:{groups:[]},live_notice:'Pregame only'};
   if(u.pathname.endsWith('/matchups'))body={games:[],notice:'Synthetic only'};
   if(u.pathname.endsWith('/paid-player-models'))body={
      provider:'BALLDONTLIE_LAB',sport:u.searchParams.get('sport'),
      state:'RESEARCH_ONLY',slate_date:'2026-10-14',
      observed_at:'2026-10-14T12:00:00Z',coverage_complete:true,
      models_found:1,models_checked:1,predictions_seen:1,
      betting_enabled:false,notice:'Synthetic LAB forecasts are not hit probabilities',
      rows:[{model_id:17,model_name:'Fixture model',player_name:'Fixture Athlete',
        game_id:88,market:'points',predicted_value:24.5,model_signal_value:24.5,
        provider_confidence_raw:.92,model_hit_probability:null,predicted_side:'over',market_line:22.5}],
    };
   if(u.pathname.endsWith('/boost/status'))body={
     mode:'RESEARCH_ONLY',state:'READY',decision:'PASS',
     paid_requests_made:0,betting_enabled:false,
     notice:'Synthetic audit only, no executable quote',
     sports:[
       {sport:'NBA',player_model_stage:'VALIDATING',player_markets:[
         {market:'player_points',stage:'VALIDATING',prospective_samples:0}
       ],joint_probability_calibration:'NOT_VERIFIED',paid_slate_coverage:'NOT_VERIFIED',
        bookmaker_parlay_price:'NOT_VERIFIED',betting_enabled:false},
       ...['NFL','NHL'].map(sport=>({sport,player_model_stage:'UNAVAILABLE',
         player_markets:[],joint_probability_calibration:'NOT_VERIFIED',
         paid_slate_coverage:'NOT_VERIFIED',bookmaker_parlay_price:'NOT_VERIFIED',
         betting_enabled:false}))
     ]
   };
   if(u.pathname.endsWith('/promo')&&route.request().method()==='POST')
     body={boosted_decimal:2.3,break_even:0.4347826,boosted_ev:null,
       notice:'Synthetic payout scenario; not a model prediction.'};
   if(u.pathname.includes('/sim/NFL/'))body={state:'SHADOW_ONLY',event:'Away @ Home',home:'Home',away:'Away',model_version:'SYNTHETIC',summary:{expected_home_points:24,expected_away_points:21,expected_total:45,sample_count:100,margin_predictive_interval_90:[-7,14],total_predictive_interval_90:[28,60]},home_win:{win:.6,push:.1,loss:.3},away_win:{win:.3,push:.1,loss:.6},spread:u.searchParams.has('spread_line')?{home_line:0,win:.6,push:.1,loss:.3}:null,total:u.searchParams.has('total_line')?{line:45,win:.4,push:.2,loss:.4}:null};
   if(u.pathname.includes('/firsttd/'))body={state:'UNAVAILABLE',players:[],reason:'No validated first TD model'};
   return route.fulfill({contentType:'application/json',body:JSON.stringify(body)});
  });
  await page.goto('https://jabbazi.test/vip#access=synthetic&view=sim');
  await page.getByRole('heading',{name:'Game simulator',exact:true}).waitFor();
  assert.equal(new URL(page.url()).hash,'#sim');
  await page.goto('https://jabbazi.test/vip#home');
  await page.getByRole('heading',{name:'Slate 2026-10-13 · America/Chicago',exact:true}).waitFor();
  const nightRefresh=page.waitForResponse(r=>r.url().includes('/today?')&&r.url().includes('slate_date=2026-10-14'));
  await page.clock.fastForward(90000);
  await nightRefresh;
  await page.getByRole('heading',{name:'Slate 2026-10-14 · America/Chicago',exact:true}).waitFor();
  await page.getByLabel('Slate date',{exact:true}).selectOption('today');
  await page.getByRole('heading',{name:'Slate 2026-10-13 · America/Chicago',exact:true}).waitFor();
  await page.getByLabel('Slate date',{exact:true}).selectOption('auto');
  await page.getByRole('heading',{name:'Slate 2026-10-14 · America/Chicago',exact:true}).waitFor();
  await page.goto('https://jabbazi.test/vip#simdetail=NFL|test');
  await page.getByLabel('Home spread (scenario)').fill('0');
  await page.getByLabel('Game total (scenario)').fill('45');
  await page.getByRole('button',{name:'Evaluate lines'}).click();
  await page.getByText('Spread push',{exact:true}).waitFor();
  assert(requests.some(r=>r.includes('spread_line=0&total_line=45')));
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
  await page.goto('https://jabbazi.test/vip#firsttddetail=NFL|test');
  await page.getByText('Verified projections unavailable',{exact:true}).waitFor();
  // Paid forecasts stay isolated by sport, on demand, and never claim hit probabilities.
  for(const sp of ['NBA','NFL','NHL']){
    await page.goto('https://jabbazi.test/vip#paidplayers&sport='+sp);
    await page.getByRole('heading',{name:sp+' Paid Player Model Research',exact:true}).waitFor();
    await page.getByText('Fixture Athlete',{exact:true}).waitFor();
    await page.getByText('Hit probability',{exact:true}).waitFor();
    await page.getByText('LAB model signal (not stat total)',{exact:true}).waitFor();
    await page.getByText('NOT VERIFIED',{exact:true}).waitFor();
  }
  assert(requests.filter(x=>x.includes('/paid-player-models')).length===3);
  assert(requests.every(x=>!x.includes('/lab/v1/')&&!x.includes('/odds/player_props')));
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
  await page.goto('https://jabbazi.test/vip#props');
  await page.getByText('0 eligible prop rows today',{exact:true}).waitFor();
  const count=requests.filter(r=>r.includes('family=props')).length;
  assert(count>0);
  const refreshed=page.waitForResponse(r=>r.url().includes('family=props'));
  await page.clock.fastForward(3600000);
  await refreshed;
  await page.waitForFunction(()=>document.querySelector('#content').textContent.includes('0 eligible prop rows today'));
  assert(requests.filter(r=>r.includes('family=props')).length>count,'Chicago midnight refreshes daily view');
  await page.route('**/v1/vip/models?*',route=>route.fulfill({status:503,contentType:'application/json',body:JSON.stringify({detail:'Synthetic metadata outage'})}));
  await page.route('**/v1/vip/slate?*',route=>route.fulfill({contentType:'application/json',body:JSON.stringify({games:[]})}));
  await page.route('**/v1/vip/top10?*',route=>route.fulfill({contentType:'application/json',body:JSON.stringify({rows:[]})}));
  await page.goto('https://jabbazi.test/vip#sport=MLB');
  await page.getByText('Model evidence could not load',{exact:true}).waitFor();
  await page.getByRole('heading',{name:'MLB Research Terminal',exact:true}).waitFor();
  await page.route('**/v1/vip/rankings?*',route=>route.fulfill({contentType:'application/json',body:JSON.stringify({date:'2026-10-14',game_count:1,stale_rows:0,notice:'Research only',web_leans:[],conflicting_events:[],moneyline_likely:[{sport:'NFL',event_id:'one',event:'Fixture Away @ Fixture Home',selection:'Fixture Home',evidence_label:'MARKET-CONSENSUS LEAN',model_probability:null,market_probability:.6,decimal:1.8,book:'Fixture',price_at:'2026-10-14T05:00:00Z'}]})}));
  await page.goto('https://jabbazi.test/vip#rankings&sport=NFL');
  await page.getByRole('heading',{name:'NFL · Today’s research rankings',exact:true}).waitFor();
  await page.getByRole('heading',{name:'Receiving unders at exact lines',exact:true}).waitFor();
  await page.getByRole('heading',{name:'Receiving over/under value supported by approved models',exact:true}).waitFor();
  await page.getByText('MARKET-CONSENSUS LEAN',{exact:true}).waitFor();
  await page.getByRole('heading',{name:'Fixture Home',exact:true}).waitFor();
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
  await page.route('**/v1/vip/matchup/MLB/explanation?*',route=>route.fulfill({contentType:'application/json',body:JSON.stringify({sport:'MLB',event:'Fixture Away @ Fixture Home',starts_at:'2026-10-14T18:00:00Z',projection:{selection:'Fixture Home',source:'MARKET CONSENSUS',market_no_vig_probability:.6},markets:['h2h'],first_td:{reason:'Not applicable'},official:[],research:[],pick_explanation:{reason:'The observed moneyline market favors Fixture Home, with a 60% no-vig implied chance.',caution:'This is a market lean, not an independent model forecast.',observed_at:'2026-10-14T05:00:00Z'}})}));
  await page.goto('https://jabbazi.test/vip#matchup=MLB|explanation');
  await page.getByRole('heading',{name:'Why this pick',exact:true}).waitFor();
  await page.getByText('The observed moneyline market favors Fixture Home, with a 60% no-vig implied chance.',{exact:true}).waitFor();
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
  // The VIP boost screen must remain research-only, quota-free and mobile-safe.
  await page.goto('https://jabbazi.test/vip#promo');
  await page.getByRole('heading',{name:'NBA · NFL · NHL research',exact:true}).waitFor();
  for(const sport of ['NBA','NFL','NHL'])
    await page.getByRole('heading',{name:sport+' player props',exact:true}).waitFor();
  await page.getByText('Model evidence: READY · Decision: PASS · Paid requests: 0',{exact:true}).waitFor();
  await page.getByText('Exact sportsbook parlay quote: NOT_VERIFIED · Betting: DISABLED').first().waitFor();
  await page.getByRole('button',{name:'Calculate boost'}).click();
  await page.getByText('Synthetic payout scenario; not a model prediction.',{exact:true}).waitFor();
  assert(requests.some(x=>x.includes('/v1/vip/boost/status?slate_date=')));
  assert(requests.every(x=>!x.includes('/odds/player_props')&&!x.includes('/boost-feed-diagnostic')&&!x.includes('/mcp/')));
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);

  // Server failure or malformed readiness must show PASS/UNAVAILABLE,
  // never hide the independent hypothetical boost calculator.
  await page.route('**/v1/vip/boost/status?*',route=>route.fulfill({
    status:503,contentType:'application/json',
    body:JSON.stringify({detail:'PRIVATE_SERVICE_ERROR_DO_NOT_RENDER'}),
  }));
  await page.reload();
  await page.getByText('Model evidence: UNAVAILABLE · Decision: PASS · Paid requests: 0',{exact:true}).waitFor();
  await page.getByText('Boost readiness could not be verified. All selections remain PASS. No live paid scan was started.',{exact:true}).waitFor();
  await page.getByRole('button',{name:'Calculate boost'}).click();
  await page.getByText('Synthetic payout scenario; not a model prediction.',{exact:true}).waitFor();
  assert(!(await page.locator('#content').textContent()).includes('PRIVATE_SERVICE_ERROR_DO_NOT_RENDER'));
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
  await page.unroute('**/v1/vip/boost/status?*');
  await page.route('**/v1/vip/boost/status?*',route=>route.fulfill({
    contentType:'application/json',
    body:JSON.stringify({mode:'RESEARCH_ONLY',state:'READY',
      decision:'BET NOW',betting_enabled:true,
      sports:[{sport:'NHL',player_markets:[]}]})
  }));
  await page.reload();
  await page.getByText('Model evidence: UNAVAILABLE · Decision: PASS · Paid requests: 0',{exact:true}).waitFor();
  await page.getByRole('button',{name:'Calculate boost'}).click();
  await page.getByText('Synthetic payout scenario; not a model prediction.',{exact:true}).waitFor();
  assert(!(await page.locator('#content').textContent()).includes('BET NOW'));
  await page.unroute('**/v1/vip/boost/status?*');

  await page.route('**/v1/vip/admin?*',route=>route.fulfill({status:403,contentType:'application/json',body:JSON.stringify({detail:'Administrator access required.'})}));
  await page.goto('https://jabbazi.test/vip#admin');
  await page.getByText('This view is unavailable',{exact:true}).waitFor();
  assert.equal(await page.locator('#login').isVisible(),false,'resource denial preserves member session');
  assert.deepEqual(errors,[]);
  console.log('PASS: private deep link, scenario lines, push display, mobile layout, First TD unavailable');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
