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

The new-research screen offers a local, optional conversation before the final
Topic and budget form. Start from a rough direction, write a Topic directly, or
leave the direction blank and choose free exploration. The guided route asks one
question at a time, with four concrete options and a free-text field; a custom
answer needs no selected option. Questions cover contribution type, focus,
materials, resources, falsification/evaluation, and scope. The focus and validation
branches differ for mechanism, method, evaluation and open exploration goals.

Users can go back, skip any question, or finish early. Changing the contribution
type clears dependent focus/validation answers; independent decisions survive.
Unanswered questions remain open, and named materials are not represented as
already read. The assembled Topic is editable, preserves the user's stated
preferences and uncertainties, and is passed unchanged through the existing
RunStore to the autonomous controller. It is visible in that run's original
input. Nothing starts until the user confirms live-call consent and submits the
budget form. The experimental-resource question does not change the live idea
generation budget.

This interview uses authored question branches, not a model interviewer. It
makes no API calls. A versioned draft is stored in the current tab's sessionStorage
and can be downloaded as `research-plan.json`. Refresh preserves answers and
manual Topic edits; a successful launch or team logout clears the local draft.
Downloaded drafts can contain unpublished ideas and should be shared deliberately.

Interaction inspiration: [RobMitt/grill-me-skill](https://github.com/RobMitt/grill-me-skill),
reviewed on 2026-10-23. SAGE adapts sequential questioning, concrete choices and
decision summaries into an optional research-specific flow. Question text and
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
