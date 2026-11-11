"""Frozen NBA/NHL same-player benchmark forecasts, never wagering approval.

The existing immutable capture/settlement store remains the source of custody.
No model is refitted, no prices become probabilities, and no inputs are invented.
"""
from copy import deepcopy
from datetime import timedelta
from math import isfinite

from jabazi.boost_prospective import _at, _leg, _now, freeze_joint_ticket
from jabazi.models.player_distribution import raw_probability
from jabazi.models.player_joint import checkerboard_joint
from jabazi.persistence.store import digest
from jabazi.research.joint_player_fit import SPECS, fingerprint
from jabazi.research.player_features import REQUIRED_INTEGRITY


class FrozenJointResearchModel:
    def __init__(self, artifact, marginals, *, expected_sha256, fitted_at):
        self.artifact = deepcopy(artifact)
        self.marginals = deepcopy(marginals)
        a = self.artifact
        self.fitted_at = _at(fitted_at, 'artifact creation time')
        if (fingerprint(a) != expected_sha256 or a.get('sport') not in SPECS
                or a.get('artifact_type') != 'same_player_joint_research'
                or a.get('stage') != 'SHADOW_ONLY' or a.get('approved_for_betting') is not False):
            raise ValueError('Frozen research artifact identity required')
        markets = sorted({m for pair, _ in SPECS[a['sport']] for m in pair})
        if set(marginals) != set(markets):
            raise ValueError('Exact frozen marginal set required')
        fit_start = _at(a['fit_start'], 'fit start')
        test_start = _at(a['test_start'], 'test start')
        test_end = _at(a['test_end'], 'test end')
        if not fit_start < test_start < test_end <= self.fitted_at:
            raise ValueError('Invalid frozen model chronology')
        for market, marginal in self.marginals.items():
            if (marginal.get('sport') != a['sport'] or marginal.get('market') != market
                    or marginal.get('family') != 'count_nb' or marginal.get('calibration') is not None
                    or fingerprint(marginal) != a['sources'][market]['marginal_sha256']
                    or _at(marginal['training_cutoff'], 'marginal training') >= fit_start):
                raise ValueError('Marginal artifact does not match frozen joint fit')
        identity = {'sport': a['sport'], 'fit_start': fit_start.isoformat(),
                    'fit_end': test_start.isoformat(),
                    'marginals': {m: fingerprint(self.marginals[m]) for m in markets},
                    'buckets': [{k: b.get(k) for k in ('markets', 'ranks', 'benchmark_lines')}
                                for b in a['buckets']]}
        if a['model_version'] != a['sport']+'-joint-research-'+fingerprint(identity)[:12]:
            raise ValueError('Frozen joint version mismatch')
        self.buckets = {}
        for b in a['buckets']:
            pair = tuple(b['markets'])
            if (pair, tuple(b['benchmark_lines'])) not in SPECS[a['sport']] or pair in self.buckets:
                raise ValueError('Unexpected or duplicate research bucket')
            if b['status'] != 'HISTORICAL_RESEARCH_FIT':
                continue
            ranks = b['ranks']
            n = len(ranks)
            if (type(b['training_unique_games']) is not int or type(b['test_unique_games']) is not int
                    or min(b['training_unique_games'], b['test_unique_games']) < 200
                    or n != b['training_pairs'] or n < b['training_unique_games']
                    or any(not isinstance(row, list) or len(row) != 2 for row in ranks)):
                raise ValueError('Independent training/test support required')
            if any(type(v) is not int for row in ranks for v in row):
                raise ValueError('Integer rank support required')
            if any(sorted(row[axis] for row in ranks) != list(range(n)) for axis in (0, 1)):
                raise ValueError('Rank support is not a permutation')
            self.buckets[pair] = b

    def ticket(self, snapshots, *, now=None, offered_quote=None):
        now = _now(now)
        if self.fitted_at >= now or len(snapshots) != 2:
            raise ValueError('Completed fit and two fresh player snapshots required')
        snapshots = deepcopy(snapshots)
        pair = tuple(s.get('market') for s in snapshots)
        if pair not in self.buckets:
            raise ValueError('Unsupported ordered market pair')
        b = self.buckets[pair]
        first = snapshots[0]
        for s in snapshots:
            canonical = {k: v for k, v in s.items() if k not in ('snapshot_id', 'archived_at')}
            if s.get('snapshot_id') != 'playerfs-'+fingerprint(canonical)[:20]:
                raise ValueError('Feature snapshot fingerprint mismatch')
            if (s.get('sport') != self.artifact['sport'] or not s.get('player_id')
                    or not s.get('event_id') or not s.get('source_checksum')
                    or any(s.get(k) != first.get(k) for k in ('player_id', 'event_id', 'starts_at', 'roster_version'))
                    or s.get('production_inputs_verified') is not True
                    or s.get('research_only') is not False
                    or not all(s.get('integrity', {}).get(k) is True for k in REQUIRED_INTEGRITY)):
                raise ValueError('Verified same-player same-event inputs required')
            if 'sportsdataio' in str(s.get('provider', '')).lower() and s.get('provider_data_verified') is not True:
                raise ValueError('Provider authenticity unavailable')
            start = _at(s['starts_at'], 'event start')
            available = _at(s['features_available_at'], 'feature availability')
            archived = _at(s['archived_at'], 'feature archive')
            if not available <= archived <= now < start or now-available > timedelta(minutes=10):
                raise ValueError('Stale, future or in-play feature snapshot')
            if not s.get('features') or any(type(x) not in (int, float) or not isfinite(x) for x in s['features'].values()):
                raise ValueError('Finite observed features required')
        lines = b['benchmark_lines']
        legs = [_leg({'leg_id': digest([s['player_id'], m, line, 'over'])[:24],
                      'player_id': s['player_id'], 'market': m, 'side': 'over', 'line': line})
                for s, m, line in zip(snapshots, pair, lines)]
        ps = [raw_probability(self.marginals[m], s['features'], 'over', line)
              for s, m, line in zip(snapshots, pair, lines)]
        # Single-ticket inference uses the exact dependency-free evaluator.
        # NumPy is a training acceleration, not a production runtime dependency.
        probability = checkerboard_joint(b['ranks'], ps, [True, True])
        if not isfinite(probability) or not 0 < probability < 1:
            raise ValueError('Degenerate forecast cannot be frozen')
        version = self.artifact['model_version']
        ticket_id = digest(['same-player-benchmark-v1', first['event_id'], legs, version])
        evidence = {'event_id': first['event_id'], 'ticket_id': ticket_id,
                    'model_version': version, 'joint_probability': probability,
                    'leg_ids': [l['leg_id'] for l in legs], 'legs': legs,
                    'features_available_at': max(_at(s['features_available_at'], 'features') for s in snapshots).isoformat(),
                    'artifact_sha256': fingerprint(self.artifact),
                    'artifact_fitted_at': self.fitted_at.isoformat(),
                    'feature_snapshot_ids': [s['snapshot_id'] for s in snapshots],
                    'marginal_probabilities': ps, 'benchmark_only': True}
        result = {'sport': self.artifact['sport'], 'event_id': first['event_id'],
                  'ticket_id': ticket_id, 'model_version': version, 'split': 'prospective',
                  'trained_through': (_at(self.artifact['test_start'], 'test start')-timedelta(microseconds=1)).isoformat(),
                  'test_start': self.artifact['test_start'], 'prospective_start': self.fitted_at.isoformat(),
                  'starts_at': first['starts_at'], 'joint_probability': probability, 'legs': legs,
                  'model_source': {'provider': 'frozen_same_player_joint_research',
                                   'observed_at': now.isoformat(), 'payload': evidence}}
        if offered_quote is not None:
            result['offered_quote'] = deepcopy(offered_quote)
        return result

    def freeze(self, store, snapshots, *, now=None, offered_quote=None):
        now = _now(now)
        return freeze_joint_ticket(store, self.ticket(snapshots, now=now,
                                  offered_quote=offered_quote), observed_at=now)
