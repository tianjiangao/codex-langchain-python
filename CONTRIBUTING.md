# Contributing

This is an unreleased community extraction. Keep core imports free of TradingAgents and application-specific financial models/vendors. Reuse the extracted tested layers rather than introducing private authentication transports.

Create a virtual environment and run `pip install -e '.[dev]'`, `pytest -q`, `ruff check src tests examples integrations scripts`, `python -m build`, and `python -m twine check dist/*`.

Offline tests must mock SDK startup and need no login, credential file or API key. New protocol/lifecycle behavior needs meaningful boundary tests. Live tests require an explicit local opt-in and must never be automatically executed by GitHub Actions. Mark unsupported/experimental behavior accurately; do not treat mock output as live evidence.

Do not commit auth/config files, cookies, keys, private transcripts, absolute personal paths, vendor data, `private/` or `work/`. Preserve original license texts, notices and modification provenance. Run `python scripts/audit_release.py` before committing and building; inspect distribution contents too.

A publication must be explicitly approved by the maintainer, after owner/name checks, security/license review and live compatibility verification. There is intentionally no publishing workflow. No contributor contact or public repository identity has been assigned yet; Git author metadata in this candidate is a generic non-personal identity.
