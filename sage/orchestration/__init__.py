# Derived from the CoI-Agent main.py/DeepResearchAgent pipeline, Apache-2.0.
# MODIFIED for SAGE 2026-10-17: owned modules, typed results, bounded failure ledger.
# Source and modification map: NOTICE.md and docs/sage-migration.md.
"""The same controller runs with fixture or live adapters; no vendor imports."""
from __future__ import annotations
from ..config import RunConfig
from ..errors import SageError, NoEvidence
from ..runtime import Runtime
from ..types import RunResult
from ..discovery import Discovery
from ..literature import Literature
from ..ideation import Ideation
from ..review import Review
from ..review.evaluator import audit_result
from ..experiment_design import ExperimentDesign


async def run(topic, main_model, source, *, cheap_model=None, config=None, mode='offline', articles=None):
    if not isinstance(topic, str) or not topic.strip():
        raise ValueError('Topic must be a nonempty string')
    if mode not in ('offline', 'live'):
        raise ValueError('Mode must be offline or live')
    config = config or RunConfig()
    runtime = Runtime(main_model, cheap_model or main_model, source, config)
    discovery = Discovery(runtime, articles=articles)
    literature = Literature(runtime, discovery)
    review = Review(runtime, discovery)
    ideation = Ideation(runtime, review)
    design = ExperimentDesign(runtime, discovery, review)
    result = RunResult(topic=topic.strip(), mode=mode)
    try:
        anchors = await discovery.anchors(topic)
        if not anchors:
            raise NoEvidence('No anchor papers found within the search budget')
        for anchor in anchors:
            try:
                chain = await literature.build_chain(anchor, topic)
                result.candidates.append(await ideation.generate(chain, topic))
            except NoEvidence as error:
                result.errors.append({'code': error.code, 'message': str(error)})
                runtime.event('orchestration.candidate', 'skipped_insufficient_evidence', anchor_id=anchor.paper_id, anchor_url=anchor.url)
        if not result.candidates:
            raise NoEvidence('No candidate met the minimum literature-chain requirement')
        result.ranking = await review.rank(result.candidates, topic)
        result.selected_index = result.ranking['selected_index']
        selected = result.candidates[result.selected_index]
        result.experiment = await design.generate(selected, topic)
        result.status = 'completed' if all(c.novelty.status == 'no_similar_work_found' for c in result.candidates) else 'completed_with_uncertainty'
        runtime.event('orchestration.run', result.status, artifact_type='unexecuted_research_proposal')
    except SageError as error:
        result.status = 'stopped' if error.code in ('budget_exceeded', 'no_evidence') else 'failed'
        # Messages here originate from our own categorized errors, never provider bodies.
        result.errors.append({'code': error.code, 'message': str(error)})
        result.experiment = getattr(design, 'current_plan', result.experiment)
        runtime.event('orchestration.run', result.status, error_code=error.code)
    result.audit = runtime.audit
    result.usage = dict(runtime.usage)
    result.usage['elapsed_seconds'] = round(runtime.clock() - runtime.started, 6)
    result.validation = audit_result(result, config)
    if not result.validation['contract_passed']:
        result.status = 'failed'
        result.errors.append({'code': 'contract_audit_failed', 'message': 'Deterministic output consistency audit failed'})
    return result
