# Open-source candidate review

Status: **local candidate acceptance PASS; publication NOT AUTHORIZED**.

## Isolation and tests

- Fresh independent Git project and virtual environment; core dependencies are official SDK, langchain-core, Pydantic and jsonschema. TradingAgents and LangGraph absent in the dedicated core wheel environment.
- 127 offline tests passed; 2 expected skips (user-opt-in live suite, separately installed TradingAgents). Real SDK startup is forbidden in offline fixtures.
- Four real SDK suite tasks passed: sync/async calls, two isolated agent threads and state merge, actual LangGraph ToolNode, native Pydantic. Sanitized token/elapsed results in LIVE_VALIDATION.md. No new actual financial study.
- Optional original full TradingAgents Graph with extracted provider passed offline, including three unchanged original schemas. Existing source project's regression remained 1430 passed / 99 subtests, 1 skipped / 1 deselected / 20 warnings.
- Source Codex worktree stayed at 194454e with no tracked changes; original stable v0.6.0 checkout stayed unchanged. No environment was modified there.

## Distribution and licenses

- wheel/sdist build and Twine checks passed. Metadata explicitly set to 2.4 to resolve the local Hatch 2.5 vs Twine validator mismatch; license-expression/files preserved.
- Final core wheel installed in a separate environment without source imports, TradingAgents or LangGraph. Standard BaseChatModel invocation passed offline and one final genuine SDK Hello returned WHEEL_OK (6,209 Tokens / 9.198 seconds). Five actual tasks total: 37,567 Tokens, no retries/fallback/UNKNOWN.
- Canonical license-content hashes check both source and archives; a temporary workspace miswrite was caught and restored before the final rebuild. No corrupted archive was published. Apache-2.0 text retained verbatim, extraction/modification NOTICE supplied. Three MIT texts/copyright notices retained verbatim; their wheel/sdist presence confirmed. Dependency SDK is not vendored. Relative source hashes and design provenance recorded.
- Financial vendor redistribution rights are UNVERIFIED. Accordingly no original OHLCV/SEC data, research report, financial tool log or private prompt is included; only accepted technical E2E counts are summarized. A provider/library code license is not treated as a data license.

## Credential/privacy review

- New Git history only; original source history was not imported or claimed audited for publication.
- Candidate tree, every committed new-history blob, wheel and sdist are scanned for common key/JWT/bearer/secret-assignment patterns, credential filenames, private artifact paths and personal absolute paths. No matched secret values are printed.
- No local Codex authentication file, token or cookie was inspected, copied or exported. SDK-managed login remains inside the official runtime. Raw local integration logs stay in ignored private/ and are absent from Git/distributions.
- No automatic uploading, publish job, Codex login or secret use in GitHub Actions. Tracing disabled during test runs. API-key authentication is refused by the adapter.
- The scanner is bounded, pattern-based evidence rather than a proof that every possible secret is absent. Human review remains required before publication; diagnostics are sensitive by default and not automatically sanitized by the runtime API.

## Remaining limits / publication gate

Tool Calling remains experimental upstream. Token stream/astream, Native Thread Resume, async structured-wrapper cancellation, Windows/macOS/untested Python/runtime combinations, fault-injected live transport recovery and distributed exactly-once side effects are not certified. Remote Actions has not run because no remote repository was created.

Provisional names were checked against public PyPI/GitHub endpoints and were not found, but are not reserved and no owner was selected. A future approved publication must recheck owner/name, license/provenance, latest archive security checks and distribution contents. No repository has been created remotely and no package has been uploaded.
