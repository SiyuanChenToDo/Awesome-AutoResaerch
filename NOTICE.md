# SAGE third-party attribution and modifications

SAGE (Scientific Agent for Grounded Exploration) includes code and prompt templates derived from **CoI-Agent**, by Li et al., licensed under Apache License 2.0. Source: https://github.com/DAMO-NLP-SG/CoI-Agent, pinned commit ac94317ff2d1997f362747edc2c9e5f0fdc9c450. The upstream README contains the full citation; its original LICENSE and all imported bytes remain in third_party/coi_agent/upstream/. That commit did not include a separate NOTICE file.

The applicable Apache-2.0 license is also provided at LICENSES/CoI-Agent-Apache-2.0.txt, so the maintained runtime has no dependency on the historical snapshot. This notice does not imply upstream endorsement.

Modified for SAGE on 2026-10-17: agents.py was decomposed into discovery, literature, ideation, experiment_design, review and orchestration implementations. LLM.py and searcher/sementic_search.py informed the injectable live adapters. Prompt functions were moved into the corresponding owned modules with explicit evidence-scope rules, relevance output, concise rationale requests and mutable-default fixes. Tuple-based exchange was replaced with named data contracts; retrieval, novelty and refinement loops have finite budgets; failures and insufficient evidence are explicit; secrets are excluded from audit records. External PDFs are not automatically fetched or parsed, and local article JSON or abstract-only metadata is clearly labeled. Offline fixtures are synthetic and cannot establish scientific validity.

SAGE-specific contracts, orchestration safety controls, tests and command routing are maintained in this repository. Original catalog records, third-party names, paper titles, model identifiers and immutable sources are not renamed. See docs/sage-migration.md for the detailed method map and capability boundaries.

## Agent Laboratory

SAGE also includes maintained code and prompt adaptations from **Agent Laboratory**, copyright (c) 2025 Samuel Schmidgall, MIT license. Source: https://github.com/SamuelSchmidgall/AgentLaboratory at `d9017d90e329112d2a80b7712f37ee9094d2cd27`. Selected immutable originals and original MIT license are under `third_party/agent_laboratory/upstream`; applicable license also at `LICENSES/Agent-Laboratory-MIT.txt`.

Modified for SAGE on 2026-10-17: MLESolver REPLACE/EDIT, generation, error repair, reflection and best-candidate mechanisms are decomposed into execution modules. PaperSolver scaffold/section writing and report review are decomposed into writing/review modules. Unbounded loops, host execution, LLM experiment reward, LaTeX compilation, auto-installation and publication are intentionally excluded. A frozen host evaluator measures candidate predictions; a separately opted-in Docker adapter supplies execution, while offline fixtures and syntax-only dry runs remain explicitly labeled. The original section-tip table's AI-Scientist inline credit is retained in the snapshot; maintained tips are newly written. See `docs/agent-laboratory-migration.md` for exact function mapping and unverified boundaries. No upstream endorsement is implied.

## CoI / Agent Laboratory hybrid discussion

Added 2026-10-17: sage/discussion combines the CoI source-scoped chain-to-idea mechanism (Apache-2.0 lineage above) with Agent Laboratory PhD/Postdoc discussion and planning concepts (MIT lineage above). Maintained prompts and code use bounded JSON role exchanges, explicit citation ownership, immutable original snapshots, canonical accepted-control handoffs, and fixed prompt-version hashes. No upstream snapshot is modified or imported. These changes do not establish original behavior parity or scientific superiority.
