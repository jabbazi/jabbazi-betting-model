"""Offline, reproducible NFL scoring-opportunity ATD challenger. Never registers models."""
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import UTC, datetime, timedelta
import gzip
import hashlib
import json
from pathlib import Path

import numpy as np
from sklearn.linear_model import LogisticRegression

from jabazi.models.player_calibration import apply_calibration
from jabazi.models.player_distribution import raw_probability
from jabazi.research.calibration_report import report
from tools.capture_nfl_context import schedule_rows
from tools.capture_nfl_player_props import build_features, parse_asset

TRAIN_END = datetime(2024, 1, 1, tzinfo=UTC)
CAL_END = datetime(2025, 1, 1, tzinfo=UTC)
TEST_END = datetime(2026, 1, 1, tzinfo=UTC)


def stamp(value):
    dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if dt.tzinfo is None:
        raise ValueError('Aware timestamp required')
    return dt.astimezone(UTC)


def available(rows, decision):
    return [r for r in rows if stamp(r['starts_at']) + timedelta(days=2) < decision]


def mean(rows, field, n):
    part = rows[-n:]
    return sum(r[field] for r in part) / len(part) if part else 0.0


def features(prior, team, opponent, row):
    """Only called with already available prior results; no outcome from row is read."""
    f = {f'{field}_mean{n}': mean(prior, field, n)
         for field in ('carries', 'targets', 'rushing_tds', 'receiving_tds') for n in (3, 8)}
    f.update({f'{field}_mean8': mean(team, field, 8)
              for field in ('team_tds', 'team_touches')})
    f['opponent_allowed_tds_mean8'] = mean(opponent, 'allowed_tds', 8)
    f['carry_share_mean3'] = mean(prior, 'carry_share', 3)
    f['target_share_mean3'] = mean(prior, 'target_share', 3)
    f['prior_sample_count'] = float(len(prior))
    f['team_sample_count'] = float(min(8, len(team)))
    f['opponent_sample_count'] = float(min(8, len(opponent)))
    f['is_home'] = float(row['is_home'])
    f['new_season'] = float(prior[-1]['season'] != row['season'])
    f['days_since_appearance'] = float((stamp(row['starts_at']) - stamp(prior[-1]['starts_at'])).days)
    for p in ('QB', 'RB', 'WR', 'TE'):
        f['position_' + p.lower()] = float(row['position'] == p)
    return f


def build_rows(source, schedule):
    """Group each game's players before updating history. Reject ambiguous identities."""
    grouped = defaultdict(list)
    seen = set()
    for r in source:
        if r['season'] > 2025 or stamp(r['starts_at']) >= TEST_END:
            continue
        key = (r['event_id'], r['player_id'])
        if key in seen:
            raise ValueError('Duplicate player/game')
        seen.add(key)
        g = schedule[r['event_id']]
        if (r['team'], r['opponent']) not in {
            (g['home_team'], g['away_team']), (g['away_team'], g['home_team'])
        }:
            raise ValueError('Player/opponent schedule mismatch')
        if r['is_home'] != (r['team'] == g['home_team']) or r['starts_at'] != g['starts_at']:
            raise ValueError('Player home/away or start mismatch')
        if r['season'] != int(g['season']) or r['week'] != int(g['week']):
            raise ValueError('Player season/week mismatch')
        if g.get('home_score') in ('', None) or g.get('away_score') in ('', None):
            continue
        grouped[r['event_id']].append(dict(r))
    players, teams, out = defaultdict(list), defaultdict(list), []
    for gid in sorted(grouped, key=lambda x: (schedule[x]['starts_at'], x)):
        rows = grouped[gid]
        aggregates = {}
        for t in (schedule[gid]['home_team'], schedule[gid]['away_team']):
            members = [r for r in rows if r['team'] == t]
            aggregates[t] = {
                'carries': sum(r['carries'] for r in members),
                'targets': sum(r['targets'] for r in members),
                'team_tds': sum(r['rushing_tds'] + r['receiving_tds'] for r in members),
                'starts_at': rows[0]['starts_at'],
            }
            aggregates[t]['team_touches'] = aggregates[t]['carries'] + aggregates[t]['targets']
        for r in rows:
            a = aggregates[r['team']]
            r['carry_share'] = r['carries'] / a['carries'] if a['carries'] else 0.0
            r['target_share'] = r['targets'] / a['targets'] if a['targets'] else 0.0
            decision = stamp(r['starts_at']) - timedelta(hours=1)
            prior = available(players[r['player_id']], decision)[-32:]
            if len(prior) >= 3 and mean(prior, 'touch_opportunities', 3) >= 2:
                team = available(teams[r['team']], decision)
                opp = available(teams[r['opponent']], decision)
                out.append({
                    'event_id': gid, 'player_id': r['player_id'], 'position': r['position'],
                    'starts_at': r['starts_at'], 'prediction_at': decision.isoformat(),
                    'result_available_at': (stamp(r['starts_at']) + timedelta(days=2)).isoformat(),
                    'feature_history_cutoff': max(stamp(p['starts_at']) + timedelta(days=2)
                        for p in [*prior, *team, *opp]).isoformat(),
                    'features': features(prior, team, opp, r),
                    'baseline_features': build_features([p['anytime_td'] for p in prior],
                        [p['touch_opportunities'] for p in prior], r['position'], r['is_home']),
                    'outcome': int(r['anytime_td']),
                })
        # Only after all predictions for the game have been materialized.
        for r in rows:
            players[r['player_id']].append(r)
        home, away = schedule[gid]['home_team'], schedule[gid]['away_team']
        for t, opp in ((home, away), (away, home)):
            teams[t].append(aggregates[t] | {'allowed_tds': aggregates[opp]['team_tds']})
    return out


