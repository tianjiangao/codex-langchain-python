# Changelog

- First remote CI exposed a mock fault-test scheduling race on Python 3.13: reserve the short deadline for timeout injection, allow transport/cancellation tests their own deadline, and complete all matrix jobs even if one fails.

## 0.1.0a1 — GitHub source alpha (PyPI unreleased)

- Extract verified runtime, messages, native dynamic tools, schema normalization, usage and checkpoint helpers from Codex Adapter source commit `194454e`.
- Expose community `ChatCodexSDK`, `UsageLedger` and `CheckpointStore` without TradingAgents dependency.
- Generalize caller-bound tool names and security instructions; preserve correlation/allowlist validation.
- Use official SDK bundled runtime by default, isolate temporary working directories, and identify the client as a community adapter.
- Unify text/tool/structured calls under the validated native lifecycle so failures retain usage evidence.
- Add executor-based `ainvoke` and request-scoped best-effort cancellation; do not claim native async transport.
- Refuse unverified token streaming explicitly; preserve Pydantic and strict wire validation.
- Add offline CI, independent arithmetic live suite, optional original-framework example and provenance/licenses.
- Reject unsupported constructor/invocation options rather than silently treating token/sampling controls as enforced.
- Keep raw live records private and exclude original financial data and research logs.

Public GitHub source publication approved by the maintainer. No PyPI package has been uploaded.
