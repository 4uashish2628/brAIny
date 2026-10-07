`/app/base.json` holds default settings and `/app/override.json` holds
environment-specific overrides.

Write `/app/config.json`: a deep merge of the two in which values from
`override.json` win. Nested objects are merged key by key; lists and all other
values from `override.json` replace the base value entirely.
