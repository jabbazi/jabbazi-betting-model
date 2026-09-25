"""Assemble measured results and explicit delivery limits; no inferred deployment."""

import hashlib
import json
import gzip
import platform
from pathlib import Path
import numpy, sklearn, scipy

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "docs/experiments/reliability-upgrade"


def build():
    reports = {s: json.loads((BASE / s / "report.json").read_text()) for s in ("nfl", "mlb", "cfb")}
    source_paths = [
        "src/jabazi/models/form_features.py",
        "src/jabazi/models/score_distribution.py",
        "src/jabazi/research/train_scores.py",
        "src/jabazi/research/rolling_upgrade.py",
        "src/jabazi/research/calibration_report.py",
    ]
    manifest = {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in source_paths}
    runtime = {
        "python": platform.python_version(),
        "numpy": numpy.__version__,
        "sklearn": sklearn.__version__,
        "scipy": scipy.__version__,
    }
    (BASE / "reproduction-manifest.json").write_text(
        json.dumps(
            {
                "source_sha256": manifest,
                "runtime": runtime,
                "availability": "retrospective two-day proxy, not frozen historical receipts",
            },
            indent=2,
        )
        + "\n"
    )
    lines = [
        "# JABBAZI reliability upgrade — 2026-09-25",
        "",
        "**Implemented and locally verified; not deployed. No model promoted.**",
        "Render opens its sign-in page in this workspace. The connected live model-status tool still returns the old NFL/MLB versions and CFB UNAVAILABLE. No Discord publishing or wagering was performed.",
        "",
        "## Diagnosis: Chiefs at Miami",
        "Scan `8f4d0c7e-5c5c-4d7b-a0ac-2e55dc19d2c1`, generated `2026-09-25T03:20:39.916689+00:00`; game `2026-09-27T17:00:00Z`, provider event `0339a0e41bcee12820eb3e64bb5fadb4`.",
        "The bundled artifact reproduces +2.5 = 168/285 = 58.947%, +7.5 = 212/285 = 74.386%, +10.5 = 232/285 = 81.404%, and conditional ML = 134/269 = 49.814% exactly. +11.5 is 82.105%, not the +10.5 rung.",
        "Expected simulated score: Miami 21.754, Kansas City 21.519; Miami margin +0.235; margin SD 13.530. Six of eight equally weighted input games per team are from 2025, and two are from 2026. The six inputs are scoring form, conceding form, rest difference and home field. There is no QB/roster/injury/weather verification. The 285 paired 2024 residuals generate 16 ties (5.61%); this is another football distribution limitation, not a validated NFL tie forecast.",
        "This is a reproducible weak/stale feature forecast, not an observed spread-sign inversion. We cannot establish the true causal personnel/news reason for market disagreement without those missing inputs. All 26 requested checks and exact input histories are in [miami-diagnostic.json](experiments/reliability-upgrade/miami-diagnostic.json). The original production feature record is not accessible through the three read-only scanner tools; the proof is an exact reproduction from the committed artifact. No probability cap was applied.",
        "Miami main +10.5 market consensus is 49.476%, ML 15.907%. Both gaps exceed 20pp. The upgraded scanner exposes EXTREME_DISAGREEMENT plus MODEL_QUARANTINE until identity, personnel, calibration and data checks are established. Live behavior remains unchanged until rollout.",
        "",
        "## Confirmed code defects and fixes",
        "- Alternate spreads were keyed by absolute handicap. A +1.5/B -1.5 and A -1.5/B +1.5 could share one normalization group. A regression reproduces the Toronto/Baltimore half-mass mechanism; signed canonical-team orientation now keeps each pair separate. No exact raw September 23 provider archive was retrieved, so this proves the code defect/mechanism rather than claiming a full forensic replay of that older payload.",
        "- `v4.2-reliability-engine` commit `4c5c52f` contains literal backslash-n sequences: Python cannot import it. The module was decoded into the real service package, with its concepts retained. Failed promotion gates no longer confer LIMITED_LIVE; frozen prospective version/bucket evidence and stability are required. Numeric defaults remain placeholders, not validated promotion policy.",
        "- A model exception could abort the rest of a feed. Per-candidate isolation now keeps independent price research available, with explicit model errors.",
        "- Scanner presentation omitted anomaly evidence, score distribution and input lineage. It now retains them while preserving existing tool names and request schemas.",
        "- CLV was calculated on demand but not saved as its own evidence record. Matching-threshold comparisons now append immutable CLV evidence.",
        "",
        "## Architecture and changes",
        "Actual cloud path: MCP `scan_everything` → `chatgpt_api.run_background` → `api.perform_scan` → `AutomaticScanner` → `FeedPlan` / `TheOddsApiProvider` → normalized quotes → signed market pairing/no-vig/line shopping → `models.registry` → score feature generation / shared paired-score distribution → reliability/anomaly checks → candidate/forecast persistence → `get_scan_results`. `get_model_status` reads that same registry. The legacy `scanner/service.py` is explicitly disabled in production.",
        "- One empirical joint score distribution now has a validated interface, predictive mean/variance/covariance/intervals, full ladder checks, push accounting, raw win/loss mass and shared-scenario SGP calculations. The existing paired-residual champion was already coherent; it was preserved. Conditional moneyline semantics remain separately labeled.",
        "- NFL and CFB recency/opponent-adjusted score-form challengers use decaying historical weights and a league-prior shrinkage term. These are **not** EPA, QB or returning-production models. Recency decay alone did not beat the NFL champion.",
        "- MLB alternatives include paired residuals, Poisson and fitted-overdispersion negative-binomial simulations (10,000 draws per evaluated game, deterministic seed). None replaced the champion.",
        "- Platt, isotonic and beta calibration are evaluated only on subsequent held-out games. Non-monotonic fits are rejected. They are not applied independently across live score markets, which could break joint coherence.",
        "- Pure, calibrated and market-aware fields are distinct; unavailable fields are null. The experimental shrinkage module defaults to zero model weight without matching frozen bucket evidence. It is not silently applied in the scanner.",
        "- Owner-only diagnostics/source-pick endpoints; immutable typed source picks, lifecycle/corrections and frozen-forecast contracts; actual-dollar thesis graph and central thesis tags; promo-term validation; Bob depth helper; research-priority score explicitly unrelated to win probability. Source import, promo and Bob helpers are frameworks, not advertised as live external-data integrations.",
        "- Identity contracts, duplicate-event detection, feature drift indicators, schema/freshness/pairing checks, missing-input reasons, model/odds snapshots and artifact hashes. Full personnel checks cannot pass without actual feeds.",
        "",
        "## Out-of-sample diagnostics",
        "Monthly expanding-origin 2025 evaluation. Each challenger fold separates earlier fitting labels, residual-distribution labels and probability-calibration labels, with availability gaps at boundaries. NFL/MLB 2025 was previously inspected, so this is a diagnostic comparison, not an untouched final holdout. CFB uses five seasons of archived FBS-v-FBS results (plus current state); no CFB player props.",
        "One canonical home outcome per game/market. Spread/total tests use fixed diagnostic thresholds, not historical offered lines. NFL market quotes are retrospective reference prices with unknown observation times; no odds-feature leakage. No legitimate execution ROI or CLV backtest is available. Brier confidence intervals and hit-rate Wilson intervals are in the JSON reports.",
        "",
        "| Sport / architecture | ML n | Brier ↓ | Log loss ↓ | ECE (5pp buckets) |",
        "|---|---:|---:|---:|---:|",
    ]
    for sport, r in reports.items():
        for name, markets in r["results"].items():
            m = markets["moneyline"]["raw"]
            lines.append(
                f"| {sport.upper()} / {name} | {m['n']} | {m['brier']:.6f} | {m['log_loss']:.6f} | {m['ece']:.4f} |"
            )
    lines += [
        "",
        "### Probability calibration comparison",
        "",
        "| Sport / recency ridge | Method | n | ML Brier | ML log loss |",
        "|---|---|---:|---:|---:|",
    ]
    for sport, r in reports.items():
        for cal in ("raw", "platt", "isotonic", "beta"):
            m = r["results"]["recency_ridge"]["moneyline"][cal]
            lines.append(
                f"| {sport.upper()} | {cal} | {m['n']} | {m['brier']:.6f} | {m['log_loss']:.6f} |"
            )
    lines += [
        "",
        "### Market diagnostics (raw Brier)",
        "",
        "| Sport / retained baseline | ML | Spread | Total | Team total | Alt spread | Alt total |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for sport, r in reports.items():
        name = "recency_ridge" if sport == "cfb" else "champion"
        m = r["results"][name]
        lines.append(
            "| "
            + sport.upper()
            + " / "
            + name
            + " | "
            + " | ".join(
                f"{m[k]['raw']['brier']:.6f}"
                for k in (
                    "moneyline",
                    "spread",
                    "total",
                    "team_total",
                    "alternate_spread",
                    "alternate_total",
                )
            )
            + " |"
        )
    lines += [
        "",
        "### Retained baseline ML calibration buckets",
        "",
        "| Sport | Predicted bucket | n | Mean predicted | Observed hit rate | 95% hit-rate interval |",
        "|---|---|---:|---:|---:|---|",
    ]
    for sport, r in reports.items():
        name = "recency_ridge" if sport == "cfb" else "champion"
        for b in r["results"][name]["moneyline"]["raw"]["buckets"]:
            if b["lower"] < 0.5:
                continue
            n = b["n"]
            interval = b["hit_rate_interval_95"]
            lines.append(
                f"| {sport.upper()} | {b['lower']:.0%}–{b['upper']:.0%} | {n} | "
                + (
                    f"{b['mean_probability']:.1%} | {b['observed_rate']:.1%} | {interval[0]:.1%}–{interval[1]:.1%}"
                    if n
                    else "— | — | —"
                )
                + " |"
            )
    nfl = reports["nfl"]["results"]["champion"]["moneyline"]
    lines += [
        "",
        f"NFL reference-market Brier: {nfl['market_reference']['brier']:.6f}; champion Brier {nfl['raw']['brier']:.6f}. The champion still underperforms that retrospective reference. MLB and CFB lack paired timestamped market benchmarks. Small buckets, especially NFL high-confidence buckets, cannot establish reliable accuracy.",
        "",
        "## Model versions and market stages",
        "- Retained NFL: `nfl-score-ridge-0.1.0-8b55af293d53`.",
        "- Retained MLB: `mlb-score-ridge-0.1.0-792a7fe3fb48`.",
        f"- New CFB: `{reports['cfb']['model_version']}` (trained and visible through local `get_model_status`; not live).",
        "- Every moneyline, spread, alternate spread, total, alternate total, team total and alternate team total bucket remains SHADOW_ONLY, with zero frozen prospective validation results. Unsupported markets remain unavailable. No global approval flag can promote these fitted research artifacts.",
        "- CFB supports FBS-v-FBS only; exact ID-joined team aliases, no FCS extrapolation, no CFB props. It has 800 retrospective 2025 evaluation games. Public archive receipt hashes and pinned source commit are saved. Ongoing CFBD refresh needs `JABBAZI_CFBD_API_KEY`; absent it, state becomes stale and inference stops rather than inventing updated inputs.",
        "",
        "## Persistence and migrations",
        "No destructive SQL migration is needed. The existing PostgreSQL/SQLite append-only `platform_events` store accepts versioned `source_pick`, `price_lifecycle`, `clv_record` and `frozen_forecast` evidence. Existing `model_prediction` gains feature/odds provenance and reliability payloads. Existing SQL immutability triggers and schema version 1 remain intact. `python -m jabazi.persistence.migrate` is idempotent. New source/lifecycle import contracts reject malformed or unauditable data; corrections append references and reasons rather than rewriting records.",
        "The source schema does not scrape restricted capper services or grant their content redistribution rights. No source receives a learned performance weight without prospective outcomes.",
        "",
        "## Tests and release status",
        "See TEST_RESULTS.md for the final exact test count and CI result. Tests cover the exact Miami reproduction, signed alternate-pair regression, full ladders, pushes/complements, team-total identities, joint SGP dependence, stage demotion, calibration counts/monotonicity, recency/future labels, CFB inference/status/no-props, source immutability, CLV persistence, identity mismatches, duplicate events, drift, malformed-model isolation, explicit blend lanes and existing API contracts.",
        "Local HTTP smoke verifies 200 liveness/readiness, 401 unauthenticated access, 200 authenticated database read and 503 missing odds provider. Production deployment has not occurred. Local tests are not proof of production PostgreSQL or Docker behavior; GitHub CI is the release gate for those.",
        "",
        "## Exact rollout",
        "1. Review the upgrade PR against `build/production-foundations` and require passing test/PostgreSQL/container/backup-restore CI. Preserve the separate member-experience work; do not force-push or merge the standalone V4.2 branch over the service.",
        "2. Sign in to the existing Render workspace. Merge the reviewed upgrade into `build/production-foundations`. Both existing services have automatic deployment off; manually deploy the **same reviewed commit** to `jabbazi-research-api` and `jabbazi-research-worker`. No new paid service is required. The existing pre-deploy migration is unchanged.",
        "3. Supply CFBD credentials via Render environment settings if ongoing CFB refresh is authorized; keep provider keys private. Keep model approval and unconfigured publishing disabled. Do not alter the bankroll or unit size.",
        "4. Verify `/healthz`, `/readyz`, authenticated model status and existing MCP `get_model_status`. Require the CFB version above, seven team markets, SHADOW_ONLY and per-market buckets. Verify worker model refresh health. Run one explicitly authorized bounded research scan and read all retained pages; inspect frozen diagnostic evidence, freshness, anomaly state, zero stake and no Discord send.",
        "5. Roll back both services to the previous reviewed commit if health/auth/API regressions appear. New event kinds are additive; retain their historical evidence. Do not delete or rewrite forecasts.",
        "",
        "## What is still unavailable / incomplete",
        "- No production rollout: Render sign-in required. No live CFB version, live anomaly quarantine or live signed-pair fix is claimed.",
        "- No frozen prospective champion/challenger evaluation campaign; no model promoted to VALIDATING/LIMITED_LIVE/PRODUCTION_APPROVED.",
        "- No validated personnel-aware NFL/MLB models, advanced CFB roster/talent/returning-production priors, or decision-time price backtest. Advanced-feature ingestion interfaces already existed and remain gated by real inputs.",
        "- No approved NFL/MLB props, anytime-TD model, first-half/quarter model, player-linked SGP model, automatically mined capper feeds or provider-specific verified promo terms. Unknown probabilities/correlations remain unavailable.",
        "- The new joint game helper supports team-market SGP research, but the scanner has no verified sportsbook combined-payout feed and does not manufacture SGP value.",
        "- New source/price lifecycle/frozen forecast and Bob/promo/shrinkage helpers are implemented and tested; automatic source settlement, learned weights, nightly/weekly performance scheduling, and full live challenger fan-out are still pending.",
        "- Probability calibrators are offline experiments. Serving them independently across markets would damage coherence. Joint-distribution calibration must be validated before live integration.",
        "- Existing history uses delayed-score availability proxies. Historical QB/lineup/weather knowledge and original provider receipt snapshots cannot be reconstructed honestly from current feeds.",
        "- Commercial display/redistribution rights for public-derived statistics and capper content need confirmation before a paid launch.",
        "",
        "## Owner access / approvals needed",
        "- Render sign-in to deploy the tested commit; no password or key in chat.",
        "- CFBD API key and permission for the configured current-season refresh. The initial archived CFB training did not require a paid purchase.",
        "- Timestamped historical odds/closing coverage entitlement (current The Odds API account or another permitted source); no purchase has been made.",
        "- Legitimate timestamped NFL QB/injury/depth-chart/advanced-stat and MLB starter/lineup/bullpen/weather feeds, with commercial-use rights if displayed to members. No paid provider is selected or bought by this change.",
        "- No request for sportsbook login, geolocation bypass, automated bet execution, or Discord publication.",
        "",
        "## Next three highest-value improvements",
        "1. Deploy these correctness fixes and start a frozen prospective, market-bucket evaluation ledger with paired current odds, closures and settled outcomes.",
        "2. Add verified decision-time personnel/context feeds (NFL QB/injuries; MLB confirmed starters/lineups/bullpen) and measure feature ablations against the retained champions and market benchmark.",
        "3. Improve the joint score distributions, including football tie/overtime treatment and distribution-level calibration, then reassess challenger promotion. Player props follow only after the team foundation clears its gates.",
        "",
    ]
    (ROOT / "docs/RELIABILITY_UPGRADE_REPORT.md").write_text("\n".join(lines))
    # Compact machine-readable reports for normal git review, retaining every value.
    for sport in reports:
        path = BASE / sport / "predictions.json"
        if path.exists():
            target = path.with_suffix(".json.gz")
            target.write_bytes(gzip.compress(path.read_bytes(), mtime=0))
            path.unlink()
        p = BASE / sport / "challenger-artifact.json"
        a = json.loads(p.read_text())
        a["code_parent_commit"] = a.pop("code_commit", None)
        a["code_commit"] = None
        a["training_source_sha256"] = manifest
        a["runtime"] = runtime
        p.write_text(json.dumps(a, allow_nan=False) + "\n")
    p = ROOT / "src/jabazi/models/artifacts/cfb_scores.json"
    a = json.loads(p.read_text())
    a["code_parent_commit"] = a.pop("code_commit", None)
    a["code_commit"] = None
    a["training_source_sha256"] = manifest
    a["runtime"] = runtime
    p.write_text(json.dumps(a, allow_nan=False) + "\n")


if __name__ == "__main__":
    build()
