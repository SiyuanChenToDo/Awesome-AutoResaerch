# Full manuscripts

`sage write-paper` produces an actual manuscript rather than a short evidence-ledger report. It composes twelve sections (including a conclusion and reproducibility appendix) as one coherent document, develops materially incomplete drafts, reviews the whole document from three perspectives, and revises it as a whole. This avoids turning each section into a repetitive standalone paper. An explicit `drafting_mode: sections` evidence setting retains the separate-section workflow when needed. Markdown, LaTeX, a bibliography and the structured review/revision history are emitted together. Supplied measured tables and figures are assembled without model-generated numerical tables.

The former adaptation limited each section to one paragraph, 160 words and 1400 characters. Those editorial caps have been removed. Agent Laboratory's original PaperSolver targeted approximately eight pages / 4000 words, with multi-paragraph sections, equations, figures, tables, compilation and whole-paper editing. The new owned controller restores comprehensive drafting without importing the immutable upstream snapshot. It uses a 4000-word main-text completeness diagnostic rather than a content maximum; short output is marked underdeveloped, never silently called a full paper. This diagnostic does not establish scientific quality.

```sh
python -m sage write-paper \
  --input-run projects/completed-study \
  --evidence projects/manuscript-input/evidence.json \
  --output projects/full-paper \
  --allow-live
```

The evidence JSON has schema `sage.manuscript_evidence.v1`: a title, the verified parent lineage, an evidence dictionary, reference records, and optional data-derived assets. `evidence.original_analysis` must equal the recomputed parent analysis. Each reference needs a unique `key`, `title`, `url`, actual verified `bibtex`, `reading_scope` and grounded `notes`. Source metadata alone does not support detailed method claims. Citations use `[@key]` or `[@one; @two]`; unknown keys and unsupported evidence identifiers are rejected. Only safe mathematical TeX is accepted from the model. Asset paths must stay within the explicitly supplied evidence directory.

Optional `assets` maps section IDs to file records. A `.tex` record contains `path` and should be a trusted data-derived table. PDF/PNG figures additionally contain `caption` and `label`. The model does not create bibliographic records, execute commands, choose measurements or alter evaluators.

Use `--config` for finite model-request, transport, timeout and revision budgets. These are operational safeguards against runaway requests, not manuscript word limits. The default request envelope allows 32768 output tokens per call; this transport envelope is not an editorial word ceiling. `--resume prior/checkpoint.json` writes into a new output directory and reuses exact-input successful calls while preserving consumed budgets. `--retry-uncertain` explicitly permits retrying an interrupted in-flight request. Different code, evidence, provider configuration or run limits cannot reuse the checkpoint.

Compile `main.tex` using a local LaTeX engine or the Codex LaTeX editor, then inspect the resulting pages. The supplied generic article layout is a full working manuscript layout, not a claim of compliance with an unspecified venue. An author chooses the venue before final formatting and submission.

`sage write-report` remains the evidence-ledger compatibility view. Its deterministic evidence record is useful alongside the manuscript. Its prose and model-review ratings are not scientific certification. The closed-loop runner still emits this compatibility view; complete manuscript authoring is an explicit continuation with a checked bibliography and research assets, rather than automatically inventing missing references after an experiment.

The supplementary CPU experiment `python -m sage.execution.sr_controls --output NEW_DIRECTORY --workers 20` writes its new protocol before running 24 new seed clusters. It evaluates numerical calibration and a probability-yoked random-rejection control, including actual matching failures. This is an owned analytic-function experiment, not a reproduction of DEAP/PTC2/LM, PySR, Operon or the original LSH paper. No upstream performance or successful control matching is assumed.

Publication readiness requires scientific evidence, not just more text. A known method cannot become novel through a writing prompt; adding a gate is already present in the cited inexact-simplification algorithm. Uncertain effects, failed matching and missing external baselines must remain visible. Automated perspectives can share the same model family and are not independent expert reviews. No part of this command submits or publishes a manuscript.
