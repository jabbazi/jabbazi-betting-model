"""Disposable DB and synthetic source fixtures, never live acceptance evidence."""
from datetime import timedelta
import json
import time
from types import SimpleNamespace
from uuid import uuid4

import pytest

from jabazi import chatgpt_api as bridge
from jabazi.boost_goat_inference_acceptance import audit_exact_line_research
from jabazi.boost_goat_research_inference import research_goat_exact_line
from jabazi.boost_identity_manifest import crosswalk_digest
from jabazi.boost_scope import SPORTS
from jabazi.paid_player_evidence import (
    feature_inventory, freeze_two_sided_forecasts, matching_game_crosswalks,
    refresh_reviewed_features, register_reviewed_manifest,
)
from jabazi.paid_player_scan import PaidScanLimits, run_paid_player_scan
from jabazi.persistence.store import Store, digest
from tests.test_v7_paid_player_scan import (
    NOW, START, PaidProvider, evidence, game, no_lab, quote, run, seed,
)


@pytest.fixture
def store(tmp_path):
    db = Store('sqlite:///' + str(tmp_path / 'v7.db'), initialize=True)
    try:
        yield db
    finally:
        db.close()


def test_reviewed_manifest_registration_is_explicit_idempotent_and_private(store):
    mapping, _, _ = evidence('NHL')
    dry = register_reviewed_manifest(store, 'NHL', [mapping], now=NOW)
    assert dry['registration_allowed'] and not dry['committed']
    assert store.list_records('paid_player_identity_manifest', 1) == []
    first = register_reviewed_manifest(store, 'NHL', [mapping], now=NOW, commit=True)
    second = register_reviewed_manifest(store, 'NHL', [mapping], now=NOW, commit=True)
    assert first['committed'] and not second['committed']
    assert not first['independent_provider_truth_confirmed_by_runtime']
    assert not first['hit_probability_verified']
    assert not first['betting_enabled']
    assert len(store.list_records('paid_player_identity_manifest', 10)) == 1
    assert mapping['source_player_id'] not in json.dumps(first)


@pytest.mark.parametrize('records', [[], [None], [{}], ['text']])
def test_bad_manifest_never_creates_evidence(store, records):
    dry = register_reviewed_manifest(store, 'NBA', records, now=NOW)
    assert not dry['registration_allowed'] and not dry['committed']
    with pytest.raises(ValueError):
        register_reviewed_manifest(store, 'NBA', records, now=NOW, commit=True)
    assert store.list_records('paid_player_identity_manifest', 10) == []


def test_feature_inventory_queries_only_requested_sport_and_events(store):
    mapping, snapshot, _ = evidence('NBA')
    store.append('player_feature_snapshot', 'one', snapshot, 'one')
    store.append('player_feature_snapshot', 'two', {**snapshot, 'event_id': 'unrelated'}, 'two')
    store.append('player_feature_snapshot', 'three', {**snapshot, 'sport': SPORTS['NFL']}, 'three')
    selected = feature_inventory(store, 'NBA', [mapping])
    assert [r['payload'] for r in selected] == [snapshot]
    assert feature_inventory(store, 'NBA', []) == []


def test_reviewed_game_mapping_rejects_schedule_drift():
    mapping, _, _ = evidence('NBA')
    good, rejected = matching_game_crosswalks('NBA', [mapping], [game('NBA')])
    assert good == [mapping] and rejected == 0
    good, rejected = matching_game_crosswalks('NBA', [mapping], [game('NBA', start=START+timedelta(hours=1))])
    assert good == [] and rejected == 1


