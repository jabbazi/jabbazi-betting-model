# Rules gate rollout — 2026-10-13

The live audit found the system channel pointing at general, an already topmost
welcome category, Community enabled but rules screening off, and a stale welcome
channel configuration. The existing dedicated rules channel is archived; restore
that channel with its history rather than creating another one.

## Enforcement

Existing VIP/source/billing roles remain untouched. The bot owns two additional
zero-global-permission roles: JABBAZI COMMUNITY and JABBAZI VERIFIED VIP. Channel
visibility requires the derived community role, or the derived paid role for VIP
channels. The latter requires both acceptance and a current original VIP role.
Paid roles alone cannot bypass rules, and acceptance alone cannot grant paid access.
Owner/admin permissions remain privileged; they are not a valid ordinary-member test.

Before applying channel changes, the installer persists all before-state, preserves
existing members' access by granting derived roles, and verifies those assignments.
Existing members are recorded as grandfathered joins, not fabricated acceptances.
A genuine rejoin requires acceptance again. Bot roles, staff exceptions and member
specific overrides are retained. Unknown role visibility grants abort preflight.

One persistent shared green button acts only on its clicking member. Per-join
welcomes link to this pinned button. Acceptance version/time and delivery receipts
are stored. Repeated clicks and restarts are safe; success follows role readback.
The rules channel, guide, welcome, access information and support remain accessible.
Native join announcements are suppressed to avoid duplicating the bot welcome.

Role updates trigger derived-role reconciliation; the publisher also reconciles
membership every cycle (nominal 60 seconds, longer if other publication jobs run).
A bot outage does not admit new unaccepted members. Removal of a paid source role
while the bot is offline can leave a previously granted derived channel role until
reconnection/reconciliation. This is an explicit limitation, not immediate billing
revocation. App ticket issuance continues checking original paid roles and rules.

## Recovery

Enable installation only through JABBAZI_RULES_GATE_ENABLED=true on the worker.
The durable discord_rules_backup record stores channel overwrite sets, names,
parents, positions, system settings and original member-role inventory. The active
configuration records its backup ID. Disable legacy startup layout/seed/repair jobs
to prevent them undoing this gate. Do not run old layout migration tools against an
active gate without reconciling their permission model first.

To roll back: pause rollout and the gate's reconciliation, restore only the recorded
channel/guild before-state after checking for intervening admin changes, append a
DISABLED discord_rules_config record, and redeploy the prior worker. Do not delete
source roles, member histories, acceptance evidence, or database lookup indexes.
The extra derived roles may remain inert after their channel grants are removed.
Never restore the database over production for a test.

## Verification scope

Automated tests exercise the permission matrix (unaccepted paid/unpaid, accepted
paid/unpaid), role expiration, rejoin behavior, persistent buttons, repeated clicks,
failed assignment and existing-member preservation. Deployment/readback cannot
substitute for a real ordinary-member walkthrough. No synthetic welcome or pick is
sent to production. The actual pinned onboarding/rules messages are authorized
production content. No new subscriptions or infrastructure plans are purchased.

Production database backup retention/PITR is not returned by the current Render
connector. CI backup/restore covers disposable synthetic evidence only; production
restore coverage must remain unverified until a backup inventory and isolated
restore can be inspected through the Render dashboard or an authorized operator.
