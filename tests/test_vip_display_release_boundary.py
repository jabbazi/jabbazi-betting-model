"""Freeze original release inputs, with exact reviewed routing-only follow-up files."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def source_digest(relative, reviewed=None):
    path = ROOT / relative
    files = sorted(p for p in path.rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix != '.pyc') if path.is_dir() else [path]
    manifest = []
    for p in files:
        name = p.relative_to(ROOT).as_posix()
        checksum = hashlib.sha256(p.read_bytes()).hexdigest()
        if name in (reviewed or {}):
            assert checksum == reviewed[name]['after'], name
            checksum = reviewed[name]['before']
            if checksum is None:  # Explicitly fingerprinted new file, absent in baseline.
                continue
        manifest.append((name, checksum))
    return hashlib.sha256(json.dumps(manifest, separators=(',', ':')).encode()).hexdigest()


def test_display_release_does_not_change_scanner_auth_models_or_schedules():
    manifest = json.loads((ROOT / 'docs/vip_display_release_boundary.json').read_text())
    assert manifest['base_commit'] == 'c5caee3dfd0ecb4523b54b943a54d6f89de0b2f5'
    followup = manifest['reviewed_routing_followup']
    assert followup['base_commit'] == '7dc640132563c6717c3926b21972bc85bba36685'
    assert set(followup['files']) == {
        'src/jabazi/models/nhl_goals.py', 'src/jabazi/models/player_distribution.py',
        'src/jabazi/reliability/layer.py', 'src/jabazi/api.py', 'src/jabazi/chatgpt_api.py'}
    v7 = manifest['reviewed_v7_integration']
    assert v7['base_commit'] == 'b92b2ccde73d4a31d4330f394375baedf617b243'
    assert set(v7['files']) == {
        'src/jabazi/automation.py', 'src/jabazi/config.py',
        'src/jabazi/providers/balldontlie.py',
        'src/jabazi/models/player_distribution.py', 'src/jabazi/chatgpt_api.py',
    }
    reviewed = dict(followup['files'])
    digest_drift = {}
    for path, hashes in v7['files'].items():
        current = hashlib.sha256((ROOT / path).read_bytes()).hexdigest()
        if current != hashes['after']:
            digest_drift[path] = {'actual': current, 'expected': hashes['after']}
        if path in reviewed:
            assert hashes['before'] == reviewed[path]['after'], path
            reviewed[path] = {'before': reviewed[path]['before'],
                              'after': hashes['after']}
        else:
            reviewed[path] = hashes
    assert not digest_drift, sorted(digest_drift)
    nhl = manifest['nhl_injury_parser_remediation']
    assert nhl['base_commit'] == '27f6d78cf193a8f66774b52a98ac6c2067761fe5'
    assert set(nhl['files']) == {'src/jabazi/providers/nhl_player_features.py'}
    reviewed.update(nhl['files'])
    nba = manifest['nba_live_input_remediation']
    assert nba['base_commit'] == '716854d73235651df19c4c2074ce3a19439a755f'
    assert set(nba['files']) == {'src/jabazi/providers/nba_player_features.py'}
    reviewed.update(nba['files'])
    quote = manifest['draftkings_quote_research_addition']
    assert quote['base_commit'] == '2139914bb6ba5810dac8a012ce7ed59f4d9c1ec5'
    assert set(quote['files']) == {'src/jabazi/providers/opticodds_sgp.py'}
    assert quote['files']['src/jabazi/providers/opticodds_sgp.py']['before'] is None
    reviewed.update(quote['files'])
    for relative, checksum in manifest['unchanged'].items():
        assert source_digest(relative, reviewed) == checksum, relative
    assert (ROOT / 'src/jabazi/paid_player_scan.py').is_file()
    assert not (ROOT / 'src/jabazi/scan_paid_research.py').exists()
    from jabazi.vip import paid_models
    assert hasattr(paid_models, 'saved_paid_player_models')
    assert hasattr(paid_models, 'read_paid_player_models')
    # Approval is not implied: only an exact opt-in full scan can enter V7.
    source = (ROOT / 'src/jabazi/automation.py').read_text()
    assert 'JABBAZI_PAID_PLAYER_SCAN_ENABLED' in source
    assert 'if mode == "full" and paid_enabled' in source
