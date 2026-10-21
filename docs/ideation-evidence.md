# Research ideation: scoped evidence, shared review and bounded retrieval

This owned SAGE implementation extends the CoI proposal chain and Agent Laboratory
discussion mechanisms. It does not import either upstream snapshot or establish
that research quality exceeds either original system. Source/attribution mappings:
[CoI](sage-migration.md), [Agent Laboratory](agent-laboratory-migration.md),
[discussion](coi-laboratory-discussion.md).

## Recommended first-stage entry

```bash
python -m sage run --mode live --allow-live --profile research --topic "YOUR RESEARCH QUESTION" --output projects/research-ideas
```

Credentials remain environment variables described in [runtime](sage-runtime.md).
The profile expands to four candidates/four roles, up to five papers per chain
(at least three), two discussion rounds, four distinct query aspects, semantic
ranking, evidence capsules, and up to two query relaxations. It permits at most
400 model requests, 160 retrieval requests, 4,000 output tokens per request,
1,600,000 reserved output tokens and 3,600 seconds. These are logical ceilings,
not a currency spending guarantee or a promise that all work will fit.
JSON `--config` overrides the profile; individual CLI limits override JSON.
`standard` keeps the existing small, legacy-compatible workflow. No larger paid
run is started merely by selecting a profile without `--allow-live`.

Offline default fixtures have only two source families; use two candidate/student
overrides for CLI offline smoke tests. The regression suite supplies four distinct
synthetic source families to exercise the full four-role/two-round research path.

## Evidence input: read, extract, then discuss

Since 2026-10-19, the research profile and native `sage autonomous` both use
source-span-bound `sage.evidence_capsule.v2` cards with claim-level semantic
screening. The downstream input is a bounded card rather than the raw paper or
only its abstract. Extraction reads supplied article sections or, in
`paper_text_mode=arxiv`, official arXiv HTML followed by optional PDF text fallback.
PDF support requires the optional dependency in `requirements-fulltext.txt`.
Only literal official arXiv identifiers/endpoints are accepted; no redirects,
arbitrary paper URLs, credentials, datasets, external code or scripts are followed.
Explicit use of the research profile opts into paper-text retrieval; this changes
the earlier metadata-only default for that profile. Existing standard behavior
and explicit `--articles` input remain available.

Each card includes source identity/scope, source digest, available and read chunk
counts, selected locators, partial-reading/truncation flags, missing categories,
and bounded source-attributed claims. Categories cover problem, motivation, method,
assumptions, data, metrics, results, baselines, limitations, reproducibility and
future work. Inferences are stored separately as unverified model interpretation.
Claims require an original passage ID matched against the actual read chunk;
the host copies its exact source text. Matching checks location. A separate,
budgeted semantic screen records `supported`, `unsupported` or `uncertain` with
reasons. Only supported claims populate the usable `claims`, `Evidence.idea` and
`Evidence.experiment` summaries. Other claims remain explicitly unverified with
their original passages and reasons. This same-family model assessment is not
independent verification or a guarantee of truth. Author-reported results are
never labeled independently reproduced results.

The reader bounds HTTP bodies at 10 MB, extracted text at 400,000 characters and
PDF extraction at 60 pages. Extraction reads up to eight 7,000-character chunks,
prioritizing abstract/introduction, method, experiment/result and limitation/discussion
headings, spreading remaining reads over the document, and retains at most 18 claims.
The research profile's card capacity is 240,000 characters to include semantic
audit metadata; native autonomous reading uses the same screen with up to 12 chunks
and 40 claims. This is selective reading, not guaranteed full-paper coverage.
Unavailable full text falls back to explicitly labeled abstract evidence; missing
methods, results and references remain missing. Formulas/tables in PDF text can
be incomplete. Raw parsed text stays in retrieval checkpoints, while capsules
reach chain ideation, discussion and experiment planning.
After finite retries, a chunk with invalid quotations contributes zero accepted
claims and remains in `failed_chunk_ids` plus the negative audit. Other validated
chunks can still form a card, with partial-reading flags. Zero source-bound claims
cannot form a card; if semantic screening supports none, it retains only the
explicitly unverified claims and the usable summaries state that evidence was
not established. Metadata does not repeat an abstract outside the read chunk,
preventing accidental cross-chunk quotation.

At the `Literature.extract` boundary, all downstream ideation, review, discussion
and experiment-planning consumers receive the same `capsule_view`: complete
supported/unverified claims and their individual verdicts, without the duplicate
`claims_before_entailment` and decision ledgers. The extraction event retains the
full original audit. The view is copied, so downstream processing cannot alter
that record. Identical paper content and topic reuse the screened card within
the same runtime rather than paying to extract and screen it again.

