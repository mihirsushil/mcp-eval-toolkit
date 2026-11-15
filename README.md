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

### 1. Live A/B Baseline (October 20, 2026)
- **48/48 live evaluations completed and scored** (`0` missing/errors) across 24 development cases × 2 server variants (`A` vs. `B`) using `anthropic/claude-haiku-4.5` via OpenRouter.
- **100% deterministic-check pass rate** on both variants (`0.0 pp` difference, 95% case-cluster bootstrap interval `[0.0 pp, 0.0 pp]`).
- **Model-choice failure surfaced:** `openai/gpt-4o-mini` was evaluated first and ruled out after reproducibly failing to terminate tool-calling even on single-call cases (e.g., calling `get_hand(id=1)` eight times identically after receiving valid responses), motivating the `request_limit` and `tool_calls_limit` guards.
- **Upstream bug diagnosed and fixed ([StacklokLabs/mcp-tef#145](https://github.com/StacklokLabs/mcp-tef/pull/145)):** `temperature`, `timeout`, and `max_retries` were recorded in metadata but silently dropped before reaching the model client, and `output_type` forced structured-only termination so clarification/no-call text was discarded. Fixed upstream with 7 regression tests and paired with plain-text termination support in `scoring.py::observe()`.
- **Human rubric review & Judge Calibration (`mcp-eval calibrate`):** All 12 live clarification/no-call responses in the 48-evaluation baseline were human-reviewed (`12/12 pass`, bound by `trace_sha256` and `case_sha256` in `reviews/baseline-20261020T005713.732529Z-human-reviews.json`). To avoid single-class prevalence degeneracy ($p_e = 1.0$) when calibrating automated judges, `cases/poker/judge_calibration.json` pairs the 12 live positive traces with 12 failure-mode contrast traces (`n = 24`, 50% prevalence) and measures chance-corrected agreement via **Cohen's $\kappa$** (`mcp-eval calibrate`, achieving $\kappa = 1.0000$, $p_o = 100\%$, $p_e = 50\%$).

### 2. Infrastructure & Suite Verification
- **38 structurally valid cases:** 32 development cases (`cases/poker/dev.yaml`) and 6 held-out cases (`cases/poker/heldout.yaml`).
- **All six tools discovered** from the live MCP server; stdio and HTTP definitions match, and Variant B changes only the `compute_stats` description.
- **Scripted A/B demo (`mcp-eval demo`):** 16 evaluations with real MCP tool execution and structured-message capture; catches two deliberately introduced improvements and one regression without requiring API keys.
- **55 unit tests** (`tests/`) covering case validation, strict argument scoring, missing/tampered evidence, stale review hashes, resume drift guards, experiment freeze contracts, paired cluster bootstrap intervals, and Cohen's $\kappa$ judge calibration.

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
