CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TYPE data_quality AS ENUM ('realtime','delayed','cached','manual','fixture');
CREATE TYPE decision_kind AS ENUM ('BET_NOW','WAIT','WATCH','PASS');

CREATE TABLE raw_provider_payloads (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), provider text NOT NULL,
  fetched_at timestamptz NOT NULL, source_timestamp timestamptz,
  quality data_quality NOT NULL, sha256 char(64) NOT NULL UNIQUE,
  payload jsonb NOT NULL
);
CREATE TABLE events (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), sport text NOT NULL, league text NOT NULL,
  provider_event_key text NOT NULL, starts_at timestamptz NOT NULL,
  home_name text, away_name text, status text NOT NULL DEFAULT 'scheduled',
  UNIQUE (sport, league, provider_event_key)
);
CREATE TABLE markets (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), event_id uuid NOT NULL REFERENCES events(id),
  market_key text NOT NULL, period text NOT NULL DEFAULT 'full_game', line numeric,
  UNIQUE (event_id, market_key, period, line)
);
CREATE TABLE selections (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), market_id uuid NOT NULL REFERENCES markets(id),
  selection_key text NOT NULL, participant_name text, side text,
  UNIQUE (market_id, selection_key)
);
CREATE TABLE odds_snapshots (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), selection_id uuid NOT NULL REFERENCES selections(id),
  sportsbook text NOT NULL, decimal_odds numeric NOT NULL CHECK (decimal_odds > 1),
  observed_at timestamptz NOT NULL, source_timestamp timestamptz NOT NULL,
  quality data_quality NOT NULL, provider_quote_id text NOT NULL,
  raw_payload_id uuid REFERENCES raw_provider_payloads(id),
  UNIQUE (sportsbook, provider_quote_id)
);
CREATE INDEX odds_lookup ON odds_snapshots(selection_id, observed_at DESC);
CREATE TABLE model_versions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), name text NOT NULL, version text NOT NULL,
  code_hash text NOT NULL, created_at timestamptz NOT NULL DEFAULT now(), UNIQUE(name, version)
);
CREATE TABLE probability_estimates (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), selection_id uuid NOT NULL REFERENCES selections(id),
  model_version_id uuid NOT NULL REFERENCES model_versions(id), probability numeric NOT NULL
    CHECK (probability >= 0 AND probability <= 1), uncertainty numeric NOT NULL
    CHECK (uncertainty >= 0 AND uncertainty <= 1), feature_snapshot jsonb NOT NULL,
  estimated_at timestamptz NOT NULL, UNIQUE(selection_id, model_version_id, estimated_at)
);
CREATE TABLE scan_runs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), betting_date date NOT NULL,
  started_at timestamptz NOT NULL DEFAULT now(), completed_at timestamptz,
  input_hash char(64) NOT NULL, status text NOT NULL, UNIQUE(betting_date, input_hash)
);
CREATE TABLE recommendations (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), scan_id uuid NOT NULL REFERENCES scan_runs(id),
  selection_id uuid NOT NULL REFERENCES selections(id), decision decision_kind NOT NULL,
  reason text NOT NULL, model_probability numeric NOT NULL, adjusted_probability numeric NOT NULL,
  market_probability numeric, best_odds_snapshot_id uuid REFERENCES odds_snapshots(id),
  ev numeric, stake numeric NOT NULL DEFAULT 0, max_playable_decimal numeric,
  risk_policy_version text NOT NULL, created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(scan_id, selection_id)
);
CREATE TABLE bets (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), recommendation_id uuid REFERENCES recommendations(id),
  sportsbook text NOT NULL, placed_at timestamptz NOT NULL, entry_decimal_odds numeric NOT NULL,
  line numeric, stake numeric NOT NULL CHECK(stake > 0), status text NOT NULL,
  settled_at timestamptz, profit numeric
);
CREATE TABLE bet_exposures (
  bet_id uuid NOT NULL REFERENCES bets(id), dimension text NOT NULL, exposure_key text NOT NULL,
  amount numeric NOT NULL, PRIMARY KEY(bet_id, dimension, exposure_key)
);
CREATE TABLE closing_lines (
  bet_id uuid PRIMARY KEY REFERENCES bets(id), snapshot_id uuid NOT NULL REFERENCES odds_snapshots(id),
  captured_at timestamptz NOT NULL, probability_clv numeric, price_clv numeric
);
CREATE TABLE audit_events (
  id bigserial PRIMARY KEY, occurred_at timestamptz NOT NULL DEFAULT now(), actor text NOT NULL,
  entity_type text NOT NULL, entity_id text NOT NULL, action text NOT NULL, details jsonb NOT NULL
);
