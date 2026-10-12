# Scoring and review

The scorer evaluates the model's actual structured tool calls. It does not use
mcp-tef's TP classification as a success label. The process-local launcher in
`scripts/tef_server.py` records Pydantic AI messages by upstream run UUID while
leaving the upstream source and model settings behavior unchanged.

## Deterministic checks

A call case requires exactly one accepted call, valid input arguments, matching
expected values, and no unwanted non-default arguments. A schema-defined default
can be omitted or explicitly supplied. Null and omission are equivalent where
the schema/default and case constraints permit them. Unknown arguments and
non-default filters that change the population fail. Expected call alternatives
are checked independently; any fully matching alternative is accepted.

Clarification and no-call cases require zero tool calls. Text quality is a
separate human judgment. A text response without tool calls can pass the action
check while its case verdict remains pending. A human failure is reflected in
the case verdict but does not retroactively change the deterministic action rate.

Extra calls, retries, schema violations, and tool errors fail the deterministic
check. Observed malformed arguments are failures; absent arguments in an
incomplete trace are evidence errors. Missing runs, missing traces, failed
upstream executions, and unrecognized message structures never become passes.

This scorer covers the current single-call suite. It does not measure the
correctness of poker analysis, retrieval grounding, or multi-step route quality.

## Evidence integrity

The run freezes `suite.json`, tool snapshots, and each structured trace's hash.
Offline reporting checks these hashes, case/query identity, trace run ID, and
requested provider/model identity. Duplicate records and changed snapshots are
rejected. Scoring source hashes are recorded in the summary so rescoring can be
audited separately from the original run.

This detects accidental drift; local hashes are not a cryptographic attestation
against someone who can rewrite both data and manifests. Sampling settings still
carry the documented mcp-tef forwarding caveat; recording does not silently fix it.

Old Phase 0 preflight artifacts lack a frozen evaluation suite and structured
evaluation traces. They cannot be retroactively treated as a scored baseline.
In particular, the pinned upstream serializes actual `{}` arguments as SQL NULL
in its match repository. The new recorder preserves the original empty object.

## Rerun the report

Re-score an existing demo or live baseline without calling any model or tools:

```sh
.venv/bin/mcp-eval report ARTIFACT_DIRECTORY
```

Replace `ARTIFACT_DIRECTORY` with the evidence directory printed by the demo or
baseline command. Generated files live under `scored/`; original traces and
upstream results stay unchanged.

## Human review

Read `scored/review-queue.json`, which includes the actual text, request, rubric,
and trace/case hashes. Copy `scored/review-template.json` to `reviews.json` in the
evidence directory. For each reviewed row, set `decision` to `pass` or `fail`,
name the reviewer, and give a concrete rationale. Remove unreviewed rows from the
submitted file; they will remain pending. Do not edit the two hashes or key.

Apply those labels and regenerate the report:

```sh
.venv/bin/mcp-eval report ARTIFACT_DIRECTORY --reviews ARTIFACT_DIRECTORY/reviews.json
```

Use a file outside `scored/` so regeneration cannot overwrite your labels.
Incomplete labels, duplicates, stale hashes, and labels for unknown runs are
rejected. No human labels have been supplied for the real demo artifacts yet.
The test suite's labels are test fixtures only.

## Uncertainty and incomplete data

For each case, average repeated binary call-check outcomes separately for A
and B. Compute the per-case difference and resample cases as paired clusters,
keeping every repeat together. The report uses 5,000 draws with a recorded seed
and percentile 95% intervals for each rate and the difference.

A case contributes only if every planned repeat in both variants has a score.
Missing or erroneous attempts exclude that entire case from the paired summary.
Coverage and an INCOMPLETE warning remain visible; partial comparisons can be
biased and must not be presented as a full-suite result. A one-case comparison
reports counts and a difference but no uncertainty interval.

The intervals describe variation across this authored case set. They do not
establish broad generalization. Small or homogeneous suites can yield wide or
degenerate intervals. Scripted demo intervals are illustrative, not evidence
about language-model performance.
