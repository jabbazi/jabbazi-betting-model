"""Cloud entry points with bounded schedules and no credential output."""

import argparse
import json
import os
import signal
import subprocess
import sys
import threading
import time
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from .config import Settings
from .persistence.store import Store


def configuration():
    settings = Settings.from_environment()
    url = os.getenv("JABBAZI_PLATFORM_DATABASE_URL", "")
    problems = []
    if os.getenv("JABAZI_ENV") == "production" and not os.getenv("JABAZI_BANKROLL", "").strip():
        problems.append("Production requires an explicit JABAZI_BANKROLL")
    if not url:
        problems.append("JABBAZI_PLATFORM_DATABASE_URL missing")
    if os.getenv("JABAZI_ENV") == "production" and not url.startswith(
        ("postgres://", "postgresql://", "postgresql+psycopg://")
    ):
        problems.append("Production requires PostgreSQL")
    if len(settings.service_token) < 32:
        problems.append("JABBAZI_MODEL_TOKEN must have at least 32 characters")
    for label, value in (("bankroll", settings.bankroll), ("unit_size", settings.unit_size)):
        if not value.is_finite() or value <= 0:
            problems.append(label + " must be positive and finite")
    settings.portfolio_limits()
    return settings, url, problems


def doctor():
    try:
        settings, url, problems = configuration()
    except Exception:
        return {"status": "INVALID_CONFIGURATION", "betting_enabled": False}
    database = "unavailable"
    if url:
        store = None
        try:
            store = Store(url)
            database = "ready" if store.ready() else "migration_required"
        except Exception:
            pass
        finally:
            if store:
                store.close()
    return {
        "status": "READY_FOR_RESEARCH"
        if not problems and database == "ready"
        else "SETUP_REQUIRED",
        "database": database,
        "configuration_errors": problems,
        "betting_enabled": False,
        "odds_provider_configured": bool(settings.api_key),
        "cfb_provider_configured": bool(os.getenv("JABBAZI_CFBD_API_KEY")),
        "player_context_provider_configured": bool(settings.sportsdataio_api_key),
        "player_context_provider": "SportsDataIO" if settings.sportsdataio_api_key else None,
        "discord_enabled": os.getenv("JABBAZI_DISCORD_REVIEW_ENABLED", "false").lower() == "true",
    }


