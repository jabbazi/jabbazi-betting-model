> Archived milestone document. See ../IMPLEMENTATION_STATUS.md and ../DEPLOYMENT.md for current behavior.

# Always-on cloud deployment

The cloud Compose file runs two services from the same image:

- `api`: authenticated bridge used by the Jabbazi Scanner website.
- `scanner`: two-hour background quick scans that preserve the audit ledger.

Terminate TLS at a cloud load balancer or reverse proxy and forward only to the `api` service on
port 8000. Never expose the odds key or model token to browser code.

## Recommended MVP

Use one small Linux VPS with Docker and an encrypted persistent volume. The scanner is single-user
and SQLite is safe for one scanner process. Move to managed PostgreSQL before adding multiple workers,
a public API, or a dashboard.

Required server characteristics:

- Ubuntu 24.04 LTS or comparable Linux
- 2 GB RAM minimum
- 20 GB persistent disk
- Docker Engine plus Compose
- Outbound HTTPS access
- Firewall denying all inbound application ports; SSH restricted to the owner's IP

## Deploy

Copy the repository to the server without `.env`, then create `.env` directly on the server with
permissions `600`. Never bake the odds API key into the image.

```bash
docker compose -f docker-compose.cloud.yml build
docker compose -f docker-compose.cloud.yml up -d
docker compose -f docker-compose.cloud.yml logs -f scanner
```

The scanner runs a quick major-US-sports pass every two hours. Each pass may spend at most 15 credits
and stops when 50 credits remain. Every payload, quote, and changed action card is persisted in the
`jabazi_data` volume. Docker restarts the scanner after process or server failure.

## Backups

Stop the scanner briefly or use SQLite's online backup command, encrypt the backup, and store it in a
separate account/bucket. Test restoration before treating the system as production.

## Current limits

- No public dashboard or inbound port is exposed.
- Alerts still return through the operating task/logs; an email/SMS/push provider is the next service.
- The free odds quota cannot sustain exhaustive frequent scans.
- Recommendation records are automatic; accepted wagers require an authorized sportsbook execution
  feed or explicit confirmation.
