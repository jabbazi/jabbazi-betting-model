# Event context and team identity

Put reviewed JSON mappings here. No secrets belong in this directory.

`nfl_events.json` and `cfb_events.json` must use current Odds API event IDs:

```json
{
  "EXAMPLE_EVENT_ID_REPLACE_ME": {"neutral_site": false}
}
```

The example ID is not real. Verify the venue against the current official schedule.
Football baseline predictions are withheld when venue status is unknown.
Set `JABBAZI_NFL_EVENT_CONTEXT=config/nfl_events.json` or its CFB equivalent.

CFBD school names and bookmaker school/mascot names often differ. Supply an
explicit dictionary from exact bookmaker name to exact training-history name:

```json
{"LSU Tigers": "LSU"}
```

Set `JABBAZI_CFB_ALIASES=config/cfb_aliases.json`. Verify every mapping against
the returned provider team identities. Unmapped teams receive no model estimate;
the program does not fuzzy-match schools. Team IDs are a future improvement.
