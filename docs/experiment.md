# Phase 0 experiment

## Question

Does clarifying the `compute_stats` description improve personal-versus-population
routing and reduce calls when player identity is missing, without harming valid
tool use elsewhere?

This is a prospective experiment. No live model results were available when
the description and cases were authored. The description was based on the
development cases and server source, not held-out model feedback.

## Fixed inputs

- Poker source: `cf2584ce08065ac5ed7fbe3315f891119803e583`.
- mcp-tef source: `1553c31835eb0d9503725e77f078999673b3088f`.
- Public bootstrap fixture: 4,992 hands; the explicitly identified fixture
  player `376d6fd36aec498b` occurs in 139 seats. This is not the user's identity.
- Suite version 1, 24 development / six held out. All cases have an explicit
  context, request, action expectation, acceptable calls, rubric and reason.
- Variant A: original server definitions.
- Variant B: only the description in
  `experiments/compute-stats-description.json` is replaced in memory in an
  isolated server process. Tool behavior and schemas remain identical.
- Shared system prompt: `SYSTEM_PROMPT` in `src/mcp_eval_toolkit/tef.py`.
  Both variants receive exactly the same prompt. Case expectations and rubrics
  are never included in the model query.
- Model/provider: pending user choice. Prefer an immutable provider model ID;
  an alias alone does not prove the underlying weights stayed fixed.

Each run records the actual hashes and revisions; these reference revisions are
not silently checked out or imposed on the user's other repositories.

## Interpretation rules

Human review must happen before treating the draft cases as gold labels. Use the
same rubric for both variants, ideally with the variant hidden while labeling.
One correct tool call is expected for call cases; unnecessary additional calls
fail the action requirement. Clarification and no-call cases require zero calls.
Grade the quality of the clarification separately. All arguments must be valid
against the captured schema; compare required values exactly. A legitimate
explicit default is equivalent to omission. Do not allow extra filters that
change the requested population. `absent_or_null` explicitly forbids such
filters on selected cases.

The schema supports alternative acceptable first calls. Current cases have one
deliberately unambiguous call each. The upstream adapter only exports the primary
expectation and flags any alternatives for manual review. Multi-step route
alternatives will require a later case-spec revision.

Do not reinterpret an upstream TP as a passed case: the upstream matcher
classifies by tool name and separately reports a partial parameter score.

Case order alternates A/B then B/A to reduce simple ordering bias. No claim is
made that identical random seeds are paired. The pinned upstream does not apply
the stored temperature, timeout or retry settings to the Agent; the manifest
records requested settings and this caveat. Resolve this upstream or explicitly
report the provider defaults before claiming controlled sampling settings.

## Next measurement

1. Review development expectations, then run a single-repeat smoke baseline.
2. Inspect raw transcripts, especially missing-identity and population cases.
3. Freeze a calibrated rubric before repeated A/B runs; keep infrastructure
   errors separate from model failures.
4. Compare case-level differences across repeats. Report case count, repeat
   count and an interval on the difference. Do not pool repeated attempts on
   the same case as independent cases; a paired case-cluster bootstrap is one
   candidate for Phase 3. With only 24 development cases, uncertainty may be wide.
5. Re-run the unchanged suite to characterize noise. Freeze all choices before
   the final six-case held-out evaluation.

These held-out cases are authored in the same project and are small in number.
They test a limited set of withheld variations, not broad generalization to
unseen MCP servers or users. Cross-server testing is a later milestone.

No judge is required for Phase 0. No model-ranking, regression significance,
speedup, or accuracy claim is supported by the infrastructure tests alone.
