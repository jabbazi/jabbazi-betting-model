"""Isolated local browser fixture; never imported by production."""
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

os.environ['JABBAZI_PLATFORM_DATABASE_URL']='sqlite:////tmp/jabbazi-vip-staging.db'
os.environ['JABBAZI_DISCORD_GUILD_ID']='1'
os.environ['JABBAZI_MODEL_TOKEN']='synthetic-test-owner-'+'x'*40
os.environ['JABBAZI_MEMBER_ORIGIN']='https://127.0.0.1:8765'
from jabazi.persistence.store import Store
store=Store(os.environ['JABBAZI_PLATFORM_DATABASE_URL'],initialize=True)
from jabazi.vip import auth
auth.current_access=lambda *_: {'tier':'ADMIN','vip':True,'admin':True}
from jabazi.api import app
from jabazi.member_access import issue_ticket
from jabazi.discord_daily import freeze_daily_moneyline
now=datetime.now(UTC)
rows=[]
for sport,event,player,market in [('baseball_mlb','Yankees @ Orioles','Aaron Judge','batter_home_runs'),('americanfootball_nfl','Chiefs @ Chargers','Patrick Mahomes','player_pass_yds'),('americanfootball_ncaaf','LSU @ Auburn',None,'spreads')]:
    rows.append({'sport':sport,'event_id':sport+'-test','event':event,'participant':player,'market':market,'selection':'Over' if player else 'LSU','line':'0.5' if sport=='baseball_mlb' else '250.5' if player else '-3.5','decimal_odds':'2.0','book':'SYNTHETIC TEST BOOK','research_probability':'.56','model_version':'STAGING-FIXTURE-NOT-A-PREDICTION','market_no_vig_probability':'.51','model_stage':'VALIDATING','data_health':'HEALTHY','executable':True,'status':'WATCH','starts_at_utc':(now+timedelta(hours=2)).isoformat(),'price_time_utc':now.isoformat()})
store.append('research_sheet','latest_scan',{'rows':rows,'healthy':True,'completed_at':now.isoformat()})
record=store.list_records('research_sheet',1,entity='latest_scan')[0]
freeze_daily_moneyline(store,record)
ticket=issue_ticket(store,guild=1,member=2,authorized=True)
Path('/tmp/vip-staging-ticket').write_text(ticket)
store.close()
if __name__=='__main__':
    import uvicorn
    uvicorn.run(app,host='127.0.0.1',port=8765,ssl_keyfile='/tmp/vip-staging.key',ssl_certfile='/tmp/vip-staging.crt',access_log=False)
