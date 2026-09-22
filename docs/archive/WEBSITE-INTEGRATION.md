> Archived milestone document. See ../IMPLEMENTATION_STATUS.md and ../DEPLOYMENT.md for current behavior.

# Jabbazi Scanner website integration

The container now starts an authenticated FastAPI service on port 8000. The website calls this
service when the owner presses **Scan Everything**. The API returns structured decisions; it never
places wagers and it never invents Pikkit links.

Required server settings:

- `JABAZI_ODDS_API_KEY`: a current licensed provider key. Rotate the key previously pasted in chat.
- `JABBAZI_MODEL_TOKEN`: a random secret containing at least 32 characters.
- `JABAZI_DATABASE_PATH=/data/jabazi.db`
- Bankroll, unit size, exposure limit and minimum edge settings from `.env.example`.

Expose the API only through HTTPS. Configure the website with the HTTPS API base URL and the same
model token. The website trigger endpoint is restricted to the configured ChatGPT owner account,
so public visitors can read the board but cannot consume odds credits.

`POST /v1/scans/run` accepts:

```json
{"mode":"full","credit_reserve":50,"max_credits":30,"limit":260}
```

Send `Authorization: Bearer <JABBAZI_MODEL_TOKEN>`. Full mode scans every currently active
configured featured feed until its credit limit or reserve is reached. Props and alternate lines
remain event-scoped and are not falsely represented as universal coverage. Market-consensus
signals remain WATCH until an independent sport-specific model passes validation.
