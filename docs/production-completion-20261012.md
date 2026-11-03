# JABBAZI implementation and remaining acceptance gates

Existing production infrastructure is retained. No models are promoted by this release.

## Implemented in this increment

- NHL simulator reuses the gated canonical NHL artifact and exact weighted score grid.
- Full-game NHL settlement includes overtime and one shootout deciding goal; book-specific settlement remains unverified.
- NHL spread and total scenarios preserve push probability and disclose weighted outcomes rather than claiming Monte Carlo draws.
- Quarantined artifacts cannot load through the registry or NHL model constructor.
- Approved original hot-pink brush logo installed unchanged from the user's prior approved asset.
- Authenticated matchup, simulation, per-game dated cheat-sheet and settled ledger performance PNG exports.
- Simulation exports fail unavailable when no valid model distribution exists.
- Acceptance probe covers original logo bytes, matchup graphic, and First TD availability in addition to authentication and core endpoints.

## Blocking evidence and unfinished work

- SportsDataIO NFL CurrentSeason and MLB projection endpoints return HTTP 401 with the configured key. Provider entitlement/key repair requires valid account access. Do not relabel trial or unverified data.
- Dedicated first-touchdown training, complete outcome labels (including defense/special teams and no TD), temporal evaluation and calibration are not complete. First TD rankings remain UNAVAILABLE.
- Scenario support is research-only, conditional on current supported inputs. No league has betting approval.
- No synthetic fixture or edited betting screenshot is performance evidence. Performance continues to use canonical scanner-origin settled positions.
- Comprehensive authenticated browser acceptance and sustained reliability monitoring remain required.
- First TD Top 10 and official-position/Play of the Day graphic exports remain incomplete; do not substitute eligible candidates for issued positions.
- All live market comparisons, injury provenance and exact-line props require event-specific acceptance; endpoint HTTP success is not sufficient.

The feature completion state remains PARTIALLY VERIFIED until these gates pass.