def split_rows(rows):
    result = {p: [] for p in ('train', 'calibration', 'test')}
    groups = {}
    for row in rows:
        start = stamp(row['starts_at'])
        decision = stamp(row['prediction_at'])
        if stamp(row['feature_history_cutoff']) >= decision or decision >= start:
            raise ValueError('Feature look-ahead')
        p = 'train' if start < TRAIN_END else 'calibration' if start < CAL_END else 'test'
        if row['event_id'] in groups and groups[row['event_id']] != (start, p):
            raise ValueError('Game crosses chronological partition')
        groups[row['event_id']] = (start, p)
        end = {'train': TRAIN_END, 'calibration': CAL_END, 'test': TEST_END}[p]
        if stamp(row['result_available_at']) < end:
            result[p].append(row)
    return result


def fit_challenger(train, calibration):
    names = sorted(train[0]['features'])
    x = np.array([[r['features'][k] for k in names] for r in train])
    center, scale = x.mean(axis=0), x.std(axis=0)
    scale[scale < 1e-9] = 1
    weights = np.array([2 ** (-(TRAIN_END - stamp(r['prediction_at'])).days / 365) for r in train])
    fit = LogisticRegression(C=0.2, max_iter=3000).fit((x-center)/scale,
        [r['outcome'] for r in train], sample_weight=weights)
    artifact = {
        'artifact_type': 'player_prop_distribution', 'artifact_schema_version': 3,
        'sport': 'americanfootball_nfl', 'market': 'player_anytime_td',
        'family': 'binary_logistic', 'feature_names': names,
        'scaler': {'mean': center.tolist(), 'scale': scale.tolist()},
        'parameters': {'coef': fit.coef_[0].tolist(), 'intercept': float(fit.intercept_[0])},
        'stage': 'SHADOW_ONLY', 'training_cutoff': TRAIN_END.isoformat(),
        'calibration_cutoff': CAL_END.isoformat(), 'approved_for_betting': False,
        'target': 'at_least_one_rushing_or_receiving_td_conditional_on_stat_archive_presence',
        'live_feature_adapter_available': False,
    }
    p = np.array([raw_probability(artifact, r['features'], 'yes', .5) for r in calibration])
    logits = np.log(np.clip(p, 1e-8, 1-1e-8) / np.clip(1-p, 1e-8, 1))[:, None]
    c = LogisticRegression(C=1.0, max_iter=3000).fit(logits, [r['outcome'] for r in calibration])
    if c.coef_[0, 0] < 0:
        raise ValueError('Non-monotone calibrator; challenger rejected')
    artifact['calibration'] = {'method': 'platt', 'orientation': 'positive',
        'slope': float(c.coef_[0, 0]), 'intercept': float(c.intercept_[0])}
    payload = json.dumps(artifact, sort_keys=True, separators=(',', ':')).encode()
    artifact['model_version'] = 'nfl-atd-opportunity-logistic-0.1.0-' + hashlib.sha256(payload).hexdigest()[:12]
    return artifact


