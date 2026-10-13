// Synthetic UI contract checks. No production sessions or betting evidence.
const {chromium}=require('playwright');
const fs=require('fs');
const path=require('path');
const assert=require('node:assert/strict');
(async()=>{
 const browser=await chromium.launch({headless:true});
 try{
  const page=await browser.newPage({viewport:{width:390,height:844}}),errors=[],requests=[];
  await page.clock.install({time:new Date('2026-10-14T04:59:00Z')});
  page.on('pageerror',e=>errors.push(e.message));
  await page.route('**/*',async route=>{
   const u=new URL(route.request().url());requests.push(u.pathname+u.search);
   if(u.pathname==='/vip')return route.fulfill({contentType:'text/html',body:fs.readFileSync(path.join(__dirname,'../src/jabazi/static/terminal.html'),'utf8')});
   if(['/vip/terminal.js','/vip/terminal.css'].includes(u.pathname))return route.fulfill({contentType:u.pathname.endsWith('.js')?'application/javascript':'text/css',body:fs.readFileSync(path.join(__dirname,'../src/jabazi/static',path.basename(u.pathname)),'utf8')});
   let body={};
   if(u.pathname.endsWith('/me'))body={tier:'VIP',expires_at:'2026-10-14T05:15:00Z',features:{admin:false},preferences:{}};
   if(u.pathname.endsWith('/board'))body={rows:[],total:0,next:null};
   if(u.pathname.endsWith('/matchups'))body={games:[],notice:'Synthetic only'};
   if(u.pathname.includes('/sim/NFL/'))body={state:'SHADOW_ONLY',event:'Away @ Home',home:'Home',away:'Away',model_version:'SYNTHETIC',summary:{expected_home_points:24,expected_away_points:21,expected_total:45,sample_count:100,margin_predictive_interval_90:[-7,14],total_predictive_interval_90:[28,60]},home_win:{win:.6,push:.1,loss:.3},away_win:{win:.3,push:.1,loss:.6},spread:u.searchParams.has('spread_line')?{home_line:0,win:.6,push:.1,loss:.3}:null,total:u.searchParams.has('total_line')?{line:45,win:.4,push:.2,loss:.4}:null};
   if(u.pathname.includes('/firsttd/'))body={state:'UNAVAILABLE',players:[],reason:'No validated first TD model'};
   return route.fulfill({contentType:'application/json',body:JSON.stringify(body)});
  });
  await page.goto('https://jabbazi.test/vip#access=synthetic&view=sim');
  await page.getByRole('heading',{name:'Game simulator',exact:true}).waitFor();
  assert.equal(new URL(page.url()).hash,'#sim');
  await page.goto('https://jabbazi.test/vip#simdetail=NFL|test');
  await page.getByLabel('Home spread (scenario)').fill('0');
  await page.getByLabel('Game total (scenario)').fill('45');
  await page.getByRole('button',{name:'Evaluate lines'}).click();
  await page.getByText('Spread push',{exact:true}).waitFor();
  assert(requests.some(r=>r.includes('spread_line=0&total_line=45')));
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
  await page.goto('https://jabbazi.test/vip#firsttddetail=NFL|test');
  await page.getByText('Verified projections unavailable',{exact:true}).waitFor();
  await page.goto('https://jabbazi.test/vip#props');
  await page.getByText('0 eligible prop rows today',{exact:true}).waitFor();
  const count=requests.filter(r=>r.includes('family=props')).length;
  assert(count>0);
  const refreshed=page.waitForResponse(r=>r.url().includes('family=props'));
  await page.clock.fastForward(90000);
  await refreshed;
  await page.waitForFunction(()=>document.querySelector('#content').textContent.includes('0 eligible prop rows today'));
  assert(requests.filter(r=>r.includes('family=props')).length>count,'Chicago midnight refreshes daily view');
  assert.deepEqual(errors,[]);
  console.log('PASS: private deep link, scenario lines, push display, mobile layout, First TD unavailable');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
