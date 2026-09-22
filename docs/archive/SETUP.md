> Archived milestone document. See ../IMPLEMENTATION_STATUS.md and ../DEPLOYMENT.md for current behavior.

# Setup and operations

## What this system can and cannot do

Jabazi can ingest and normalize any market returned by its provider, including team markets,
totals, period markets, props, and alternate ladders. It can price-shop identical wagers, remove
vig from complete markets, flag stale or outlier prices, persist evidence, enforce risk limits, and
measure performance.

Universal market support is not universal predictive intelligence. MLB pitcher strikeouts, NFL
passing yards, tennis aces, and soccer shots require different data and independently validated
models. Until one exists, a positive cross-book discrepancy is `WATCH`, never `BET_NOW`.

## 1. Install prerequisites

Install:

- Python 3.12 or newer
- Git
- Docker Desktop if using PostgreSQL

From PowerShell in the project folder:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

## 2. Configure secrets and bankroll

The existing `.env` contains the locally stored odds API key and is excluded by `.gitignore`.
Review these values without committing the file:

```env
JABAZI_OPERATIONAL_TIMEZONE=America/Los_Angeles
JABAZI_UNIT_SIZE=20.00
JABAZI_BANKROLL=1000.00
JABAZI_DAILY_EXPOSURE_LIMIT=0.20
JABAZI_MIN_EDGE=0.02
```

Replace the test bankroll with the actual dedicated betting bankroll before using stake output.
The 20% daily exposure value is a hard ceiling, not a target.

## 3. Verify the build

```powershell
python -m unittest discover -s tests -v
python -m jabazi catalog
```

## 4. Run a featured-market scan

Featured scans cover moneylines, spreads/run lines, and totals. Each requested market consumes one
provider credit for the US region:

```powershell
python -m jabazi scan --sport baseball_mlb --markets h2h,spreads,totals --top 25
python -m jabazi scan --sport basketball_wnba --markets h2h,spreads,totals --top 25
python -m jabazi scan --sport americanfootball_nfl --markets h2h,spreads,totals --top 25
```

The command archives the raw payload and normalized quotes in `jabazi-local.db`. Repeated snapshots
are retained rather than overwriting history.

## 5. Scan props and alternate lines

The provider requires non-featured markets to be queried one event at a time. First list event IDs;
the event-list endpoint does not consume odds quota:

```powershell
python -m jabazi events --sport baseball_mlb
```

Then request concrete markets for one event:

```powershell
python -m jabazi scan-event --sport baseball_mlb --event-id EVENT_ID `
  --markets pitcher_strikeouts,pitcher_strikeouts_alternate,batter_total_bases
```

The command first discovers recently available markets. It stops before the odds request if a
requested key is absent, preventing wasted credits. Examples for other sports:

```powershell
python -m jabazi scan-event --sport basketball_wnba --event-id EVENT_ID `
  --markets player_points,player_rebounds,player_points_rebounds_assists,player_points_alternate

python -m jabazi scan-event --sport americanfootball_nfl --event-id EVENT_ID `
  --markets player_pass_yds,player_reception_yds,player_rush_yds,player_pass_yds_alternate
```

## 6. Understand decisions

- `BET_NOW`: a validated independent model clears EV, uncertainty, execution, and portfolio rules.
- `WATCH`: useful price discrepancy, but no sufficient independent probability yet.
- `WAIT`: price is stale or should be refreshed.
- `PASS`: insufficient EV, bad execution, incomplete capacity, or another risk veto.

Never convert `WATCH` to a bet merely because its market-relative EV is positive. That number is a
price-shopping signal derived from the market itself.

## 7. Sportsbook coverage

The free provider plan returns DraftKings and FanDuel for supported US markets. Caesars uses the
provider key `williamhill_us` and currently requires a paid subscription. Jabazi displays Caesars
only when the provider actually returns it.

## 8. PostgreSQL

SQLite supports immediate local operation. For the production source of truth:

```powershell
docker compose up -d db
```

Apply `migrations/001_initial.sql` to the `jabazi` database. The next engineering milestone is the
SQLAlchemy repository that makes PostgreSQL the scanner's default runtime instead of only providing
the production schema.

## 9. Required path to real predictive bets

For each sport/market family:

1. Acquire licensed historical results, lineups, injuries, and context data.
2. Freeze features using only information available before the event.
3. Train a sport-specific probability distribution, not a winner classifier.
4. Use time-based train/validation/test splits.
5. Measure calibration, Brier score, log loss, and out-of-sample CLV.
6. Version the model and feature snapshot.
7. Paper trade before enabling `BET_NOW`.
8. Disable markets automatically when CLV or calibration deteriorates.

Recommended order: MLB pitcher strikeouts, NFL core sides/totals, NBA/WNBA player minutes-based
props, then tennis and soccer. Building every model simultaneously would create broad but weak
coverage.

## 10. Production readiness checklist

- Confirm actual bankroll and unit size.
- Upgrade data plan if Caesars or historical odds are required.
- Add the PostgreSQL repository and scheduled closing-line capture.
- Add confirmed-bet entry and settlement commands.
- Add one validated sport model at a time.
- Back up the database and monitor feed freshness and quota.
- Keep wagering manual; never scrape or automate sportsbook account interaction.

## Automatic operation

Run a credit-aware automatic pass with:

```powershell
.\jabazi.ps1 auto-scan --mode quick --credit-reserve 50 --max-credits 30
```

Every action card is stored automatically, and repeated identical cards are not duplicated. `quick`
targets the major US slates. `full` walks all active supported feeds but still stops at the configured
per-run budget and account reserve. Actual placed bets remain a separate state because a
recommendation is not evidence that a sportsbook accepted a wager.
