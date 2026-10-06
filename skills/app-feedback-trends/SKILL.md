---
name: app-feedback-trends
description: Import local app feedback incrementally, classify configured topics, and generate a local trend HTML dashboard with the app-feedback-trends CLI.
---

# App Feedback Trends

Use the project's Python CLI. The Skill is optional; ordinary users can run every command from README without installing it.

1. Locate the project and read README. Select an existing profile or create a simple profile in this project. Do not change the profile of an existing dataset.
2. Run `python trends.py preview --data-dir outputs/<dataset> --profile profiles/<profile>.json --ios <file>`; use `--android` and `--cs` as needed. Inputs are local CSV, TSV or XLSX files. There is no data acquisition service.
3. Inspect `preview.json` counts, warnings, updated records and ambiguous matches. Existing records stay unchanged. Do not turn ambiguous or updated records into new feedback automatically. Correct invalid source files and regenerate the preview.
4. If importing new feedback is within the user's request, run `python trends.py apply` with the same dataset/profile. It classifies only new records, rebuilds the dashboard, then commits history.
5. Show the generated `report.html` or run `python trends.py serve` with the same dataset/profile for a local preview. Explain the topic rates using README's denominators, and report rejected or skipped records.

Never upload private inputs, accumulated history, generated report assets or original feedback as part of source publication. Use only the synthetic demo for public previews. This Skill does not publish or push anything.
