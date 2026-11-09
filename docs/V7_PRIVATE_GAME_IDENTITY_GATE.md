# Candidate-to-game identity membership gate

Use `jabazi.paid_identity_event_gate.audit_candidate_game_context` in a
private V7 identity-review process to cross-check an independently observed
BALLDONTLIE game record with a private candidate review packet. It checks:

- Exact provider game start timestamp and scheduled status
- Both participating teams, rejecting absent/ambiguous game team identity
- Candidate roster team membership in that game
- Matching private candidate review kickoff and sport/source namespace
- Explicit **unverified** candidate status, never trusting self-set approval flags

The returned `private_event_membership_candidates` includes private review
information and MUST remain inside the authorized environment. Only
`redacted_summary` is suitable for logs. This does not prove real-world
player identity, paid feed completeness, lineup availability, or validated
player probabilities.

It does not mutate manifests, generate probabilities, call APIs, or alter
the production branch. Complete independent original-source identity review
is still necessary before any manifest registration.
