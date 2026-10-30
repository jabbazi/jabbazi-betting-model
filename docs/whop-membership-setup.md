# Whop membership integration

JABBAZI VIP is configured in Whop at USD 29 per month, hidden with waitlist
enabled. Business `biz_Po7hFcUreS6QYk`, product `prod_JnZJaFPW8Q1rG`, Discord
experience `exp_FiVuSxtmtRoRjB`. Checkout has not been opened for launch.
The owner approved the Discord app's additional 3% transaction fee and its limited
OAuth permissions. Payment processing and applicable additional fees are separate.

Whop must manage only `JABBAZI WHOP SUBSCRIBER`, a separate zero-permission source
role. Never assign the existing manual VIP role, a derived verified role, the
community role, or an administrator role through Whop. Whop stays below all other
roles and above its dedicated subscription role. Its approved bot permissions are
Manage Roles, Create Invite, View Channels, Send Messages and Embed Links only.
No kicks, bans, channel/server management, webhooks, message management or pings.

Set `JABBAZI_WHOP_SETUP_ENABLED=true` on the existing Discord worker only. Startup
audits the installed bot and existing VIP tier, backs up the gate/roles/channels,
creates or verifies the dedicated source, and appends its mapping to the existing
rules configuration. It never changes existing member roles or channel grants.
The new source maps to the same derived tier as the existing JABBAZI VIP source.
Either valid source preserves access, but a new member must still accept rules.
Removing the Whop role cannot erase an independently granted manual VIP role.

In Whop, restrict the Discord app to the JABBAZI VIP product and assign only the
dedicated subscription source. Set cancellation to Remove Role, never Kick User
or Remove All Roles. Leave past-due role unset. Configure an owner diagnostics
channel only if the bot can access it without broader privileges.

Before launch, verify a genuine ordinary-member purchase/claim, rules acceptance,
both VIP commands, and expiry/cancellation. Owner access is not evidence of these
flows. No real charge or synthetic member is created by automated tests.
Channel revocation depends on the running JABBAZI reconciliation worker; existing
app sessions retain their established maximum 15-minute lifetime. Neither an
installed bot nor a successful software deployment proves the billing lifecycle.

Rollback: keep sales closed; detach the Whop role from the hidden product first.
Disable the setup flag, restore the recorded prior rules config only after checking
for intervening changes, and deploy the preceding worker commit. Before any real
members have been admitted, the extra role can remain inert. Once paying members
exist, review active entitlements before rollback. Never delete manual roles,
historical ledgers, acceptance records, or database indexes.
