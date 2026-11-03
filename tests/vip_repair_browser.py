"""Offline Chromium + real TestClient research acceptance (synthetic data only).

HTML/CSS/JS are the application assets; fetch is bridged to the real ASGI app.
This does not verify network/TLS, actual Discord membership or live delivery.
No browser policy is changed and no browser network navigation is needed.
"""
import argparse
import base64
import json
import os
from pathlib import Path
import re
import runpy
import sys

parser = argparse.ArgumentParser()
parser.add_argument('--source', type=Path, default=Path(__file__).resolve().parents[1])
parser.add_argument('--output', type=Path, required=True)
parser.add_argument('--before', action='store_true')
args = parser.parse_args()
args.output.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(args.source / 'src'))
for name in ('/tmp/jabbazi-repair-fixture.db', '/tmp/jabbazi-repair-fixture.db-wal', '/tmp/jabbazi-repair-fixture.db-shm'):
    Path(name).unlink(missing_ok=True)
fixture = runpy.run_path(str(args.source / 'tests/vip_repair_fixture.py'), run_name='fixture')
from fastapi.testclient import TestClient
from playwright.sync_api import sync_playwright
client = TestClient(fixture['app'], base_url='https://127.0.0.1:8765')
login = client.post('/v1/member/session', json={'ticket': fixture['ticket']}, headers={'Origin': 'https://127.0.0.1:8765'})
assert login.status_code == 200
assert client.get('/v1/vip/me').status_code == 200
requests = []
fail_board = False

def backend(path, options):
    assert path.startswith(('/v1/vip/', '/v1/member/', '/vip/version')), path
    requests.append(path)
    if fail_board and path.startswith('/v1/vip/board'):
        return {'status': 503, 'body': {'detail': 'PRIVATE_SERVICE_DIAGNOSTIC'}}
    response = client.request(options.get('method', 'GET'), path,
        content=options.get('body'), headers={**options.get('headers', {}), 'Origin': 'https://127.0.0.1:8765'})
    return {'status': response.status_code, 'body': response.json()}

