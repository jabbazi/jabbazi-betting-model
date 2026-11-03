# Private owner review desk

`/owner` serves a mobile-friendly, read-only interface. The page shell has no research data. `/v1/owner/review` requires the same private bearer credential as the administrative API. Keep this credential with the owner; it is not a VIP membership credential. Enter it directly in the application, never in chat or a Discord channel.

The browser holds the credential only in memory, clears the input after unlock, and clears research on Lock/page exit. No browser storage, third-party assets, query-string secrets, scan triggers, or Discord posting calls are used. Responses are no-store. Provider labels are inserted as text, not HTML.

The desk shows the latest archived scan, filtered by sport and paginated 25 rows at a time. It never falls back to an older healthy scan. Bad, future, missing, and older-than-three-hour timestamps are blocked; individual prices older than 120 seconds require refresh. This is an archive viewer, not a live execution-price check.

Model probabilities require a model version and a finite probability strictly between zero and one. Without them, research probability, edge, ROI, and uncertainty are unavailable. Even with them, no production model approval is inferred. All cards remain research/WATCH, with no stake or maximum playable price until a separately validated production approval path exists.

Automated tests cover authentication before storage access, no-cache responses, pagination, sport filtering, unavailable model evidence, stale/future/malformed snapshots and unhealthy data. No claim of model profitability follows from this interface.
