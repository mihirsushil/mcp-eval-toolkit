# Phase 0 findings — October 6, 2026

Status: infrastructure exercised; live-model baseline pending. The build /
extend / contribute decision remains provisional.

## What was run

The successful local evidence directory is
`artifacts/preflight-20261006T185911.530413Z/`. Its manifest records source and
environment hashes. `preflight.json` records 30 validated cases, six discovered
tools, 18 successful development fixture calls, and 24 cases created through the
real mcp-tef REST API. No held-out query was sent to a model.

The scripted integration used Pydantic AI's `FunctionModel` to request population
statistics, received the real server result, returned the structured confidence
result required by mcp-tef, and saved a completed upstream run. It exercised two
scripted model turns and a real MCP call. It did not evaluate a language model.
See `upstream-probes/scripted-run.json` for the raw transcript and tool snapshot.

Both server variants use the same copied database. Discovery verified that
only `compute_stats.description` changed. The original poker database and both
source checkouts were left unchanged.

## Existing capability confirmed

At [the inspected upstream revision](https://github.com/StacklokLabs/mcp-tef/tree/1553c31835eb0d9503725e77f078999673b3088f),
mcp-tef already provides live HTTP MCP discovery, an agent that executes tools,
ordered and unordered expected-call matching, raw transcript storage, and
SQLite-backed results. The scripted integration exercised the ordered
single-tool route through that machinery. Multi-step runtime behavior was
inspected in source but has not yet been evaluated with this suite.

A new generic runner justified only by tool selection, saved transcripts, or
ordered expected calls would overlap substantially with these capabilities.

## Reproduced limitations

`scripts/probe_upstream.py` executes the upstream matcher and records the
results in `upstream-probes/probes.json`:

- **Unwanted filters can earn full parameter credit.** For expected arguments
  `{}`, `compute_stats(player_hash="invented")` receives TP and 10/10. Our
  population-statistics case must reject this result because it changes the
  requested population.
- **Correct tool selection is distinct from correct arguments.** Expected
  `position="BTN"` versus actual `position="BB"` receives TP and 7.5/10.
  A report counting TP as success would overstate this suite's accuracy.
- **Valid optional arguments can lose points.** Expected `position="BTN"`
  versus actual `position="BTN", player_hash=null` receives 7.5/10 for an extra
  parameter, even though null is valid and selects the same population.
- **No-call classification does not distinguish clarification quality.** Empty
  expected and actual call lists produce TN. A useful identity question and an
  irrelevant text answer need separate rubric review.
- **Requested settings are not necessarily effective settings.** The executable
  construction probe captures Agent keyword arguments and confirms that no
  `model_settings` are forwarded. Source inspection of `EvaluationService` and
  `LLMService` shows temperature is stored but not forwarded, and service timeout /
  retry fields are not wired into Agent construction. This must be disclosed
  before claiming fixed temperature or retry behavior.

These are deterministic implementation probes, not observed model failures.
They establish that the desired rubric differs from the upstream scoring
semantics; a live run is still needed to determine their practical frequency.

The poker server also uses lexical timestamp comparisons. A date-only upper
bound can omit that day's timed records. Initial time-filter cases therefore
use explicit full timestamps. No server bug fix was bundled into this experiment.

## Candidate contribution and next decision

The smallest promising extension is configurable argument assertions that
distinguish required values, forbidden filters, and equivalent defaults, plus
a settings-forwarding regression test. Reproducible A/B reports can sit around
the existing execution engine.

Before building an independent harness, run the development baseline with a
chosen model, inspect the mismatches against the written rubric, and determine
whether an upstream contribution or a thin extension can satisfy the actual
need. No claim that the missing capabilities are absent from every upstream
branch, release, or competing project is made here.
