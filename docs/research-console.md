# Research console

The console is part of SAGE, uses the existing autonomous runner and reads its
run directories. It has no database and does not edit scientific artifacts.
Single-owner deployment uses loopback HTTP plus an SSH tunnel. For an
authenticated group website with an HTTPS entry point, see [team deployment](team-console.md).

On AutoDL, in the same configured environment used for `sage autonomous`:

```bash
cd /root/autodl-tmp/Awesome-AutoResaerch
.venv/bin/python -m sage console --port 8765 --allow-live
```

Omit `--allow-live` for read-only viewing. The command prints an access URL with
a generated platform token (not the provider API key). For persistent service
deployments set a private `SAGE_CONSOLE_TOKEN` of at least 32 characters. Never
commit either credential. Model configuration remains in the server environment.

On your own computer:

```bash
ssh -N -L 8765:127.0.0.1:8765 -p SSH_PORT root@SSH_HOST
```

Open the printed `http://127.0.0.1:8765/#token=...` URL. The page removes the token
from the address bar and stores it in that browser tab's session storage. API
requests require the token and reject foreign origins/hostnames. The server
listens only on loopback. This is a single-owner console, not a public multi-user
service. Do not expose it directly to the internet.

Enter a topic and review finite budgets before starting. The UI requires explicit
live-call consent, launches the existing CLI, saves the real process exit code,
and refuses to start another active autonomous launcher. Scientific API keys are
never accepted by or transmitted to the browser. A browser disconnect does not
cancel the research. Current starts retain default 4 researchers, 2 discussion
rounds, 4 formal attempts, 640 research-tool attempts, and 7200 seconds; these
are not a currency or token-spend cap.

Views: full input; evidence cards and source spans; all initial candidates and
synthesis versions; peer reviews, audited advice and revisions; advisory reviews
and formal grading; safe tool events with correlation IDs and hashes; exact-byte
artifact downloads. The stage bar shows the latest observed stage, not a percent
complete. The event view is explicitly a recent 200-event tail. Complete logs
remain on disk. Missing, malformed or pending snapshots are not called success.
Team synthesis completion is distinct from completed formal grading/export.
History is ordered by the recorded start time, with unavailable times last.
The selected run is remembered within the browser tab. Switching runs or views
invalidates outstanding requests and clears the previous content immediately.
An older result that reports completion without a matching, explicitly completed
grade is labeled "历史运行报告完成 / 未独立核验". This label does not alter its files;
even a matching complete grade does not establish independent scientific acceptance.

This entry point produces conjectures and experiment protocols. It does not
implement the general experiment-to-paper bridge. Same-family model reviews are
advisory and do not establish independent scientific acceptance.

## Review integrity update

Scientific projection v2 preserves candidate `calibration_plan` and the typed
`shared_scientific_context` fields `novelty_operationalization`,
`computational_envelope`, `evidence_policy`, `verification_boundary`, plus existing
scientific protocol fields. Unknown containers remain omitted and are reported.
Author scores do not cross the blind-review boundary.

Novelty feedback v2 sends a compact evidence overview plus each available
original passage exactly once. Selectable source references carry paper-bound
handles, so identical local span IDs cannot be rebound across papers. Original
quotes are still resolved by the manager; source integrity is not entailment.
Legacy reference pairs remain readable for archived runs.

The `preflight` research tool uses the same deterministic checks as formal
grading and exposes omissions before submission, without model calls or formal
attempt consumption. It does not bypass the final exact-byte grader check or
weaken the two-advisory-lineage/current-version requirements. Invalid scientific
claims and incomplete evidence remain visible; no historical output is rewritten.

## Optional research planning interview

The new-research screen offers an optional **live model interview** before the
final Topic and research budget form. The configured provider receives the Topic
and full question/answer history on each explicit next click. It generates one
context-sensitive question, its reason, zero to four relevant options, and a brief
interpretation of the current direction. There is no authored question/option bank.
Users can answer freely, choose an option, skip, revise a previous answer, or finish
at any time. Changing an earlier answer regenerates dependent questions; a changed
Topic resets the conversation. Empty topics can be explored, or users can bypass
all model calls and start free exploration directly.

Clicking “开始模型追问” explicitly opts into transmitting the Topic and subsequent
answers to the configured model and paying for those calls. This does not launch
research. The final editable Topic preserves the exact user answers; the model's
interpretation is shown separately and is not silently promoted into user decisions.
The existing consent and budget form remains the only research start action.