The explicit compatibility configuration `evidence_mode: capsule` alone still
defaults to `capsule_semantic_audit: false`, the original quote-matched v1 card
and 12,000-character capacity. It does not claim semantic screening occurred.
Use the research profile or explicitly enable `capsule_semantic_audit` with an
adequate capacity to select the newer path; `standard` defaults remain unchanged.
Discussion additionally projects each card to 2,000-4,500
characters, omitting inference prose and trailing claims with explicit omission
counts and a full-card digest. Every source remains visible/citable; complete
cards remain in the result ledger. This projection is not a claim of lossless
compression or exhaustive reading.

## Search, ranking and actual graph edges

With the research profile, configured embeddings are used if available. Otherwise
an explicit model semantic reranker scores at most 30 metadata records, returning
every supplied ID once. These are unverified model scores, not probabilities.
Omitted retrieval-pool counts are recorded. No embedding service is silently
provisioned and no absent embedding configuration is represented as present.

For arXiv queries, a zero-result novelty query may be relaxed to its first four
and then two essential terms. Original/relaxed queries and all calls remain in
the audit and budget; an empty search still means unknown. Problem, mechanism
and comparison aspects are requested as separate short queries. This bounded
fallback is not an exhaustive systematic literature search.

`SAGE_PAPER_PROVIDER=arxiv` uses topic/time chains only. Optional
`SAGE_PAPER_PROVIDER=arxiv_graph` combines arXiv discovery with actual Semantic
Scholar citation/reference edges (and its configured API key, if available).
ARXIV identifiers are resolved through the official graph endpoint; no similarity
edge is relabeled as a citation. `citation_policy=prefer` explicitly records graph
unavailability before rebuilding a separately labeled topic/time chain.
`required` stops on unavailable/insufficient graph evidence. Graph availability
still depends on the external API and rate limits; software fixtures do not prove
live graph service availability.

Novelty screening retains a structured closest-work comparison: shared problem,
shared mechanism, claimed difference, evidence limits and supplied source IDs.
The comparison corpus includes actually read input papers cited by the idea,
separately labeled from fresh search results; legitimate seed-paper IDs are not
misclassified as fabricated just because the latest search did not return them.
The profile additionally reads up to two comparison papers into capsules per
screening. The comparator distinguishes overlap, differences within retrieved
evidence, and insufficient evidence. None proves global novelty.

## Shared discussion v3

Initial students develop ideas from distinct seed chains. Review/revision then
uses a common evidence library, with source discovery ownership retained as
provenance rather than exclusive reading permission, including previously read
closest-work capsules. Reviewers see the target's
evidence and can cite any supplied shared card; invented IDs are still rejected.

`supported` critiques require source IDs. `methodological` critiques can propose
logical controls/falsification/feasibility improvements without inventing a paper
citation. `unknown` factual claims cannot be adopted as facts. Every incoming
critique gets an acceptance/rejection decision. Accepted changes are preserved
verbatim by the controller in an authoritative control block, carried across
rounds and bound into experiment planning. The model edits concise narrative;
it does not have to recopy long requirements. `UNCHANGED` is an explicit no-edit
sentinel, and synthesis returns exact accepted IDs with an empty requirements
array; the controller constructs requirement text from those approved IDs.
Revision may report current-round approvals or cumulative already-approved IDs;
only current incoming decisions are new. Unknown IDs/revocation are rejected.
The controller also retains the approved controls' source IDs independently of
the model's narrative citation list.
This never auto-accepts an opinion or promotes unknown facts. v1/v2 retain
their prior contracts for compatibility and controlled comparisons.

All roles may use the same model; they are not independent scientific reviewers.
More roles/rounds are not evidence of improved quality. The first-stage result is
still an unexecuted proposal. Missing experimental budgets/sample sizes remain
explicit. The downstream execution adapter remains scalar-only; this upgrade
does not implement arbitrary training, datasets or research experiments.

## Verification and limits

Run `python scripts/check.py`. Regressions exercise exact-excerpt rejection,
coverage/truncation, bounded relaxation/accounting, semantic-ID validation,
cross-role evidence access, methodological acceptance, real-edge normalization,
graph fallback labeling, the actual semantic `Literature.extract` branch,
screened-summary isolation, shared transport views, exact-input caching and the
four-role/two-round controller using synthetic inputs. Live smoke results must be
recorded separately under ignored `projects/`.
Scientific quality needs a same-topic/same-budget comparison and human evidence
review; a software pass or fluent idea is insufficient.


## ARIS / CORAL 增量接入

research 配置现默认 claim_review=true，在原证据卡上提取拟议主张并逐条进行有界最近工作比较；v3 讨论改动 idea 后使用同一路径重新筛查。配置、原版 ARIS 门控、评审收据与独立的 CORAL 任务执行入口见[实际接入说明](aris-coral-runtime.md)。此前的候选级 nearest-work 路径在 claim_review=false 时保留用于对照。
