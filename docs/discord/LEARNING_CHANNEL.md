# JABBAZI learning channel

The owner requested renaming betting-basics to `📚｜learn-how-to` and publishing a
practical beginner guide. `learn-how-to.json` contains 20 ordered messages (an
index, 18 lessons and a final checklist), each below Discord's 2,000-character
limit. Examples are hypothetical; the current JABBAZI reference is $30/unit,
while members choose their own dollar unit.

The publisher resolves exactly one existing channel, verifies the configured
server owner, adds resolved official-channel links, and changes only the name and
topic. It never changes role permissions or pings members. Each message is claimed
in PostgreSQL before sending; ambiguous sends stop for review. No repeated posts
on a rerun of the same version. It preserves existing message history.

On the existing worker with its securely configured bot credential:

```
python tools/discord_learning.py
python tools/discord_learning.py --apply
```

The first command is read-only and prints the resolved target. The second requires
existing bot permissions to manage that channel and send messages. A 403 is an
access blocker; do not grant Administrator to work around it. Publishing and
pinning must only be reported as complete after actual Discord verification.

If Send Messages is already permitted but Manage Channel is unavailable, publish
the authorized lessons without changing permissions or channel metadata:

```
python tools/discord_learning.py --apply --publish-only
```

This reports `rename_completed=false`. The owner can rename the channel separately;
a later normal `--apply` changes the metadata and skips already delivered lessons.

Settlement references were checked September 23, 2026 and are included in the
last lesson. Book-specific rules still control each wager. The guide does not
claim that teaching NBA, tennis, props or touchdown markets makes their models
available. Current NFL/MLB forecasts remain experimental research.