def paired_interval(rows, field):
    groups = defaultdict(list)
    for r in rows:
        groups[r['event_id']].append((r[field]-r['outcome'])**2 - (r['baseline']-r['outcome'])**2)
    # Equal-game weighting; players within each game remain together.
    values = np.array([np.mean(v) for v in groups.values()])
    rng = np.random.default_rng(20260928)
    samples = [values[rng.integers(len(values), size=len(values))].mean() for _ in range(500)]
    return {'independent_games': len(values), 'equal_game_mean_difference': float(values.mean()),
            'interval_95': np.quantile(samples, [.025, .975]).tolist(),
            'method': 'paired_game_cluster_bootstrap_500_equal_game_weight'}


def run(raw_dir, output):
    manifest_path = Path('docs/experiments/nfl-player-props/request.json')
    request = json.loads(manifest_path.read_text())
    receipts, source = [], []
    schedule = schedule_rows((raw_dir/'games.csv').read_text(), set(range(2021, 2026)))
    for a in request['assets']:
        if a['season'] > 2025:
            continue
        path = raw_dir/a['filename']
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != a['sha256']:
            raise ValueError('Source checksum mismatch')
        receipts.append({'file': a['filename'], 'sha256': actual, 'url': a['url']})
        source.extend(parse_asset(path, schedule))
    rows = build_rows(source, schedule)
    parts = split_rows(rows)
    artifact = fit_challenger(parts['train'], parts['calibration'])
    base_path = Path('models/player_props/americanfootball_nfl/player_anytime_td.json')
    baseline = json.loads(base_path.read_text())
    if stamp(baseline['split_policy']['test_before']) > CAL_END:
        raise ValueError('Baseline calibration extends into evaluation window')
    predictions = []
    for row in parts['test']:
        raw = raw_probability(artifact, row['features'], 'yes', .5)
        old = raw_probability(baseline, row['baseline_features'], 'yes', .5)
        predictions.append(row | {'baseline': apply_calibration(old, baseline.get('calibration')),
            'challenger_raw': raw, 'challenger_calibrated': apply_calibration(raw, artifact['calibration'])})
    fields = ('baseline', 'challenger_raw', 'challenger_calibrated')
    metrics = {f: report([r[f] for r in predictions], [r['outcome'] for r in predictions]) for f in fields}
    positions = {}
    for pos in sorted({r['position'] for r in predictions}):
        selected = [r for r in predictions if r['position'] == pos]
        positions[pos] = {f: report([r[f] for r in selected], [r['outcome'] for r in selected]) for f in fields}
    summary = {
        'model_version': artifact['model_version'], 'approved_for_betting': False, 'stage': 'SHADOW_ONLY',
        'baseline_version': baseline['model_version'], 'evaluation': 'retrospective_2025_matched_games',
        'counts': {k: {'player_games':len(v), 'games':len({r['event_id'] for r in v})} for k,v in parts.items()},
        'metrics': metrics, 'by_position': positions,
        'paired_difference': {f: paired_interval(predictions, f) for f in fields[1:]},
        'market_baseline': None, 'clv': None, 'roi': None,
        'source_receipts': receipts,
        'schedule_sha256': hashlib.sha256((raw_dir/'games.csv').read_bytes()).hexdigest(),
        'baseline_sha256': hashlib.sha256(base_path.read_bytes()).hexdigest(),
        'code_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'limitations': [
            'No prospective or sportsbook-priced sample; no independent betting edge established.',
            'Availability is reconstructed at scheduled start plus two days, not original receipt time.',
            'Current-game participation and position are retrospectively recorded; no pregame injury/active roster archive.',
            'Population is players present in stat archive with prior usage; omissions can bias calibration.',
            'Target covers rushing/receiving TDs, not return/recovery TDs; general anytime settlement unverified.',
            'No red-zone/goal-line/end-zone usage, current projected snaps, or verified live feature adapter.',
            'Row-wise reliability intervals are descriptive; paired comparison uses whole-game clusters.',
            '2025 period overlaps earlier examinations and is not an untouched confirmatory test.',
        ],
    }
    output.mkdir(parents=True, exist_ok=True)
    for name, doc in [('artifact', artifact), ('report', summary)]:
        (output/f'{name}.json').write_text(json.dumps(doc, indent=2, allow_nan=False)+'\n')
    frozen = json.dumps(predictions, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
    (output/'predictions.json.gz').write_bytes(gzip.compress(frozen, mtime=0))
    print(json.dumps({'counts':summary['counts'], 'metrics':{f:{k:v for k,v in m.items() if k in ('n','brier','log_loss','ece')} for f,m in metrics.items()}, 'paired':summary['paired_difference']}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--raw-dir', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    run(args.raw_dir, args.output)
