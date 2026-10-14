# Independent package live validation

2026-10-14, explicit user-authorized local run, official SDK managed ChatGPT login, gpt-6.1-sol. All assertions read actual SDK results; no financial market requests or synthetic live responses.

- 4/4 SDK tasks PASS, 4 distinct ephemeral Threads.
- invoke and executor ainvoke: two real agents concurrently returned their own fixed role labels; private contexts and merged LangGraph State verified.
- Original LangGraph ToolNode executed a local addition tool, native correlation IDs matched real ToolMessage/result, final answer 12.
- Native strict Pydantic response included Literal plus numeric and nullable fields; original class/wire validation PASS, no fallback/coercion.
- Input 31,288; output 70; cached 6,144 (input subset); total 31,358. Unknown tasks 0.
- Whole suite 37.164 seconds; independent agent overlap 13.554 seconds.
- No retry, no API Key, no remote publication. Monetary subscription bill is UNKNOWN; no API price is inferred.

Sanitized usage/version/assertion details: [live_integration_summary.json](live_integration_summary.json). Threads use aliases. Raw SDK transcripts, paths, Thread IDs, local checkpoints and detailed private logs are deliberately not distributed. Stream/native cold resume, transport fault injection and arbitrary application side effects were not live-certified by this suite.

## Final installed-wheel confirmation

After packaging and unsupported-option/error-privacy hardening, a separate core-only wheel environment (no TradingAgents or LangGraph) completed one genuine gpt-6.1-sol call and returned WHEEL_OK. Input 6,202 / output 7 / cached 0 / total 6,209; 9.198 seconds, UNKNOWN 0. See [clean wheel record](wheel_live_summary.json).

Extraction validation therefore used **5 successful SDK tasks**, input **37,490**, output **77**, cached **6,144** (input subset), total **37,567**. Sum of the two experiment elapsed measurements: **46.362 seconds**; these were separate runs, not one continuous workflow wall-clock interval. No retries/fallback or financial re-execution. Local target remained 60,000 Tokens; this is not an official quota or guaranteed service-side ceiling.
