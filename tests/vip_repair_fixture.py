"""Synthetic local UX acceptance fixture. Never imported by production.

No provider requests, real memberships, live betting data or Discord sends.
"""
import os
from pathlib import Path
from time_machine import travel
clock = travel('2026-11-03T18:00:00Z', tick=True)
clock.start()
from datetime import UTC, datetime, timedelta

os.environ['JABBAZI_PLATFORM_DATABASE_URL'] = 'sqlite:////tmp/jabbazi-repair-fixture.db'
os.environ['JABBAZI_DISCORD_GUILD_ID'] = '1'
os.environ['JABBAZI_MODEL_TOKEN'] = 'synthetic-fixture-' + 'x' * 40
os.environ['JABBAZI_MEMBER_ORIGIN'] = 'https://127.0.0.1:8765'
from jabazi.persistence.store import Store
from jabazi.vip import auth
auth.current_access = lambda *_: {'tier': 'VIP', 'vip': True, 'admin': False}
from jabazi.api import app
from jabazi.member_access import issue_ticket
from jabazi.vip.research import SPORT_CODES

store = Store(os.environ['JABBAZI_PLATFORM_DATABASE_URL'], initialize=True)
now = datetime.now(UTC)
start = (now + timedelta(hours=4)).isoformat()
games = [{'sport': code, 'event_id': label + '-fixture', 'event': label + ' Fixture Away @ Fixture Home',
          'starts_at': start} for label, code in SPORT_CODES.items()]
games.append({'sport': SPORT_CODES['NBA'], 'event_id': 'nba-schedule-only',
              'event': 'NBA Schedule Only @ No Saved Forecast', 'starts_at': start})
rows = []
for game in games[:-1]:
    for side, p in [('Fixture Home', '.64'), ('Fixture Away', '.36')]:
        rows.append({**game, 'market': 'h2h', 'participant': None, 'selection': side, 'line': None,
                     'research_probability': p, 'model_version': 'SYNTHETIC-TEAM-v1',
                     'model_stage': 'VALIDATING', 'data_health': 'HEALTHY', 'executable': True,
                     'decimal_odds': '1.8' if side == 'Fixture Home' else '2.2', 'book': 'FIXTURE BOOK',
                     'market_no_vig_probability': '.55' if side == 'Fixture Home' else '.45',
                     'starts_at_utc': start, 'price_time_utc': (now-timedelta(minutes=8)).isoformat(),
                     'model_time_utc': now.isoformat(), 'status': 'WATCH'})
# Ordinary rows demonstrate unders/alternate lines and player drill-down.
for i in range(65):
    rows.append({**games[0], 'participant': f'Fixture Guard {i:03d}', 'market': 'player_points',
                 'selection': 'Under' if i % 2 else 'Over', 'line': '24.5', 'team': 'Fixture Home',
                 'research_probability': '.61', 'model_version': 'SYNTHETIC-PLAYER-v1',
                 'model_stage': 'VALIDATING', 'data_health': 'HEALTHY', 'executable': True,
                 'decimal_odds': '1.91', 'book': 'FIXTURE BOOK', 'starts_at_utc': start,
                 'price_time_utc': now.isoformat(), 'model_time_utc': now.isoformat(),
                 'status': 'WATCH', 'player_distribution': {'mean': 25.2, 'market': 'player_points', 'model_version': 'SYNTHETIC-PLAYER-v1'}})
for market, side, line in [('player_points', 'Under', '28.5'), ('player_rebounds', 'Over', '5.5'), ('player_assists', 'Under', '6.5')]:
    rows.append({**rows[-1], 'participant': 'Fixture Guard 000', 'market': market,
                 'selection': side, 'line': line, 'player_distribution': None})
store.append('research_sheet', 'latest_scan', {'healthy': True, 'completed_at': now.isoformat(),
             'rows': rows, 'slate_events': games, 'fixture': True})
paid = []
for i in range(61):
    paid.append({'sport': SPORT_CODES['NHL'], 'event_id': 'NHL-fixture', 'event': games[2]['event'],
                 'participant': f'Fixture Skater {i:03d}', 'market': 'player_shots_on_goal',
                 'selection': 'under' if i % 2 else 'over', 'line': '2.5', 'settlement': 'OVER_UNDER',
                 'model_probability': .58 + (i % 5) / 100, 'projected_mean': 3.2, 'model_stage': 'VALIDATING',
                 'model_version': 'SYNTHETIC-NHL-v1', 'model_time': now.isoformat(),
                 'source_timestamp': (now-timedelta(minutes=4)).isoformat(), 'starts_at': start,
                 'best_sportsbook': 'FIXTURE BOOK', 'best_decimal': 1.91,
                 'probability_basis': 'FITTED_JABBAZI_MODEL', 'approved_for_betting': False})
store.append('paid_player_scan', now.date().isoformat(), {'slate_date': now.date().isoformat(),
             'observed_at': now.isoformat(), 'status': 'PARTIAL', 'scope_complete': False,
             'sports': {'NHL': {'coverage': 'FULL', 'research_rows': paid, 'model_probability_rows': 61}}})
ticket = issue_ticket(store, guild=1, member=2, authorized=True)
Path('/tmp/vip-repair-ticket').write_text(ticket)
store.close()
if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host='127.0.0.1', port=8765, ssl_keyfile='/tmp/vip-staging.key',
                ssl_certfile='/tmp/vip-staging.crt', access_log=False)