static = args.source/'src/jabazi/static'
html = (static/'terminal.html').read_text().replace('__JABBAZI_RELEASE__', 'development')
html = re.sub(r'<link[^>]+>', '', html)
html = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.S)
logo = 'data:image/png;base64,' + base64.b64encode((static/'jabbazi-approved.png').read_bytes()).decode()
html = html.replace('/vip/jabbazi-approved.png', logo)
css = (static/'terminal.css').read_text()
html = html.replace('</head>', '<style>'+css+'\n.fixture-label{padding:8px;text-align:center;background:#392b0b;color:#fff;font:12px system-ui;position:relative;z-index:1000}</style></head>')
html = html.replace('<body>', '<body><div class="fixture-label">SYNTHETIC LOCAL FIXTURE · NOT PRODUCTION · '+('BEFORE' if args.before else 'DEVELOPMENT REPAIR')+'</div>')
errors, flows = [], []
with sync_playwright() as p:
    browser = p.chromium.launch(executable_path=os.environ.get('CHROMIUM_PATH', '/usr/bin/chromium'), headless=True)
    page = browser.new_page(viewport={'width': 1440, 'height': 1050}, device_scale_factor=1)
    page.set_default_timeout(8000)
    page.on('pageerror', lambda err: errors.append(str(err)))
    page.expose_function('fixtureBackend', backend)
    page.set_content(html)
    page.evaluate("""() => {window.fetch=async(path,options={})=>{if(window.delayNBA&&String(path).includes('/board?')&&String(path).includes('sport=NBA'))await new Promise(r=>setTimeout(r,400));const r=await window.fixtureBackend(String(path),{method:options.method||'GET',headers:options.headers||{},body:options.body||null});return {ok:r.status>=200&&r.status<300,status:r.status,json:async()=>r.body};};location.hash='props&sport=NHL';}""")
    page.add_script_tag(content=(static/'terminal.js').read_text())
    page.locator('#workspace').wait_for(state='visible')
    page.wait_for_function("document.getElementById('refresh').disabled===false && document.getElementById('content').textContent.length>100")
    page.screenshot(path=str(args.output/('before_nhl_props_desktop.png' if args.before else 'after_nhl_props_desktop.png')))
    if args.before:
        page.set_viewport_size({'width':390,'height':844})
        page.screenshot(path=str(args.output/'before_nhl_props_mobile.png'))
        flows.append('before NHL props screen with the same saved fixture')
    else:
        def route(hash, expected=None):
            page.evaluate('(hash)=>{location.hash=hash}', hash)
            page.wait_for_function("document.getElementById('refresh').disabled===false")
            if expected:
                page.get_by_text(expected, exact=False).first.wait_for()
        assert page.locator('.opportunity').count() == 50
        assert '61 matching rows' in page.locator('#content').inner_text()
        page.get_by_role('link', name='Next 50 →').first.click()
        page.wait_for_function("document.querySelectorAll('.opportunity').length===11")
        assert 'offset=50' in page.url
        flows.append('61 saved paid props, working second page, no truncation as Top 10')
        page.screenshot(path=str(args.output/'after_nhl_page_two_desktop.png'))
        route('moneylines&sport=NBA', 'Fixture Home')
        assert '64.0%' in page.locator('#content').inner_text()
        assert 'No Saved Forecast' in page.locator('#content').inner_text()
        assert 'Current price unavailable' in page.locator('#content').inner_text()
        page.screenshot(path=str(args.output/'after_moneylines_desktop.png'))
        flows.append('VALIDATING model winner survives stale price; schedule-only game visible')
        page.set_viewport_size({'width':390,'height':844})
        page.screenshot(path=str(args.output/'after_moneylines_mobile.png'), full_page=True)
        # Prime saved registry evidence in this disposable fixture only; no providers.
        from jabazi.vip.model_status import saved_model_status
        from jabazi.vip import model_cache
        import time
        model_cache._cache = saved_model_status()
        model_cache._cached_at = time.monotonic()
        route('model-routing&sport=NFL', 'NFL · Model connections')
        page.get_by_text('Saved selections:', exact=False).first.wait_for()
        assert page.get_by_role('link', name='Open this market').count() >= 16
        page.screenshot(path=str(args.output/'after_model_connections_mobile.png'), full_page=True)
        page.get_by_role('combobox', name='Research sport').select_option('CFB')
        page.get_by_text('CFB · Model connections', exact=True).wait_for()
        assert 'model-routing&' in page.url
        assert 'College player props remain restricted' in page.locator('#content').inner_text()
        flows.append('model connection inventory, per-market links, selected sport and college policy')
        route('props&sport=NBA&player=Fixture%20Guard%20000', '4 matching rows')
        assert page.locator('.opportunity').count() == 4
        assert page.get_by_role('link', name=re.compile('rebounds')).count() >= 1
        page.locator('summary').filter(has_text='Filter research').click()
        page.get_by_role('combobox', name='Side', exact=True).select_option('Under')
        page.get_by_role('button', name='Apply filters').click()
        page.wait_for_function("document.querySelectorAll('.opportunity').length===2")
        assert 'player=Fixture' in page.url
        flows.append('all player markets and alternate lines; under filter retains player')
        page.screenshot(path=str(args.output/'after_player_props_mobile.png'))
        page.locator('.opportunity').first.click()
        page.get_by_role('heading', name='Behind the research').wait_for()
        assert page.get_by_role('link', name=re.compile('All props for Fixture Guard')).count() == 1
        flows.append('player detail links back to all available props')
        route('top10&sport=NBA&market=player_points&mode=projection', 'Projected average')
        assert page.get_by_text('25.2', exact=False).count() >= 1
        assert 'not hit probabilities' in page.locator('#content').inner_text()
        page.screenshot(path=str(args.output/'after_top10_mobile.png'))
        flows.append('genuine fitted statistical projections separate from hit rates')
        route('props&sport=NBA&market=player_blocks', 'No records match these filters')
        assert page.get_by_role('link', name='Reset filters').count() == 1
        flows.append('zero-market and no-match recovery')
        page.get_by_role('combobox', name='Research sport').select_option('NFL')
        page.wait_for_function("location.hash.includes('sport=NFL') && !location.hash.includes('market=')")
        page.get_by_role('combobox', name='Slate date').select_option('tomorrow')
        page.get_by_text('2026-11-04', exact=False).first.wait_for()
        flows.append('persistent sport and explicit next-day mode')
        route('props&sport=NHL&date=2026-11-03', '61 matching rows')
        assert page.get_by_role('combobox', name='Slate date').input_value() == 'today'
        assert requests[-1].endswith('slate_date=2026-11-03')
        page.get_by_role('combobox', name='Slate date').select_option('tomorrow')
        page.get_by_text('2026-11-04', exact=False).first.wait_for()
        assert 'date=' not in page.url
        assert page.locator('.opportunity').count() == 0
        flows.append('dated Discord research link uses its date; manual date changes do not stick')
        count_before = len(requests)
        route('props&sport=NHL&date=2025-01-01', 'This dated research link is no longer current')
        assert len(requests) == count_before
        page.get_by_role('button', name='Open current slate').click()
        page.wait_for_function("document.querySelectorAll('.opportunity').length===50")
        flows.append('expired dated links never substitute a different slate silently')
        route('search&q=Skater', '61 matching rows')
        assert page.get_by_role('combobox', name='Research sport').input_value() == ''
        assert 'Viewing all sports' in page.locator('#content').inner_text()
        page.get_by_role('combobox', name='Research sport').select_option('NBA')
        page.get_by_text('No records match these filters', exact=False).first.wait_for()
        page.get_by_role('combobox', name='Research sport').select_option('')
        page.wait_for_function("document.querySelectorAll('.opportunity').length===50")
        page.get_by_role('link', name='Next 50 →').first.click()
        page.wait_for_function("document.querySelectorAll('.opportunity').length===11")
        assert 'search&' in page.url
        flows.append('global search crosses sports and retains full-board pagination')

        page.get_by_role('combobox', name='Slate date').select_option('today')
        fail_board = True
        route('props&sport=NHL', 'This view is unavailable')
        assert page.get_by_role('button', name='Retry this view').count() == 1
        assert 'PRIVATE_SERVICE_DIAGNOSTIC' not in page.locator('#content').inner_text()
        fail_board = False
        page.get_by_role('button', name='Retry this view').click()
        page.wait_for_function("document.querySelectorAll('.opportunity').length===50")
        flows.append('explicit service-error state and working retry')
        page.evaluate("window.delayNBA=true;location.hash='props&sport=NBA'")
        page.wait_for_timeout(50)
        page.evaluate("location.hash='props&sport=NHL'")
        page.wait_for_function("document.querySelectorAll('.opportunity').length===50 && document.querySelector('.opportunity').textContent.includes('Skater')")
        page.wait_for_timeout(600)
        assert 'Skater' in page.locator('.opportunity').first.inner_text()
        assert 'Guard' not in page.locator('.opportunity').first.inner_text()
        flows.append('slower old sport response cannot overwrite new selection')
        assert not page.evaluate('document.documentElement.scrollWidth>innerWidth'), 'mobile overflow'
        page.evaluate("dispatchEvent(new Event('offline'))")
        assert page.locator('#content').inner_text() == ''
        flows.append('offline clears current research')
    browser.close()
assert not errors, errors
report = {'environment':'offline Chromium plus real FastAPI TestClient; synthetic rows and roles only',
          'browser_network_navigation':False,'live_acceptance':False, 'page_errors':errors,
          'flows':flows,'request_count':len(requests),'requests':requests,
          'screenshots':[x.name for x in args.output.glob('*.png')]}
(args.output/('before_browser.json' if args.before else 'after_browser.json')).write_text(json.dumps(report, indent=2))
print(json.dumps({k:v for k,v in report.items() if k!='requests'}, indent=2))
