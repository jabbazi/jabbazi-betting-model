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
    for relative, checksum in manifest['unchanged'].items():
        assert source_digest(relative, followup['files']) == checksum, relative
    assert not (ROOT / 'src/jabazi/paid_player_scan.py').exists()
    assert not (ROOT / 'src/jabazi/scan_paid_research.py').exists()
    from jabazi.vip import paid_models
    assert not hasattr(paid_models, 'read_paid_player_models')
    assert not hasattr(paid_models, 'LabReader')
