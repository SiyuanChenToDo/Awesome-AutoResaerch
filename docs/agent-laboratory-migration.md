# Agent Laboratory → SAGE: actual mechanisms and boundaries

This integration is a maintained functional decomposition, not a runtime wrapper around a vendored checkout. The [immutable source snapshot](../third_party/agent_laboratory/README.md) pins Agent Laboratory at `d9017d90e329112d2a80b7712f37ee9094d2cd27` under MIT (Samuel Schmidgall, 2025). Runtime modules never import it. CoI proposal behavior and original CLI remain compatible.

## Mechanism map

| Upstream source and function | Maintained SAGE implementation | Deliberate changes |
|---|---|---|
| `mlesolver.py: Replace.parse_command`, `Edit.parse_command/execute_command` | [execution/commands.py](../sage/execution/commands.py) `apply_command` | Pure single-command parsing, full-match fences, strict zero-based inclusive bounds, no execution during parsing |
| `MLESolver.gen_initial_code`, `solve`, `process_command` | [execution/__init__.py](../sage/execution/__init__.py) `ExperimentRunner.run` | Finite attempts; malformed commands, failed generations and failed executions retained; syntax check before optional backend; best candidate chosen by fixed MSE |
| `code_repair` | [execution/prompts.py](../sage/execution/prompts.py) `repair_prompt`, runner repair branch | Preserve intended behavior and error context, finite repair allowance; cannot alter evaluator |
| `MLESolver.system_prompt`, `phase_prompt`, `generate_code_lines`, `generate_dataset_descr_prompt` | `generation_prompt` | Plan, numbered source, contract, attempt history; JSON scalar prediction IO; no library installation, hidden labels or evaluator edits |
| `MLESolver.reflect_code`, `feedback` | `reflection_prompt`, runner reflection stage | Concise development-only suggestions; preserved failed/negative evidence; no test-set generalization claims |
| `get_score` model reward / `best_codes` | [execution/contracts.py](../sage/execution/contracts.py) `EvaluationContract.evaluate`, best-attempt selection | Model reward intentionally replaced by host-owned scalar MSE computed from predictions and frozen targets; model cannot supply score |
| `papersolver.py: PaperSolver.gen_initial_report`, `system_prompt`, `solve` | [writing](../sage/writing/) section scaffold/generation and bounded review-driven revision | Structured JSON draft, supplied-source IDs only; no LaTeX compilation, web search, fake figures or submission |
| `agents.py: get_score` reviewer rubric, `PhDStudentAgent.phase_prompt` results interpretation | [review/report.py](../sage/review/report.py), writing evidence report | Explicitly non-independent model review, measured-vs-fixture-vs-unexecuted boundaries; deterministic rendered facts |
| Multi-phase upstream workflow | [orchestration/laboratory.py](../sage/orchestration/laboratory.py) `run_laboratory` | Same Runtime budget across CoI proposal, code engineering and writing; failures preserved |

The inline AI-Scientist credit in upstream `per_section_tips` is preserved in the snapshot. SAGE's section instructions are newly written rather than copying that table. Source and applicable MIT license must accompany derivatives.

## What is runnable

```
python -m sage laboratory --mode offline --output projects/lab-dry
python -m sage laboratory --mode offline --backend fixture --allow-execution --output projects/lab-fixture
```

Default dry-run generates and parses source and checks Python syntax without executing it. The fixture backend recognizes exact reviewed fixture source and dispatches trusted owned functions; it never evaluates generated Python. Synthetic scalar inputs and labels verify plumbing, not research effectiveness. Changing the topic does not change these into real research.

Generated candidate source is also saved as non-executed `candidates/attempt-N.py` files for review (do not execute it directly on the host). Output includes `result.json` (proposal, every candidate/repair, metrics, errors, report draft/review), `contract.json`, `config.json`, `audit.jsonl` and `report.md` plus `draft.md` when writing produces them. Output directories cannot be reused. Report Markdown is deterministic from recorded evidence; generated prose is separately labeled UNVERIFIED MODEL DRAFT in `draft.md` and JSON, with citation IDs preserved. No publication is performed.

## Explicit Docker development evaluation

The optional Docker backend executes candidate source inside a locally available, separately reviewed container image. It does not execute generated code directly on the host, pull images, install dependencies or provision Docker. Docker and Python 3 inside the image are prerequisites. No Docker engine was available in this implementation environment: the adapter is tested with fake subprocesses, not a real container smoke test. These controls are defense-in-depth, not a verified security sandbox or protection against Docker/kernel vulnerabilities.

Only scalar development prediction with fixed MSE is implemented, not arbitrary ML training, final-test evaluation, external data preparation or benchmark replication. A custom trusted backend can implement the same prediction interface; the operator is responsible for its isolation and authorization. Supplying an arbitrary backend grants code-execution capability and is not made safe by the protocol type.

Create and review a complete contract JSON, for example:

