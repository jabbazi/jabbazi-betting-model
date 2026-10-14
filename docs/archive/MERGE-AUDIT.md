> Archived milestone document. See ../IMPLEMENTATION_STATUS.md and ../DEPLOYMENT.md for current behavior.

# Uploaded multisport model merge audit

## Adopted

- Expandable sport catalog rather than an MLB-only design
- Arbitrary provider market ingestion
- Separation between universal scanning and sport-specific prediction
- Broad categories for props, periods, totals, alternates, and futures

## Replaced

The uploaded float-based odds math was replaced by the existing Decimal implementation. Its
Pandas scanner was not used because it priced each row independently, did not remove vig, did not
price-shop identical lines, did not check freshness, and did not load cumulative portfolio state.
The Streamlit upload UI was deferred because reliable ingestion and auditability remain the priority.

## Result

The merged system accepts broad provider market keys while retaining strict decision semantics:
unmodeled price discrepancies are `WATCH`, stale data is `WAIT`, risk failures are `PASS`, and only
a versioned independent model probability can lead to `BET_NOW`.
