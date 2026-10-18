# Native research team protocol

This section governs the multi-researcher mode and takes precedence over the
single-researcher allocation and submission instructions above. It does not replace
the ARIS methods, paper-reading requirements, evidence policy or candidate schema.
The manager assigns each researcher a separate native agent, persisted DSH session,
Git worktree and authenticated team slot. Do not impersonate another slot or edit
another researcher's files. These researchers may use the same model API; describe
them as separate research contexts, never independent model families or experts.

## Start with the actual team state

Call `mcp__sage_research__team` with `{"action":"status"}` first and after any
phase transition. Use the returned role, slot, round and required action rather
than guessing teammate identities or the current round. Your slot comes from the
runtime, not a field you can supply to a tool. Work independently in your own wiki
and files; the shared evidence service gives everyone the same authenticated
paper identities, extraction scopes and source passages.

The team as a whole must retrieve at least 12 relevant papers and read at least
6 central papers, and produce 8–12 distinct candidates. The initial per-researcher
minimum is `ceil(8 / team_size)` candidates: four researchers normally contribute
2–3 each; three contribute 3–4 each; two contribute 4–6 each. This replaces the
instruction for every individual to generate 8–12. Follow the same complete
candidate schema, including actual sources, closest work and falsification plans.
Keep your own research decisions and negative evidence in your wiki. Choose a
complementary mechanism or question, not superficial variants of a teammate's
idea. Do not assert that a shared card proves you personally read the full paper.

## Independent proposal, peer challenge and revision

1. Search, read, compare and develop your assigned research perspective. Use
   `evidence` and targeted `passages` when useful. Write a JSON file in your own
   worktree with `candidates`, `selected_ids` and `selection_rationale`, following
   the primary candidate schema. Local candidate IDs identify your own proposal;
   final synthesis will preserve their origin explicitly.
2. Freeze your initial proposal with
   `team(action="propose", artifact_path="/absolute/path/to/proposal.json")`.
   The manager copies and hashes it. Other initial proposals become visible only
   after all researchers have submitted; do not bypass that barrier by reading
   peer worktrees or their native conversation files.
3. When status assigns a peer review, read the returned frozen proposal and its
   exact `proposal_sha256`. Examine methods, novelty, counterexamples, assumptions,
   evaluation, resource feasibility and reproducibility through your assigned
   perspective. Do real supporting or contradictory retrieval when needed. Submit
   `team(action="review", round=STATUS_ROUND, target_slot=...,
   proposal_sha256="...", issues=[...])`. Pass the exact round from current status;
   an older receipt or delayed request must not be applied to a later round.
   Each issue is `{"id":"...","candidate_id":"...","kind":"factual" or
   "methodological","problem":"...","repair":"...","source_ids":[...]}`.
   Factual objections must cite actually retrieved papers; methodological concerns
   may be logical objections with explicit reasons rather than invented citations.
   Focus on consequential problems; do not fabricate an objection to fill a quota.
   The tool receipt, rather than your own prose, records what was submitted.
4. Once all reviews for the round are frozen, read the objections to your proposal.
   Revise it in your own worktree. Submit
   `team(action="revise", round=STATUS_ROUND,
   artifact_path="/absolute/path/to/revised.json",
   decisions=[...])`. For every received issue provide
   `{"issue_id":"...","decision":"accepted" or "rejected" or "uncertain",
   "reason":"...","source_ids":[...],"change":"..."}`. State the precise
   change for acceptance, evidence or logic for rejection, and remaining missing
   evidence for uncertainty. Rejecting or retaining uncertainty is allowed; silent
   omission and unsupported agreement are not. Re-search mechanisms and nearest
   work after substantive revisions. Preserve rejected candidates and reasons.
5. Repeat the assigned peer-review/revision cycle for the configured rounds. The
   manager selects the peer and exposes same-round frozen snapshots, so reviews
   cannot silently switch to a moving proposal. Never submit another researcher's
   revision or claim a review was addressed without the matching decision record.

If a barrier is waiting, first use the time for relevant source checks, your own
notes or additional counterevidence. Otherwise wait 20–30 seconds with native
shell before checking status again. Do not hammer the service or spend calls
repeating an unchanged status. Do not exit merely because your current phase is
waiting; the manager controls the overall time limit and shutdown.

## Synthesis and formal submission

Only authenticated slot 0 synthesizes and invokes `coral eval`. After the final
round's revisions are complete, inspect every final frozen proposal and decision
record. Build the common `conjectures.json` in slot 0's worktree, retaining every
originating candidate, including rejected ones. Each candidate additionally needs
`"origin":{"slot":...,"candidate_id":"...","proposal_sha256":"..."}`
from its final frozen proposal. Use unique final IDs and record selection and
rejection reasons. Merge or reject redundant claims explicitly while preserving
their source candidates; do not discard inconvenient proposals or open objections.

Write the Chinese `CONJECTURES.md` and reconcile it with that exact JSON. Preserve
the original workflow's at least two fresh-context advisory critique/revision
cycles, targeted novelty/counterevidence checks and substantive repairs. Team peer
reviews supplement these critiques. They are not additional CORAL formal grades.
Register the current final file with
`team(action="synthesize", artifact_path="/absolute/path/to/conjectures.json")`.
This binds synthesis to the exact file SHA and completed team history. Register
again after any later file change, including advisory or formal review repairs,
before the next `coral eval -m "..."`. A past synthesis receipt does not authorize
grading a changed file. The grader also checks provenance and candidate contracts.

Other slots remain available for source checks and notes while slot 0 handles
the shared report and grading feedback. Do not make competing formal submissions.
In your WORKFLOW_TRACE.md cite your own proposal, review and revision receipts,
actual source work and native slot. Report uncompleted rounds or missing peers as
incomplete. Do not turn collaboration, source binding or a high model score into
experimental validation or ARIS cross-family independent acceptance.