```json
{
  "protocol_id": "reviewed-demo-v1",
  "dataset_id": "user-supplied-scalars-v1",
  "split": "development",
  "features": [0, 1, 2],
  "targets": [0, 2, 4],
  "metric": "mse",
  "max_attempts": 3,
  "max_repairs": 1,
  "timeout_seconds": 10,
  "stopping_rule": "attempt_budget_or_zero_loss",
  "evaluator_version": "sage.scalar-mse.v1"
}
```

This is still toy data, not a validated experiment. Contract identity covers targets, inputs, evaluator version, split, limits and stopping rule. Compute its canonical digest with the same constructor (default fields are included):

```python
import json
from sage.execution.contracts import EvaluationContract
value = json.load(open('projects/contract.json'))
value['features'] = tuple(value['features'])
value['targets'] = tuple(value['targets'])
print(EvaluationContract(**value).sha256)
```

Then explicitly approve the reviewed digest and resource use:

```
python -m sage laboratory --mode live --allow-live --backend docker --allow-execution --contract projects/contract.json --approved-contract-digest REVIEWED_SHA256 --docker-image YOUR_PRELOADED_IMAGE@sha256:IMAGE_DIGEST --topic "Your scalar prediction proposal" --output projects/lab-docker
```

Live laboratory requires an explicit `--contract`, including dry-run; it never silently chooses the synthetic fixture contract. Live model configuration is unchanged from [runtime guide](sage-runtime.md). The public contract and candidate history go to the configured model; targets are excluded from prompts and Docker mounts. Targets remain in private local `contract.json`. Development scores are returned for bounded iteration, so this is not blind/final-test isolation. A digest is a consistency check, not a human identity or cryptographic approval signature.

The Docker adapter pins an existing local image, disables networking, uses read-only root and input/source mounts, drops capabilities, runs nonroot, sets no-new-privileges, bounds CPUs/memory/PIDs/tmpfs/output and enforces timeout/cleanup. Candidate output is only predictions; the trusted host evaluator validates length, numeric types and finiteness before computing MSE. No candidate-defined evaluator or printed score is accepted. Host Docker daemon access itself is privileged; container isolation must be independently reviewed for deployment.

## Bounded failures and evidence

Every generation slot creates an attempt before the model call. Failed calls count against shared Runtime requests; invalid commands and syntax/backend/evaluation failures count against the attempt budget. Consecutive repairs are capped, and the total attempts cannot exceed the frozen limit. Failures retain source (when generated), source digest and categorized errors. Reflection failures do not invalidate a measurement already obtained. All unsuccessful or worse-scoring candidates remain in the record. A zero development loss or exhausted attempts stops the loop without declaring scientific success.

Budget/parse/provider failures can stop report generation; prior proposal/execution artifacts remain. Runtime budgets are logical request/attempt/wall-clock limits, not currency guarantees. Backend implementations must enforce their own process/resource limits. Frozen dataclasses/hashes detect accidental drift, not hostile same-process Python mutation. The local audit is append-ordered, not tamper-proof storage.

## Unimplemented or unverified

- No upstream Agent Laboratory scientific result reproduced; no paid/live API calls in verification.
- No real Docker smoke test in this environment and no claim of audited containment.
- No arbitrary datasets/downloads, GPUs, package installs, full training infrastructure or final-test custodian.
- No automatic publication, LaTeX execution, acceptance-score optimization or independent scientific review.
- Model draft and reviewer opinions are unverified; deterministic rendering does not establish that supplied sources or measurements support a scientific claim.
- Original `sage run` remains proposal-only; `laboratory` is the explicit extension path.

Run `python scripts/check.py` for the full offline regression suite. Those tests verify software contracts and fixtures, not live services, real research or scientific validity.

## Explicit coverage, not upstream parity

This is a first mechanism-level integration. It does not reproduce the complete original Agent Laboratory application.

| Area | Coverage |
|---|---|
| CoI proposal chain / Semantic Scholar | Existing SAGE implementation retained; not replaced by Agent Laboratory search |
| MLESolver editing, repair, reflection, best-candidate selection | Adapted mechanisms implemented with bounded loops and fixed host metric |
| PaperSolver section writing / review / revision | Adapted mechanisms implemented; readable unverified `draft.md` and separate deterministic `report.md` |
| Frozen contract / Docker / safe fixture | New SAGE controls and adapters, not upstream security guarantees |
| arXiv search and automatic PDF/full-text retrieval | Not migrated; existing explicit local article support remains |
| Hugging Face dataset search/preparation | Not migrated; contract requires user-supplied bounded scalar development inputs |
| PhD / postdoc / professor / engineer multi-role dialogs | Phase responsibilities inform module boundaries, but original conversational multi-role agent machinery is not reproduced |
| MATH benchmark and upstream benchmark reproduction | Not migrated or run |
| LaTeX/PDF compilation and figure generation | Not migrated; output is Markdown/JSON, no generated LaTeX execution |
| Original Agent Laboratory model/provider catalog | Not migrated; SAGE's explicit configured providers are used |
| Publication, manuscript submission and public repositories | Not implemented or authorized by a run |
