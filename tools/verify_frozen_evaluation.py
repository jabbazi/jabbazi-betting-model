"""Re-score committed frozen predictions; never refit or claim a new holdout."""
import gzip
import hashlib
import json
from pathlib import Path

from jabazi.research.rolling_upgrade import labels
from jabazi.research.calibration_report import report


def verify(root):
    result = {}
    for sport in ('nfl', 'mlb', 'cfb'):
        directory = root / 'docs/experiments/reliability-upgrade' / sport
        source = directory / 'predictions.json.gz'
        frozen = json.loads(gzip.decompress(source.read_bytes()))
        saved = json.loads((directory / 'report.json').read_text())
        checked = {}
        for model, rows in frozen.items():
            markets = {}
            for market in saved['results'][model]:
                eligible = [r for r in rows if labels(r['game'], sport)[market] is not None]
                metrics = report([r['raw'][market] for r in eligible],
                                 [labels(r['game'], sport)[market] for r in eligible])
                expected = saved['results'][model][market]['raw']
                for key in ('n', 'brier', 'log_loss'):
                    if abs(metrics[key] - expected[key]) > 1e-9:
                        raise ValueError(f'Frozen metric mismatch: {sport}/{model}/{market}/{key}')
                markets[market] = metrics
            checked[model] = markets
        result[sport] = {'prediction_archive_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
                         'results': checked, 'verification': 'PASS',
                         'scope': 'Re-scored existing retrospective frozen predictions; not a new fit or untouched holdout',
                         'roi': None, 'clv': None}
    return result


if __name__ == '__main__':
    print(json.dumps(verify(Path(__file__).resolve().parents[1]), indent=2, allow_nan=False))
