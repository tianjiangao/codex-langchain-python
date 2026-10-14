# Security

## Scope

This alpha controls a local official Codex runtime. The runtime owns authentication. The package does not read auth files, tokens or cookies, invoke private ChatGPT HTTP APIs, or convert a subscription login into an API key. It reads `config.toml` only to enumerate and disable inherited MCP names; config values are never logged. The SDK/CLI itself necessarily manages authentication under its official behavior.

Default SDK threads are ephemeral, read-only, without environment tools. Built-in shell/file/web/plugin/agent features are disabled; approval/permissions requests are declined. Only caller-registered dynamic tools can be requested and their JSON arguments and returned correlation IDs are validated. Arbitrary caller Python functions can have side effects: **review/authorize them in the executor**, beyond SDK sandbox controls.

## Data and logs

`event_log_path`, `model.evidence`, structured evidence, checkpoints and tool results can contain prompts, tool data, server error text and private IDs. They are diagnostic records, not an automatically sanitized public dataset. Do not log secrets or upload raw records. This repository's `private/` and `work/` are ignored and excluded from distributions. LangChain callbacks/tracing are caller-controlled; enabling external tracing can transmit content. Offline CI disables tracing and real runtime startup.

Async cancellation is best effort. Tool execution may already have happened. SQLite integrity seals and duplicate task/correlation guards do not provide distributed exactly-once transactions. Use idempotency keys and application-owned side-effect transactions. Native persistent Thread Resume is not implemented by this ephemeral adapter.

## Reporting

Do not post credentials, private logs or full checkpoints in an issue. Use a private channel to the maintainer who supplied this checkout; a public security-advisory channel will be assigned only if publication is approved. Provide versions, a minimal synthetic reproducer and sanitized error category instead of authentication material.

## Release review

A allowlist-oriented tree/archive/Git-history scanner is provided in `scripts/audit_release.py`. It rejects common credential patterns, personal absolute paths, credential filenames and private artifact paths without printing matched values. It cannot prove the absence of every possible secret. No local authentication file is inspected during this review. Initial Git history is new, not imported from the source project. A human must recheck before any public publication.
