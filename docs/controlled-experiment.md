# Controlled description experiment — October 21, 2026

## Prospective protocol

Question: with a fixed poker assistant system prompt, does the more explicit
compute_stats description improve scope/identity handling and neighboring-tool
routing without regressing other tools?

The October 20 smoke baseline already included compute_stats requests (three
aggregate cases, plus missing-identity and neighboring-tool cases). It scored
48/48 deterministic checks. The claim that none of its cases exercised the
changed description was incorrect. A ceiling on explicit authored cases, and
a system prompt that already instructs identity clarification, are plausible
reasons that the descriptions performed equally.

Keep both existing descriptions and the system prompt unchanged. Add eight
development challenges before new model feedback: known-identity population
requests, a single population position, an unmapped screen name, an unidentified
opponent despite a known user, plain-language personal metrics, position and
threshold routing, and a definition despite a known identity. The original six
held-out cases remain unchanged and receive no model calls before the freeze.

- Model: anthropic/claude-haiku-4.5 via OpenRouter, matching the successful prior
  baseline. This is an alias, not a guarantee of immutable weights/routing.
- Temperature 0; timeout 60 seconds; no provider retries; at most eight model
  requests and five tool calls per evaluation.
- Development: 32 cases × two variants × three repeats = 192 evaluations.
- Final held-out: six cases × two variants × three repeats = 36 evaluations.
- Alternate AB/BA order by case and repeat. No matched sampling seeds.
- Primary endpoint: paired mean difference in deterministic single-call/no-call
  correctness over the full split. Report the authored-case cluster bootstrap
  interval and counts. Repeats are not independent cases.
- Diagnostic endpoints: family breakdown and case/variant outcome variability.
  These are descriptive, not multiple independent significance tests.
- Text quality: separate blinded human rubric review, not implied by tool checks.
  Until a human supplies labels, no fully reviewed answer-quality claim is made.
- Do not select a new description or model based on final held-out feedback.
  A zero difference is a valid finding; do not keep tuning to manufacture a win.
- Infrastructure/provider errors remain visible. On resume, archive failed
  upstream records before retry. Do not repeatedly retry a behavioral failure
  until it passes. Report any retries and incomplete evidence explicitly.

## Freeze and completion

`mcp-eval freeze DEV_DIRECTORY FREEZE_FILE` requires a complete development
report with at least three repeats. It records source snapshots, environments,
both suite hashes, descriptions, tool snapshots, fixture, settings, and repeat
count. The final baseline requires `--split heldout --final-report --freeze
FREEZE_FILE` and rejects different inputs before any final model calls.

Resume refuses changed settings, suite, source state, environments, fixture,
repeat count, or tool definitions. It does not overwrite the previous manifest
on a rejected input change. Saved traces and checksums remain local under
artifacts/. Summaries and the research interpretation will be published in docs
only after all planned evaluations are complete.

Completion means a validated implementation, the repeated development and
frozen held-out runs, a reproducible findings report, and the blinded review
packet. Human rubric approval remains explicitly separate until supplied.
