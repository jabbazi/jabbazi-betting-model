"""Isolated runner control-flow tests; not provider or production acceptance."""
import importlib.util
import json
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock

import pytest


PRIVATE_MARKER = "test-only-private-database-or-provider-secret"


@pytest.fixture
def runner(monkeypatch):
    # Isolate infrastructure imports so these tests cannot open real connections,
    # use configured secrets, consume provider quota, or mutate other test state.
    for name in ("jabazi", "jabazi.models", "jabazi.providers"):
        package = ModuleType(name)
        package.__path__ = []
        monkeypatch.setitem(sys.modules, name, package)

    settings = SimpleNamespace(
        balldontlie_api_key=PRIVATE_MARKER,
        balldontlie_lab_api_key=PRIVATE_MARKER,
        sportsdataio_api_key=PRIVATE_MARKER,
    )
    limits = SimpleNamespace(requests=90, seconds=180)
    store = Mock()
    store.acquire_lease.return_value = True
    model_loader = Mock(return_value=({}, []))
    report = {
        "status": "RESEARCH_ONLY", "scope_complete": True,
        "collection_complete": True, "model_scope_complete": True,
        "paid_requests_made": 3,
        "sports": {"NBA": {"responded_games": 1, "accepted_quotes": 2}},
    }
    scan = Mock(return_value=report)
    factory = Mock(return_value=store)
    settings_type = SimpleNamespace(from_environment=Mock(return_value=settings))
    limits_type = SimpleNamespace(from_environment=Mock(return_value=limits))
    collector = Mock()
    modules = {
        "jabazi.config": {"Settings": settings_type},
        "jabazi.models.player_registry": {"load_player_models": model_loader},
        "jabazi.paid_player_scan": {
            "PaidScanLimits": limits_type, "run_paid_player_scan": scan,
        },
        "jabazi.providers.player_features_live": {"LivePlayerFeatureCollector": collector},
        "jabazi.api": {"platform_store": factory},
    }
    for name, attributes in modules.items():
        module = ModuleType(name)
        module.__dict__.update(attributes)
        monkeypatch.setitem(sys.modules, name, module)
    path = Path(__file__).resolve().parents[1] / "tools" / "run_v7_paid_scan.py"
    spec = importlib.util.spec_from_file_location("_v7_runner_cleanup_under_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return SimpleNamespace(
        module=module, store=store, scan=scan, factory=factory, settings=settings_type,
        limits=limits_type, models=model_loader, collector=collector, report=report,
    )


def result(runner, capsys, args=None):
    code = runner.module.main(["--sport", "NBA", "--execute"] if args is None else args)
    captured = capsys.readouterr()
    assert captured.err == ""
    assert len(captured.out.splitlines()) == 1
    assert PRIVATE_MARKER not in captured.out
    payload = json.loads(captured.out)
    assert payload["production_approved"] is False
    return code, payload


def test_dry_run_never_opens_database_or_calls_providers(runner, capsys):
    code, payload = result(runner, capsys, [])
    assert code == 0 and payload["mode"] == "DRY_RUN"
    assert payload["paid_requests_made"] == 0 and payload["database_writes"] is False
    runner.factory.assert_not_called()
    runner.scan.assert_not_called()


@pytest.mark.parametrize("stage", ["limits", "settings", "factory", "lease", "models", "scan"])
def test_stage_errors_are_sanitized_and_cleanup_is_bounded(runner, capsys, stage):
    targets = {
        "limits": runner.limits.from_environment,
        "settings": runner.settings.from_environment,
        "factory": runner.factory, "lease": runner.store.acquire_lease,
        "models": runner.models, "scan": runner.scan,
    }
    targets[stage].side_effect = RuntimeError(PRIVATE_MARKER)
    code, payload = result(runner, capsys)
    assert code == 2
    assert payload["reason"] == "V7_PRIVATE_ACCEPTANCE_FAILED"
    if stage in ("lease", "models", "scan"):
        runner.store.close.assert_called_once_with()
    else:
        runner.store.close.assert_not_called()
    if stage in ("models", "scan"):
        runner.store.release_lease.assert_called_once()
    else:
        runner.store.release_lease.assert_not_called()
    if stage != "scan":
        runner.scan.assert_not_called()


def test_busy_scanner_does_not_release_an_unowned_lease(runner, capsys):
    runner.store.acquire_lease.return_value = False
    code, payload = result(runner, capsys)
    assert code == 1 and payload["reason"] == "SCANNER_BUSY"
    runner.store.release_lease.assert_not_called()
    runner.store.close.assert_called_once_with()
    runner.scan.assert_not_called()


