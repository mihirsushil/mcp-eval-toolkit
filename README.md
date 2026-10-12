# MCP eval toolkit

Does a change to an MCP server make models worse at using it?

This repository starts with a reproducible poker-analytics experiment over
[mcp-tef](https://github.com/StacklokLabs/mcp-tef). It currently provides a CLI,
versioned cases, isolated server variants, structured traces, strict scoring,
human-review inputs, and paired A/B reports with uncertainty intervals.
There is no web interface yet.

## Two-minute demo

From this directory, run a scripted A/B experiment through actual mcp-tef and
poker MCP tool execution. It needs no model credentials and makes no live model calls:

```sh
.venv/bin/mcp-eval demo
```

The command prints a link/path to `scored/report.md` in a fresh evidence directory.
Four development cases run twice against each variant (16 evaluations). Fixed
responses deliberately introduce two improvements and one regression so you can
inspect the scorer's behavior. Every demo artifact is labeled scripted; the
reported rates demonstrate the report, not model capability.

The report shows call checks, case verdicts, pending human review, paired
confidence intervals, and links to raw evidence. See [scoring and review](docs/scoring.md).

## Current evidence

The local preflight on October 6, 2026 verified:

- 30 structurally valid cases: 24 development and six held out.
- All six tools discovered from the actual MCP server; stdio and HTTP definitions match.
- 18 development-case tool calls executed successfully against a copy of the
  existing 4,992-hand public bootstrap database.
- All 24 development cases accepted by the running mcp-tef API.
- Variant B changes only the `compute_stats` description; schemas and other
  descriptions match variant A.
- One **scripted-model integration** completed the full mcp-tef agent → MCP
  execution → SQLite result-storage path. This is an infrastructure test.
- The subsequent scripted A/B demo completed 16 evaluations with real tool
  execution and structured-message capture; all 16 traces were scored. Six
  text responses correctly remained pending human review.
- 44 focused tests cover case validation, argument scoring, missing evidence,
  stale labels, pairing, and error handling.

**Live model evaluations: zero. No model accuracy or regression claim is available.**
Cases and rubrics are authored drafts awaiting human review. The held-out cases
have had structural/schema validation only, with no model evaluation or tuning.

The new project is on branch `feat/phase-zero-baseline`. Existing poker-analytics
and mcp-tef source checkouts are unchanged.

## Run locally

The sibling checkouts are expected at `../poker-analytics` and `../mcp-tef`, each
with its own `.venv`. The poker interpreter runs its MCP 2.x server; the toolkit
and upstream clients use their own locked environments. This avoids changing an
existing project's dependency versions.

From this directory, `uv sync --frozen` installs this project's locked dependencies.
The upstream checkout also needs `uv sync --frozen` in its directory.

Check case structure without starting services:

```sh
.venv/bin/mcp-eval validate
```

Exercise actual MCP tools, create upstream cases, and run the scripted integration:

```sh
.venv/bin/mcp-eval preflight
```

This command starts temporary servers bound to `127.0.0.1`, copies the poker
database, writes a fresh evidence directory under `artifacts/`, and stops its
servers when finished. It never calls a live model. Override checkout locations
with `--poker-repo PATH --tef-repo PATH`.

Run the live development A/B baseline after choosing a model and setting the
provider credential in your shell environment:

```sh
.venv/bin/mcp-eval baseline --provider openrouter --model PROVIDER_MODEL_ID --repeats 3
```

Replace `PROVIDER_MODEL_ID` with the chosen provider's exact model ID. OpenRouter
uses `OPENROUTER_API_KEY`; Anthropic uses `ANTHROPIC_API_KEY`; OpenAI uses
`OPENAI_API_KEY`. Ollama uses `--provider ollama --model LOCAL_MODEL_ID --base-url
http://127.0.0.1:11434/v1` and needs a running local model. Keys are passed in an
HTTP header and are not written to manifests.

Three repeats means 144 upstream evaluations: 24 cases × two variants × three
repeats. Each evaluation may involve multiple model calls. One repeat is a
smoke run, not a convincing regression measurement. Errors are retained and stop
the batch. The adapter polls each upstream run for at most five minutes.

The default split is always `dev`. Final held-out runs require both
`--split heldout --final-report`; freeze prompts, descriptions, expectations,
and rubrics first. This is an explicit workflow guard, not access control.

## Read the output

Each evidence directory contains:

- `manifest.json`: source commits, dirty state, source hashes, Python/package
  versions, suite hashes, database checksum, tool hashes, and experiment metadata.
- `tools-A.json` / `tools-B.json`: actual MCP `tools/list` responses.
- `tool-executions/`: raw responses from development fixture calls (preflight only).
- `upstream-probes/`: executable scoring probes and the explicitly scripted
  integration transcript (preflight only).
- `mcp-tef.db`: isolated upstream SQLite storage.
- `runs/` and `report.md`: raw upstream results and links (baseline/demo).
- `traces/`: lossless structured agent messages, linked by upstream run UUID.
- `suite.json`: the exact selected case suite frozen at evaluation time.
- `scored/`: deterministic scores, paired summaries, Markdown report, and review inputs.
- `failure.json`: diagnostic if the command could not complete.

Tool responses and fixture databases remain local and ignored by Git. Review
artifacts before sharing them. The current fixture uses the poker project's
existing public bootstrap records; player identifiers are already hashed.

The current upstream classification is preserved verbatim. `TP` means a tool
name matched; it is **not** a full case pass. The scorer independently validates
schemas, expected arguments, forbidden/unrequested filters, accepted alternatives,
and equivalent defaults against the structured messages. Clarification and
no-call answer quality still require human review. Reported rates explicitly
measure deterministic tool behavior; pending reviews never become full case passes.

## Experiment and build gate

Read [the experiment specification](docs/experiment.md) and
[the evidence-backed upstream findings](docs/phase-zero-findings.md).

Phase 0 remains open until a real model baseline and controlled description
comparison are run and reviewed. The initial findings favor extending or
contributing to mcp-tef; a separate general-purpose runner is not yet justified.
The implemented scorer and reporting layer address the reproduced upstream gaps
without replacing its execution engine. Multi-step golden paths, memory/retrieval
suites, live-model calibration, and CI regression gates remain later milestones.

Run focused tests with `.venv/bin/pytest -q`; run static checks with
`.venv/bin/ruff check src scripts tests`.