`POST /api/planning/next` uses the existing member session, pinned origin and CSRF
checks (or the local console bearer token). The shared `sage/planning.py` controller
uses `OpenAIModel`, validates inputs and generated JSON, closes its client, and has
no research tool or launch capability. Each request has one attempt, up to 2000
output tokens and an 85-second outer timeout. Each interview permits 12 questions;
per gateway process there are at most 30 attempts/account/hour, 120 total/hour and
two simultaneous requests, with only one per account. Failures consume the budget;
there are no automatic retries or fallback scripted questions. Request IDs dedupe
completed requests for one hour (bounded 128-entry cache); in-flight duplicates
are rejected without another model call. These are process-local limits, reset on
service restart, not a persistent currency cap. Token usage is recorded separately
from research launches. Provider errors are sanitized and answers remain editable.

A versioned draft remains in the tab's sessionStorage and can be downloaded as
`research-plan.json`. Refresh never automatically sends a paid call; an interrupted
request can be explicitly resumed using the same request ID. Finishing while a call
is pending ignores the late reply, although the already-issued request may still
be billed. Successful research launch or team logout clears the local draft.
Old drafts preserve seed and manually edited final Topic but do not reuse scripted
question branches. Downloaded drafts can contain unpublished ideas.

Interaction inspiration: [RobMitt/grill-me-skill](https://github.com/RobMitt/grill-me-skill),
reviewed on 2026-10-23. SAGE adapts sequential questioning, concrete choices and
decision summaries into an optional research-specific flow. The interview prompt and
implementation are original; the upstream skill is neither installed nor executed.
Unlike an exhaustive interview, all decisions can remain explicitly unresolved.

Candidate results use the available width when only one is present; the selected
candidate view uses full-width cards. Account styles are scoped to account pages,
and consent checkboxes have intrinsic width with adjacent labels. These changes
do not alter scientific artifacts or strengthen completion/acceptance claims.

## Structured proposal and evidence reading

The default research view presents each selected candidate as a proposal: motivation
and gap; hypothesis and proposed contribution; algorithm/implementation; main
experiment and endpoints; baselines and ablations; analysis and falsification;
resources, risks and boundaries; sources. A short opening-sentence overview and
chapter links help readers follow the story. Original fields, unknown future fields,
shared definitions and full protocol remain accessible. Missing sections are marked
as missing, never completed with invented results. Primary/secondary endpoint roles
remain the roles recorded in the protocol. A Markdown reading export includes all
mapped fields and the shared context; original scientific downloads are unchanged.

Evidence cards group actual claims by problem, motivation, method, data, baselines,
metrics, reported results, assumptions, limitations and reproducibility. Every claim
keeps its model support verdict and expandable exact source spans. Unsupported and
uncertain claims remain visible. Search includes evidence-card content. This is a
reading projection, not an independent verification or experimental replication.

An optional privately stored `presentation/proposal-reading.json` in a run may provide
an editorial Chinese reading aid with schema `sage.proposal-reading.v1`, the exact
`primary_sha256` of `conjectures.json`, and `candidates` keyed by candidate ID. Each
item has `sections` keyed by `motivation`, `hypothesis`, `method`, `experiment`,
`baselines`, `decisions`, `feasibility`, or `sources`; each section has `text` and
`source_fields` listing existing candidate fields. The API suppresses stale hashes
and invalid references. These references establish provenance, not semantic truth;
editorial text still requires human review. Such a reading aid only accompanies the
matching final export, never another historical synthesis. It is visibly labelled,
retains full originals beneath each section, and cannot change grades or research
artifacts. There is no automatic paid summarization request.

Readable prose resolves each candidate's variable/endpoint references to its own
protocol definitions (for example, a variable's full metric name). Versions, URL
paths and source handles are not rewritten. An optional `term_names` map in that
candidate's private reading aid may translate these names; the API only accepts
IDs present in that candidate's variables/endpoints. Ambiguous duplicate IDs are
not silently assigned a meaning. All substitutions affect display copies only.
The main view hides protocol codes in expandable originals and a code/name glossary.
The default Markdown export contains readable prose; a separate full export appends
the original protocol with its exact identifiers and fields for scientific review.
