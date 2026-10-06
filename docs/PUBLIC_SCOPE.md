# Public repository scope

This is a standalone Topic Monitoring pipeline, not a copy of a working directory.

Retained: the stable media matchers, market/customer-service parsing and incremental identity rules, monthly/weekly/star/customer-service calculations, dashboard template and raw-feedback drill-down. The standalone CLI supplies paths and profile configuration, commits one history file after successful reporting, and serves static files locally.

Excluded: historical classification libraries, real reviews and conversations, field-mapping exports from real datasets, report-site data, Node services and solved-status API, private publishing/deployment scripts, local skill executable wrappers, backups, exploratory scripts, one-off extraction/backfill code, legacy tests containing real data. The dashboard's browser-local solved markers replace internal server storage.

All CSV examples, cross-project regression cases, screenshot and demo dashboard are artificial. The published dashboard is regenerated from the examples; no historical output or frontend build containing real data is used. Local output trees are ignored and excluded from `public-files.txt`. The privacy checker rejects unexpected files and scans the allowlisted text for personal filesystem paths, private-network addresses/domains and common credential forms. It is an additional guard, not a guarantee against every possible secret format; manually inspect additions to the allowlist.

Compatibility verification compared both classifiers over the complete available legacy corpus, monthly/weekly/metadata/customer-service/star/raw-audit JSON, the complete HTML core payload, and both detail JS assets. Counts, labels, topic order, denominators and trend data matched. Generic brand wording changed in a small number of classification reason strings; the labels did not change. HTML title, profile/source metadata, audit metadata and local solved-state storage are deliberately different. The original runtime directories were not changed.

Extensions tested separately: configurable substring topics, zero customer-service records, empty platform scopes, datasets without a complete calendar month, unrated feedback and TSV delimiter support. Those add previously unsupported cases without changing the observed legacy metrics. The raw-feedback UI also corrects JavaScript null-rating coercion, shows unrated feedback explicitly, and limits manual follow-up status filters to rated 1–3-star records. These presentation fixes do not alter topic counts or rates. The frontend currently uses Chinese UI text; source platform/channel recognition is still the media-oriented importer. A profile change requires a fresh dataset, and updated/ambiguous import records still require human review.

The CLI only reads local inputs and generates local reports. It does not create repositories, push commits or deploy dashboards.