def test_existing_feature_collector_used_only_for_reviewed_missing_contexts(store):
    mapping, snapshot, _ = evidence('NBA')
    mapping.update(source_player_name=snapshot['participant'], canonical_event_name='Fixture Away @ Fixture Home')
    mapping['record_sha256'] = crosswalk_digest(mapping)
    calls = []
    class Collector:
        def sync(self, db, cards):
            calls.extend(cards)
            return int(db.append('player_feature_snapshot', 'fixture', snapshot, 'new-feature'))
    offers = [{'sport': SPORTS['NBA'], 'raw': quote('NBA')}]
    result = refresh_reviewed_features(store, 'NBA', offers, [mapping], [], Collector(),
        now=NOW, deadline=time.monotonic()+100, clock=time.monotonic, renew=lambda: True)
    assert result['attempted_contexts'] == result['archived_snapshots'] == 1
    assert calls[0].participant == snapshot['participant']
    assert calls[0].event_id == mapping['canonical_event_id']
    again = refresh_reviewed_features(store, 'NBA', offers, [mapping], [snapshot], Collector(),
        now=NOW, deadline=time.monotonic()+100, clock=time.monotonic, renew=lambda: True)
    assert again['attempted_contexts'] == 0 and len(calls) == 1
    invalid = {**mapping, 'independent_source_reviewed': False}
    rejected = refresh_reviewed_features(store, 'NBA', offers, [invalid], [], Collector(),
        now=NOW, deadline=time.monotonic()+100, clock=time.monotonic, renew=lambda: True)
    assert rejected['rejections'] == {'REVIEWED_MANIFEST_INVALID': 1}
    assert len(calls) == 1


@pytest.mark.parametrize('sport, expected', [('NBA', 2), ('NFL', 2), ('NHL', 0)])
def test_database_freezes_real_estimates_only_with_two_sided_baseline(store, sport, expected):
    mapping, snapshot, artifact = evidence(sport)
    offers = [{'sport': SPORTS[sport], 'raw': quote(sport)}]
    result = audit_exact_line_research(sport, offers, [mapping], [snapshot], [artifact],
                                      observed_at=NOW, include_research_rows=True)
    rows = result['research_rows']
    capture = freeze_two_sided_forecasts(store, rows, offers, [snapshot], now=NOW)
    assert capture['frozen'] == expected
    frozen = store.list_records('player_prospective_forecast', 10)
    assert len(frozen) == expected
    for item in frozen:
        value = item['payload']
        assert value['market_probability'] == .5
        assert value['probability'] in [r['model_probability'] for r in rows]
        assert not value['approved_for_betting']
        assert value['model_version'] == artifact['model_version']
    assert freeze_two_sided_forecasts(store, rows, offers, [snapshot], now=NOW)['frozen'] == 0
    assert store.list_records('player_prospective_result', 10) == []


def test_complete_pipeline_uses_durable_request_counters_and_private_snapshot(store):
    models = seed(store)
    provider = PaidProvider()
    report = run_paid_player_scan(store, SimpleNamespace(balldontlie_api_key='NOT_LOGGED',
        balldontlie_lab_api_key=''), models, lambda: True, now=NOW,
        limits=PaidScanLimits(requests=30, seconds=60, interval=0),
        provider_factory=lambda *a, **kw: provider, lab_reader=no_lab)
    assert report['scope_complete'] and report['paid_requests_made'] == 6
    assert len(store.list_records('paid_player_quote_snapshot', 10)) == 3
    assert len(store.list_records('player_prospective_forecast', 10)) == 4
    assert 'NOT_LOGGED' not in json.dumps([r['payload'] for r in store.list_records('paid_player_scan', 1)])


def test_scan_bridge_returns_paid_categories_and_rechecks_staleness(store):
    report, _, _ = run()
    scan_id = str(uuid4())
    bridge.submit(store, scan_id, now=NOW)
    payload = {'status': 'COMPLETE', 'actions': [], 'total_actions': 0, 'feeds_scanned': 3,
               'generated_at': NOW.isoformat(), 'errors': [],
               'event_market_coverage': {'paid_player_research': report}}
    store.append('chatgpt_scan_result', scan_id, payload, digest(['test', scan_id]))
    page = bridge.scan_page(store, scan_id, now=NOW)
    assert page.actions == []
    for sport in ('NBA', 'NFL', 'NHL'):
        result = page.player_probability_research['sports'][sport]
        assert result['returned'] == 1
        assert result['top10_by_market']
        assert result['top10'][0]['projected_mean'] is not None
        assert result['projected_totals_by_market']
        assert not result['top10'][0]['approved_for_betting']
    late = bridge.scan_page(store, scan_id, now=NOW+timedelta(minutes=3))
    assert all(not r['top10'] for r in late.player_probability_research['sports'].values())