@pytest.mark.parametrize("release_fails,close_fails", [(True, False), (False, True), (True, True)])
@pytest.mark.parametrize("scan_fails", [False, True])
def test_cleanup_errors_never_escape_or_print_false_success(
    runner, capsys, release_fails, close_fails, scan_fails,
):
    if release_fails:
        runner.store.release_lease.side_effect = RuntimeError(PRIVATE_MARKER)
    if close_fails:
        runner.store.close.side_effect = RuntimeError(PRIVATE_MARKER)
    if scan_fails:
        runner.scan.side_effect = RuntimeError(PRIVATE_MARKER)
    code, payload = result(runner, capsys)
    assert code == 2 and payload["status"] == "UNAVAILABLE"
    expected = "V7_PRIVATE_ACCEPTANCE_FAILED" if scan_fails else "V7_PRIVATE_CLEANUP_FAILED"
    assert payload["reason"] == expected
    assert payload["cleanup_errors"] == (
        (["LEASE_RELEASE_FAILED"] if release_fails else [])
        + (["STORE_CLOSE_FAILED"] if close_fails else [])
    )
    runner.store.close.assert_called_once_with()
    if not scan_fails:
        assert payload["paid_requests_made"] == 3
        assert payload["joint_calibration_validated"] is False


@pytest.mark.parametrize("busy", [False, True])
def test_close_failure_after_unacquired_lease_is_sanitized(runner, capsys, busy):
    if busy:
        runner.store.acquire_lease.return_value = False
    else:
        runner.store.acquire_lease.side_effect = RuntimeError(PRIVATE_MARKER)
    runner.store.close.side_effect = RuntimeError(PRIVATE_MARKER)
    code, payload = result(runner, capsys)
    assert code == 2 and payload["status"] == "UNAVAILABLE"
    assert payload["reason"] == ("SCANNER_BUSY" if busy else "V7_PRIVATE_ACCEPTANCE_FAILED")
    assert payload["cleanup_errors"] == ["STORE_CLOSE_FAILED"]
    runner.store.release_lease.assert_not_called()
    runner.scan.assert_not_called()


def test_success_is_printed_only_after_cleanup_and_keeps_research_gates(runner, capsys):
    def check_output_is_not_printed_yet(*_):
        assert capsys.readouterr().out == ""
    runner.store.release_lease.side_effect = check_output_is_not_printed_yet
    runner.store.close.side_effect = check_output_is_not_printed_yet
    code, payload = result(runner, capsys)
    assert code == 0 and payload["scope_complete"] is True
    assert payload["betting_enabled"] is False
    assert payload["joint_calibration_validated"] is False
    assert payload["model_load_error_count"] == 0
    assert "cleanup_errors" not in payload
    acquired = runner.store.acquire_lease.call_args.args
    runner.store.release_lease.assert_called_once_with("scanner", acquired[1])
    runner.store.close.assert_called_once_with()


@pytest.mark.parametrize("complete,quotes", [(False, 2), (True, 0), (False, 0)])
def test_partial_or_empty_scans_cannot_pass(runner, capsys, complete, quotes):
    runner.report["scope_complete"] = complete
    runner.report["sports"]["NBA"]["accepted_quotes"] = quotes
    code, _ = result(runner, capsys)
    assert code == 1
    runner.store.close.assert_called_once_with()


def test_interrupt_propagates_but_cleanup_still_runs(runner, capsys):
    runner.scan.side_effect = KeyboardInterrupt
    runner.store.release_lease.side_effect = RuntimeError(PRIVATE_MARKER)
    runner.store.close.side_effect = RuntimeError(PRIVATE_MARKER)
    with pytest.raises(KeyboardInterrupt):
        runner.module.main(["--execute"])
    runner.store.release_lease.assert_called_once()
    runner.store.close.assert_called_once_with()
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize("field", ["status", "errors"])
def test_unserializable_report_remains_sanitized(runner, capsys, field):
    if field == "status":
        runner.report["status"] = object()
    else:
        runner.report["sports"]["NBA"]["errors"] = [object()]
    code, payload = result(runner, capsys)
    assert code == 2 and payload["reason"] == "V7_PRIVATE_ACCEPTANCE_FAILED"
    runner.store.release_lease.assert_called_once()
    runner.store.close.assert_called_once_with()