def worker(*, once=False):
    from .automation import AutomaticScanner
    from .operations import ClosingCollector

    settings, url, problems = configuration()
    if problems:
        raise ValueError("; ".join(problems))
    store = Store(url)
    stop = threading.Event()
    if threading.current_thread() is threading.main_thread():
        for sig in (signal.SIGTERM, signal.SIGINT):
            def handle_stop(signum, _frame):
                print("WORKER_STOP_SIGNAL_" + str(signum), flush=True)
                stop.set()
            signal.signal(sig, handle_stop)
    interval = int(os.getenv("JABBAZI_SCAN_INTERVAL_SECONDS", "7200"))
    if interval < 300:
        raise ValueError("Scan interval must be at least 300 seconds")
    startup_delay = 0 if once else int(
        os.getenv("JABBAZI_WORKER_STARTUP_SCAN_DELAY_SECONDS", "300")
    )
    if not 0 <= startup_delay <= interval:
        raise ValueError("Worker startup scan delay must be between 0 and scan interval")
    next_scan = time.monotonic() + startup_delay
    discord_process = None
    initial_model_refresh = True
    vip_acceptance_due = True
    daily_thread = None
    next_vip_watch = time.monotonic()
    next_entitlement_sync = time.monotonic()
    try:
        if not store.ready():
            raise RuntimeError("Database migration required")
        if not once and os.getenv("JABBAZI_DISCORD_COMMANDS_ENABLED", "false").lower() == "true":
            if os.getenv("JABBAZI_DISCORD_RECONCILE_ENABLED", "false").lower() == "true":
                try:
                    from .discord_reconcile import reconcile
                    result = reconcile()
                    from .discord_migration import CHANNEL_ENV
                    for name, suffix in CHANNEL_ENV.items():
                        os.environ["JABBAZI_DISCORD_" + suffix] = result["channel_ids"][name]
                    print("DISCORD_RECONCILE_" + result.get("status", "UNKNOWN") + " BACKUP=" + result.get("backup_id", "") + " CHANNELS=" + str(result["channel_ids"]), flush=True)
                    seed = subprocess.run([sys.executable, "tools/seed_discord_content.py", "--apply"], capture_output=True, text=True, timeout=300)
                    for line in seed.stdout.splitlines():
                        if line.startswith(("DISCORD_ONBOARDING_VERIFICATION ", "DISCORD_OPERATION_")):
                            print(line, flush=True)
                    print("DISCORD_ONBOARDING_" + ("SEEDED" if seed.returncode == 0 else "UNAVAILABLE"), flush=True)
                except Exception as exc:
                    # Never dump SDK response bodies, URLs, environment values or
                    # exceptions that could contain credentials.
                    detail = ""
                    import re
                    match = re.fullmatch(r"Configured channel ID missing for ([a-z-]+); review before migration", str(exc))
                    if match:
                        detail = "_MISSING_CHANNEL_" + match[1]
                    elif str(exc) in {"Configured Discord owner mismatch", "No approved VIP-family role exists",
                                      "Bot requires Manage Channels and Manage Roles before permission repair",
                                      "Durable database backup is required before migration", "Backup database is not ready",
                                      "Discord backup readback failed"}:
                        detail = "_" + str(exc).replace(" ", "_")
                    print("DISCORD_RECONCILE_UNAVAILABLE_" + type(exc).__name__ + detail, flush=True)
            discord_process = subprocess.Popen([sys.executable, "-m", "jabazi.discord_bot"])
        if not once:
            from .discord_schedule import daily_loop
            daily_thread = threading.Thread(target=daily_loop, args=(settings, url, stop), daemon=True)
            daily_thread.start()
        while not stop.is_set():
            if vip_acceptance_due:
                vip_acceptance_due = False
                if os.getenv("JABBAZI_DISCORD_COMMANDS_ENABLED", "false").lower() == "true":
                    try:
                        checked = store.list_records("vip_acceptance", 1, entity="terminal-v1")
                        if not checked or checked[0]["payload"].get("status") != "VERIFIED":
                            check = subprocess.run([sys.executable, "tools/verify_vip_production.py"], capture_output=True, text=True, timeout=300)
                            for line in check.stdout.splitlines():
                                if line.startswith("VIP_ACCEPTANCE_VERIFICATION "):
                                    print(line, flush=True)
                    except Exception as exc:
                        print("VIP_ACCEPTANCE_FAILED_" + type(exc).__name__, flush=True)
            if time.monotonic() >= next_vip_watch:
                try:
                    from .vip.state import poll_watchlists
                    poll_watchlists(store)
                except Exception as exc:
                    print("VIP_WATCH_JOB_FAILED_" + type(exc).__name__, flush=True)
                next_vip_watch = time.monotonic() + 60
            report = {"completed_at": datetime.now(UTC).isoformat(), "betting_enabled": False}
            from pathlib import Path
            try:
                report["memory_bytes"] = int(Path("/sys/fs/cgroup/memory.current").read_text())
                report["memory_events"] = dict(line.split() for line in Path("/sys/fs/cgroup/memory.events").read_text().splitlines())
            except (OSError, ValueError):
                pass
            if discord_process is not None:
                if discord_process.poll() is not None:
                    print("DISCORD_GATEWAY_RESTART_EXIT_" + str(discord_process.returncode), flush=True)
                    discord_process = subprocess.Popen([sys.executable, "-m", "jabazi.discord_bot"])
                report["discord_process"] = (
                    "RUNNING" if discord_process.poll() is None else "STOPPED"
                )
            try:
                if not settings.api_key:
                    report["status"] = "WAITING_FOR_ODDS_CREDENTIAL"
                else:
                    if time.monotonic() >= next_entitlement_sync:
                        try:
                            from .discord_roles import reconcile_known
                            report["discord_entitlements"] = reconcile_known(store)
                        finally:
                            next_entitlement_sync = time.monotonic() + 300
                    report["closing"] = ClosingCollector(store, settings.api_key).run()
                    if initial_model_refresh:
                        from .models.refresh import refresh_models
                        report["model_refresh"] = refresh_models(store)
                        initial_model_refresh = False
                    local_clock = datetime.now(UTC).astimezone(ZoneInfo("America/Chicago"))
                    daily_window = (local_clock.hour == 8 and local_clock.minute >= 57) or (local_clock.hour == 9 and local_clock.minute < 15)
                    if time.monotonic() >= next_scan and not daily_window:
                        # Schedule from completion; no concurrent jobs or catch-up storms.
                        try:
                            from .models.refresh import refresh_models

                            if "model_refresh" not in report:
                                report["model_refresh"] = refresh_models(store)
                            result = AutomaticScanner(
                                settings,
                                max_credits_per_run=int(os.getenv("JABBAZI_SCAN_MAX_CREDITS", "15")),
                            ).run("quick")
                            report["scan"] = {
                                "feeds": result.feeds_scanned,
                                "quotes": result.quotes_archived,
                                "errors": result.errors,
                                "modeled_actions": sum(
                                    a.model_probability is not None for a in result.actions
                                ),
                                "model_versions": sorted(
                                    {a.model_version for a in result.actions if a.model_version}
                                ),
                            }
                            from .discord_sheets import archive_sheets

                            archive_sheets(store, result)
                            if (
                                not result.errors
                                and os.getenv("JABBAZI_DISCORD_REVIEW_ENABLED", "false").lower()
                                == "true"
                            ):
                                from .discord_review import (
                                    validate_webhook,
                                    deliver_durable,
                                    render,
                                )

                                webhook = os.getenv("JABBAZI_DISCORD_REVIEW_WEBHOOK", "")
                                channel = os.getenv("JABBAZI_DISCORD_REVIEW_CHANNEL_ID", "")
                                validate_webhook(webhook, channel)
                                for action in [a for a in result.actions if render(a) is not None][
                                    :5
                                ]:
                                    deliver_durable(action, webhook, store, channel)
                        finally:
                            next_scan = time.monotonic() + interval
                    report["status"] = "RUNNING"
                store.append("worker_heartbeat", "research_worker", report)
            except Exception as exc:
                report["status"] = "DATA_UNHEALTHY"
                report["error_type"] = type(exc).__name__
                try:
                    store.append("worker_heartbeat", "research_worker", report)
                except Exception:
                    report["database_write"] = "failed"
            print(json.dumps(report, default=str), flush=True)
            if once:
                return report
            stop.wait(30 if settings.api_key else 300)
    finally:
        if discord_process is not None and discord_process.poll() is None:
            discord_process.terminate()
            try:
                discord_process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                discord_process.kill()
                discord_process.wait()
        if daily_thread is not None:
            daily_thread.join(timeout=10)
        store.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("role", choices=("api", "worker", "doctor", "history"))
    parser.add_argument("--once", action="store_true")
    parser.add_argument(
        "--sport", choices=("baseball_mlb", "americanfootball_nfl", "americanfootball_ncaaf")
    )
    parser.add_argument("--at")
    args = parser.parse_args()
    try:
        if args.role == "doctor":
            report = doctor()
            print(json.dumps(report))
            return 0 if report["status"] == "READY_FOR_RESEARCH" else 1
        settings, url, errors = configuration()
        if errors:
            raise ValueError("; ".join(errors))
        if args.role == "api":
            import uvicorn

            uvicorn.run("jabazi.api:app", host="0.0.0.0", port=int(os.getenv("PORT", "8000")))
        elif args.role == "worker":
            worker(once=args.once)
        else:
            from .providers.the_odds_api import TheOddsApiProvider
            from .operations import reserve_request

            if not args.at or not args.sport or not settings.api_key:
                raise ValueError(
                    "Historical collection requires --sport, --at and odds credentials"
                )
            at = datetime.fromisoformat(args.at.replace("Z", "+00:00"))
            if at.tzinfo is None or at >= datetime.now(UTC):
                raise ValueError("Historical timestamp must be in the past and timezone-aware")
            store = Store(url)
            try:
                if not reserve_request(store, 30):
                    raise ValueError("Monthly request budget exhausted")
                evidence = TheOddsApiProvider(
                    args.sport, api_key=settings.api_key
                ).fetch_historical(at)
                store.append("historical_odds", args.sport, evidence)
                print(
                    json.dumps(
                        {
                            "status": "ARCHIVED",
                            "snapshot_at": evidence["snapshot_at"],
                            "usage_type": evidence["usage_type"],
                        }
                    )
                )
            finally:
                store.close()
        return 0
    except Exception as exc:
        # urllib/SQL errors can embed credentials; emit only type here.
        print(json.dumps({"status": "UNAVAILABLE", "error_type": type(exc).__name__}), flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