@pytest.mark.parametrize('partial', [True, False])
def test_chat_bridge_terminal_status_includes_paid_coverage(monkeypatch, store, partial):
    from jabazi import api
    scan_id = str(uuid4())
    bridge.submit(store, scan_id, now=NOW)
    monkeypatch.setattr(bridge, 'store_factory', lambda: store)
    monkeypatch.setattr(store, 'close', lambda: None)
    monkeypatch.setattr(api, 'perform_scan', lambda *a, **kw: {
        'actions': [], 'feeds_scanned': 2, 'quotes_archived': 100, 'errors': [],
        'event_market_coverage': {'paid_player_research': {'requested': True, 'scope_complete': not partial}}})
    bridge.run_background(scan_id)
    payload = store.list_records('chatgpt_scan_result', 1, entity=scan_id)[0]['payload']
    assert payload['status'] == ('PARTIAL' if partial else 'COMPLETE')


def test_paid_config_faster_pacing_requires_explicit_verified_entitlement(monkeypatch):
    monkeypatch.setenv('JABBAZI_PAID_SCAN_INTERVAL_SECONDS', '1')
    monkeypatch.delenv('JABBAZI_PAID_SCAN_RATE_LIMIT_VERIFIED', raising=False)
    with pytest.raises(ValueError):
        PaidScanLimits.from_environment()
    monkeypatch.setenv('JABBAZI_PAID_SCAN_RATE_LIMIT_VERIFIED', 'true')
    monkeypatch.setenv('JABBAZI_PAID_SCAN_VERIFIED_REQUESTS_PER_MINUTE', '60')
    assert PaidScanLimits.from_environment().interval == 1
    monkeypatch.setenv('JABBAZI_PAID_SCAN_INTERVAL_SECONDS', '.5')
    with pytest.raises(ValueError):
        PaidScanLimits.from_environment()


def test_inference_budget_and_extreme_lines_fail_closed():
    mapping, snapshot, model = evidence('NBA')
    offers = [{'sport': SPORTS['NBA'], 'raw': quote('NBA')}]
    result = audit_exact_line_research('NBA', offers, [mapping], [snapshot], [model],
        observed_at=NOW, continue_check=lambda: False)
    assert result['rejections']['INFERENCE_TIME_OR_LEASE_BUDGET_EXHAUSTED'] == 1
    assert result['exact_line_research_estimates'] == 0
    answer = research_goat_exact_line('NBA', quote('NBA', line_value=1000000), mapping,
                                     snapshot, model, observed_at=NOW)
    assert answer['reason'] == 'UNSUPPORTED_EXACT_MARKET'


def test_acceptance_summary_does_not_call_empty_slate_paid_access():
    from tools.run_v7_paid_scan import summary
    report = {'scope_complete': True, 'sports': {'NBA': {'coverage': 'NO_ELIGIBLE_GAMES',
              'responded_games': 0, 'accepted_quotes': 0}}}
    assert not summary(report)['paid_endpoints_observed_for_requested_sports']
    report['sports']['NBA'].update(responded_games=1, accepted_quotes=20)
    assert summary(report)['paid_endpoints_observed_for_requested_sports']


def test_scan_operator_dry_run_does_not_access_database_or_provider(monkeypatch, capsys):
    from tools import run_v7_paid_scan as cli
    monkeypatch.setattr(cli.Settings, 'from_environment', lambda: SimpleNamespace(
        balldontlie_api_key='DO_NOT_LEAK', balldontlie_lab_api_key='DO_NOT_LEAK'))
    monkeypatch.setattr(cli, 'run_paid_player_scan', lambda *a, **kw: pytest.fail('Unexpected paid call'))
    from jabazi import api
    monkeypatch.setattr(api, 'platform_store', lambda: pytest.fail('Unexpected DB access'))
    assert cli.main([]) == 0
    output = capsys.readouterr().out
    assert 'DO_NOT_LEAK' not in output
    assert json.loads(output)['paid_requests_made'] == 0


