# Codex instructions: TradeScout

## Purpose
A practical China sourcing B2B prospecting assistant for a Yiwu multi-category merchandise exporter.

## Priorities
1. Evidence-first research. Do not present model-generated guesses as facts.
2. Maintain cold-email guardrails: subject <=6 words; body <=50 words; plain text, no attachments, no made-up praise, no invented buyer/contact.
3. Preserve source URLs with all evidence; score only evidence supported by a relevant source. Note: source URLs are model-provided and must be manually checked; a future version should fetch and validate citations.
4. Never bulk-send emails; require user review before any dispatch. No automatic SMTP credentials, scraping behind access controls, or bypassing site policies.
5. Keep API keys out of git, logs and SQLite. Use .env only locally.
6. Python modules: `engine.py` API+scoring, `storage.py` SQLite persistence, `app.py` Streamlit UI. Add tests for changes.
7. Local tests: `python -m pytest -q`.

## Next milestones for Codex
- Add direct verification of official site URLs, source link reachability and relevance with safe outbound HTTP (strict SSRF protections).
- Add editable evidence with manual accept/reject and human-readable audit trails.
- Implement lead deduplication by canonical hostname across discovered countries.
- Add CRM next-follow-up dates with user-controlled reminders; no automatic email dispatch.
- Add CSV imports and exports, filters, and optional Gmail draft integration only with explicit authorization.
- Add historical activity log, pagination, and account authentication before any public deployment.
