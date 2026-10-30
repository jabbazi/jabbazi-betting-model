const {chromium}=require('playwright');const fs=require('fs');
(async()=>{const browser=await chromium.launch({headless:true});const context=await browser.newContext({ignoreHTTPSErrors:true,viewport:{width:390,height:844},deviceScaleFactor:1});const page=await context.newPage();const errors=[];page.on('pageerror',e=>errors.push(e.message));const token=fs.readFileSync('/tmp/vip-staging-ticket','utf8').trim();await page.goto('https://127.0.0.1:8765/vip#access='+token);await page.locator('#workspace').waitFor({state:'visible'});await page.getByRole('heading',{name:'Your VIP terminal is ready'}).waitFor();await page.screenshot({path:'/tmp/jabbazi-vip-mobile-home.png',fullPage:true});await page.goto('https://127.0.0.1:8765/vip#search&q=Judge%20HR');await page.locator('.opportunity').first().waitFor();await page.locator('.opportunity').first().click();await page.getByRole('heading',{name:'Behind the research'}).waitFor();await page.getByLabel('Alert when decimal odds reach (optional)').fill('2.1');await page.getByRole('button',{name:'☆ Add to watchlist'}).click();await page.getByRole('status').filter({hasText:'Added to your private watchlist'}).waitFor();await page.screenshot({path:'/tmp/jabbazi-vip-mobile-detail.png',fullPage:true});await page.goto('https://127.0.0.1:8765/vip#watchlist');await page.getByRole('heading',{name:'Your alert inbox'}).waitFor();await page.goto('https://127.0.0.1:8765/vip#settings');await page.getByLabel('Your unit size ($)').fill('50');await page.getByRole('button',{name:'Save preferences'}).click();await page.getByRole('status').filter({hasText:'Saved.'}).waitFor();await page.goto('https://127.0.0.1:8765/vip#top10');await page.getByRole('heading',{name:'NFL · Today’s research rankings',exact:true}).waitFor();await page.goto('https://127.0.0.1:8765/vip#sports');await page.getByRole('heading',{name:'MLB',exact:true}).waitFor();await page.goto('https://127.0.0.1:8765/vip#sport=NFL');await page.getByRole('heading',{name:'NFL Research Terminal'}).waitFor();await page.getByRole('heading',{name:'Anytime touchdown candidates',exact:true}).waitFor();
const paidCalls=[];const readinessReplies=[];
page.on('request',req=>{if(/(?:odds\/player_props|boost-feed-diagnostic|\/mcp\/)/.test(req.url()))paidCalls.push(req.url());});
page.on('response',r=>{if(r.url().includes('/v1/vip/boost/status'))readinessReplies.push(r);});
await page.goto('https://127.0.0.1:8765/vip#promo');
await page.getByRole('heading',{name:'NBA · NFL · NHL research',exact:true}).waitFor();
for(const sport of ['NBA','NFL','NHL'])
  await page.getByRole('heading',{name:sport+' player props',exact:true}).waitFor();
await page.getByText(/Model evidence: .* · Decision: PASS · Paid requests: 0/).waitFor();
await page.getByText('Exact sportsbook parlay quote: NOT_VERIFIED · Betting: DISABLED').first().waitFor();
if(!readinessReplies.length||readinessReplies.at(-1).status()!==200)throw Error('Authenticated staging boost readiness failed');
const readiness=await readinessReplies.at(-1).json();
if(readiness.mode!=='RESEARCH_ONLY'||readiness.decision!=='PASS'||readiness.betting_enabled!==false
  ||readiness.paid_requests_made!==0||readiness.sports.map(x=>x.sport).join(',')!=='NBA,NFL,NHL')
  throw Error('Staging readiness violated research-only contract');
await page.getByRole('button',{name:'Calculate boost'}).click();
await page.getByText('Profit-boost calculation only. Confirm eligibility, stake caps and sportsbook terms.',{exact:true}).waitFor();
await page.getByText('Probability source: your assumption, not a JABBAZI forecast.',{exact:true}).waitFor();
await page.route('**/v1/vip/boost/status?*',route=>route.fulfill({
 status:503,contentType:'application/json',
 body:JSON.stringify({detail:'INTERNAL_SECRET_MUST_NOT_LEAK'})
}));
await page.reload();
await page.getByText('Model evidence: UNAVAILABLE · Decision: PASS · Paid requests: 0',{exact:true}).waitFor();
await page.getByRole('button',{name:'Calculate boost'}).click();
await page.getByText('Profit-boost calculation only. Confirm eligibility, stake caps and sportsbook terms.',{exact:true}).waitFor();
if((await page.locator('#content').textContent()).includes('INTERNAL_SECRET_MUST_NOT_LEAK'))
 throw Error('Staging boost fallback leaked internal service error');
if(paidCalls.length)throw Error('Boost status page accessed live paid/provider API');
await page.unroute('**/v1/vip/boost/status?*');
const overflow=await page.evaluate(()=>document.documentElement.scrollWidth>window.innerWidth);await page.screenshot({path:'/tmp/jabbazi-vip-mobile-sports.png',fullPage:true});await page.setViewportSize({width:1440,height:1000});await page.goto('https://127.0.0.1:8765/vip#home');await page.getByRole('heading',{name:'Your VIP terminal is ready'}).waitFor();await page.screenshot({path:'/tmp/jabbazi-vip-desktop.png',fullPage:true});await context.setOffline(true);await page.getByRole('alert').waitFor({state:'visible'});if(await page.locator('#content').textContent()!=='')throw Error('Offline research not cleared');await context.setOffline(false);console.log(JSON.stringify({mobile_width:390,desktop_width:1440,horizontal_overflow:overflow,page_errors:errors,flows:['ticket login','home','alias search','detail','watchlist','personal unit','Top10 fail-closed','sports','boost authenticated readiness','boost outage PASS fallback','hypothetical calculator','offline clearing']}));await browser.close();if(overflow||errors.length)process.exit(1);})().catch(e=>{console.error(e);process.exit(1)});