def test_manifest_operator_dry_run_does_not_modify_attestations(monkeypatch, tmp_path, capsys):
    from tools import register_paid_identity_manifest as cli
    mapping, _, _ = evidence('NBA')
    path = tmp_path / 'reviewed.json'
    path.write_text(json.dumps([mapping]))
    original = path.read_bytes()
    class Clock:
        @staticmethod
        def now(tz):
            return NOW
    monkeypatch.setattr(cli, 'datetime', Clock)
    from jabazi import api
    monkeypatch.setattr(api, 'platform_store', lambda: pytest.fail('Dry-run must not access database'))
    assert cli.main(['--sport', 'NBA', '--input', str(path)]) == 0
    result = capsys.readouterr().out
    assert mapping['source_player_id'] not in result
    assert not json.loads(result)['committed']
    assert path.read_bytes() == original


@pytest.mark.parametrize('mode, called', [('full', True), ('quick', False), ('moneyline', False)])
def test_automatic_scanner_calls_paid_stage_only_for_full_mode(monkeypatch, store, mode, called):
    from jabazi import automation, paid_player_scan
    from jabazi.config import Settings
    from jabazi.models import player_registry
    monkeypatch.setattr(automation.AutomaticScanner, '_active_supported', lambda self: [])
    monkeypatch.setattr(automation, 'load_models', lambda db: ({}, []))
    monkeypatch.setattr(player_registry, 'load_player_models', lambda db: ({}, []))
    calls = []
    def collect(db, settings, models, renew, **kwargs):
        calls.append((db, kwargs))
        return {'requested': True, 'scope_complete': False, 'status': 'PARTIAL', 'sports': {}, 'betting_enabled': False}
    monkeypatch.setattr(paid_player_scan, 'run_paid_player_scan', collect)
    result = automation.AutomaticScanner(Settings.from_environment())._run(mode, store, 'test-owner')
    assert bool(calls) is called
    coverage = result.event_market_coverage['paid_player_research']
    assert coverage['requested'] is called
    if called:
        assert calls[0][0] is store
        assert calls[0][1]['feature_collector'] is not None
        assert calls[0][1]['deadline'] > time.monotonic()
    assert not result.errors


def test_archive_retains_versioned_distribution_not_sportsbook_line(store):
    from decimal import Decimal as D
    from jabazi.discord_sheets import archive_sheets
    from jabazi.vip.data import project
    distribution = {'market': 'player_points', 'model_version': 'fixture-v1', 'mean': 27.25}
    price = SimpleNamespace(sport=SPORTS['NBA'], event_id='EV', event='Away @ Home',
        market='player_points', participant='Fixture Player', selection='over', line=D('20.5'),
        best_book='fixture', best_decimal=D('1.91'), consensus_probability=D('.5'),
        source_timestamp=NOW, starts_at=START, executable=True, stale=False, in_play=False)
    action = SimpleNamespace(price=price, model_probability=D('.65'), model_version='fixture-v1',
        uncertainty=D('.05'), probability_edge=D('.15'), expected_roi=None, reason='Research',
        reliability={'model_stage': 'VALIDATING', 'player_distribution': distribution,
                     'research_priority_components': {'data_health': 1}})
    result = SimpleNamespace(actions=[action], errors=[], feeds_scanned=1, quotes_archived=2)
    archive_sheets(store, result, now=NOW)
    record = store.list_records('research_sheet', 1)[0]
    row = record['payload']['rows'][0]
    assert row['player_distribution'] == distribution
    # No independently reconciled slate supplied in this isolated projection fixture.
    record['payload'].pop('slate_events')
    visible = project(row, record, now=NOW)
    assert visible['projected_mean'] == 27.25
    assert visible['projected_mean'] != float(row['line'])
    assert not visible['approved_for_betting']
