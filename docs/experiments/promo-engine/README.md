# Promo research calculator — 2026-10-21

Reuses domain.pricing Decimal arithmetic and existing owner authentication.
POST /v1/chatgpt/promo-calculator is a read-only scenario calculator, not a model inference or betting approval endpoint. Probabilities and bonus conversion fractions supplied here are hypothetical assumptions. Every result remains RESEARCH_ONLY; no result can become BET NOW. No official records are written.

Supported arithmetic: capped extra profit boosts, bonus stake returned/not returned, loss-only refund (cash or explicitly assumed bonus conversion), and a verified unconditional qualifying bet-and-get reward. Complex conditional reward offers are unsupported and must not be marked verified. Push settlement for bonus bets and bet-and-get is explicitly unsupported. Eligibility and terms are owner-supplied assertions, not independently verified by the service. Quotes are manual snapshots with a five-minute maximum age, never continuously refreshed.

Seven-Up always returns PROMO EV UNAVAILABLE. No validated possession-path model exists in this release. No lead probability is inferred from final scores. Model probabilities, play-to prices, and risk approval remain unavailable in this calculator.

Provider transport additionally recognizes DEACTIVATED_KEY and EXCEEDED_FREQ_LIMIT. Successful responses persist only numeric request-credit headers with observation time; these are not dollar spending or subscription confirmation. Existing credential-scoped backoff remains intact. This release does not fix an invalid subscription or provision credentials, does not purchase data, and does not prove fresh odds coverage.

NBA artifact and approval gates unchanged. No demonstrated accuracy or profitability improvement is claimed. UI integration, validated promo inference, prospective evaluation, budget enforcement in dollars, and authenticated live calculator verification remain separate acceptance items.
