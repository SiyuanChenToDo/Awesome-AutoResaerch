# MIT License
#
# Copyright (c) 2025 Samuel Schmidgall
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

"""Evidence-scoped PaperSolver adaptation; no upstream imports or LaTeX execution.

Derived mechanisms: PaperSolver.gen_initial_report (validated scaffold and separate
section calls), PaperSolver.solve/process_command (reviewed edits and best-draft
retention). MODIFIED 2026-10-17: structured data, bounded Runtime calls, immutable
observations, supplied-source bibliography, and a deterministic Markdown renderer.
The raw model draft is quarantined from factual Markdown rather than using a
number/citation regex as an unreliable scientific fact checker.
"""
from __future__ import annotations
from copy import deepcopy
import html
import json
import math
import re
from typing import Protocol

from ..errors import BudgetExceeded, InvalidResponse, SageError, ValidationError
from ..review.report import review_report
from .prompts import SECTIONS, TITLES, scaffold_prompt, section_prompt, revision_prompt, MAX_COMMENTARY_CHARS


class EvidenceWriter(Protocol):
    async def draft(self, *, reviewed_claims: list[dict], evidence: list[dict]) -> str: ...


def supplied_references(proposal):
    """Only actual evidence paper records; generated reference-title strings aren't sources."""
    evidence = list(proposal.get('evidence', [])) if isinstance(proposal.get('evidence'), list) else []
    for candidate in proposal.get('candidates', []):
        if not isinstance(candidate, dict):
            continue
        chain = candidate.get('chain', {})
        if isinstance(chain, dict) and isinstance(chain.get('evidence'), list):
            evidence.extend(chain['evidence'])
    sources = {}
    for item in evidence:
        if not isinstance(item, dict):
            continue
        paper = item.get('paper', item)
        if not isinstance(paper, dict):
            continue
        identity, title = paper.get('paper_id'), paper.get('title')
        if not isinstance(identity, str) or not identity.strip() or not isinstance(title, str) or not title.strip():
            continue
        if identity in sources:
            continue
        sources[identity] = {'paper_id': identity, 'title': title,
                             'url': paper.get('url') if isinstance(paper.get('url'), str) else '',
                             'evidence_scope': paper.get('evidence_scope') if isinstance(paper.get('evidence_scope'), str) else 'unspecified',
                             'basis': 'supplied_proposal_evidence_not_independently_verified'}
    return list(sources.values())


def parse_json(value, label):
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        raise InvalidResponse(f'{label} must be JSON') from None


def parse_section(value, reference_ids):
    section = parse_json(value, 'Report section') if isinstance(value, str) else value
    if not isinstance(section, dict) or set(section) != {'commentary', 'citation_ids'}:
        raise InvalidResponse('Report section has unexpected fields')
    if not isinstance(section['commentary'], str) or not section['commentary'].strip():
        raise InvalidResponse('Report commentary is missing')
    if len(section['commentary']) > MAX_COMMENTARY_CHARS:
        raise ValidationError('bounded_commentary', 'commentary')
    # Narrow form check for the concrete failure observed in a real revision.
    # This does not certify prose quality, entailment, or numerical truth.
    if re.match(r'(?is)^\s*(?:clarify|reframe|correct|rewrite|revise|align|rename)\s+(?:the\s+)?(?:abstract|manuscript|draft|section|description|results|setup)\b|^\s*separate\s+the\s+(?:pre-registered\s+)?(?:design\s+)?proposal\s+from\b|^\s*clarify\s+the\s+executed-vs-proposed\s+split\b',section['commentary']):
        raise ValidationError('manuscript_prose','commentary')
    citations = section['citation_ids']
    if not isinstance(citations, list) or len(citations) > len(reference_ids) or any(not isinstance(x, str) or x not in reference_ids for x in citations):
        raise InvalidResponse('Report cites an unsupported source')
    return {'commentary': section['commentary'], 'citation_ids': list(dict.fromkeys(citations)),
            'claim_status': 'unverified_model_commentary', 'rendered_in_markdown': False,
            'status': 'drafted'}


def parse_edits(value, reference_ids):
    edits = parse_json(value, 'Report edits')
    if not isinstance(edits, list) or len(edits) > len(SECTIONS):
        raise InvalidResponse('Report edits must be a bounded array')
    result, seen = [], set()
    for edit in edits:
        if not isinstance(edit, dict) or set(edit) != {'section_id', 'commentary', 'citation_ids'}:
            raise InvalidResponse('Report edit has unexpected fields')
        identity = edit['section_id']
        if not isinstance(identity, str) or identity not in SECTIONS or identity in seen:
            raise InvalidResponse('Report edit targets an invalid or repeated section')
        seen.add(identity)
        body = parse_section({k: edit[k] for k in ('commentary', 'citation_ids')}, reference_ids)
        result.append({'section_id': identity, **body})
    return result


def recorded_observations(execution):
    """Extract scalar logged values without statistical inference or model involvement."""
    dry_run = execution.get('status') in ('dry_run', 'dry-run', 'not_run')
    warnings, attempts = [], []
    for index, attempt in enumerate(execution.get('attempts', [])):
        if not isinstance(attempt, dict):
            warnings.append({'code': 'invalid_attempt_record', 'attempt_index': index})
            continue
        metrics = {}
        supplied = attempt.get('metrics')
        if dry_run and supplied:
            warnings.append({'code': 'dry_run_metrics_ignored', 'attempt_index': index})
        elif supplied is not None:
            if not isinstance(supplied, dict):
                warnings.append({'code': 'invalid_metrics_ignored', 'attempt_index': index})
            else:
                for key, value in supplied.items():
                    if isinstance(key, str) and key.strip() and type(value) in (int, float) and math.isfinite(value):
                        metrics[key] = value
                    else:
                        warnings.append({'code': 'invalid_metric_ignored', 'attempt_index': index})
        identity = attempt.get('attempt_id', f'attempt-{index + 1}')
        if not isinstance(identity, (str, int)) or isinstance(identity, bool):
            identity = f'attempt-{index + 1}'
        error = attempt.get('error')
        # Raw process error text is retained by execution, never promoted to report facts.
        attempts.append({'attempt_id': identity, 'status': attempt.get('status', 'unknown'),
                         'metrics': metrics,
                         'selected': identity == execution.get('selected_attempt_id'),
                         'code_sha256': attempt.get('code_sha256'),
                         'error_present': bool(error)})
    return attempts, warnings, dry_run


def _text(value):
    if not isinstance(value, (str, int, float)) or isinstance(value, bool):
        return 'unavailable'
    text = ' '.join(str(value).split())
    text = html.escape(text, quote=True)
    return re.sub(r'([\\`*_{}\[\]()#!|])', r'\\\1', text)


def render_markdown(report):
    """Never interpolate model prose, model ratings, or model-created references."""
    attempts = report['observations']
    lines = ['# Research Report: Evidence-scoped execution record', '',
             'Scientific validation: not_performed.',
             'This report is a software-generated evidence view, not a validated manuscript.', '']
    if report['dry_run']:
        lines += ['DRY RUN: candidate code was not executed; no experimental measurements are reported.', '']
    elif report['fixture']:
        lines += ['SYNTHETIC FIXTURE: all recorded metrics below are synthetic software-test data, not scientific findings.', '']
    else:
        lines += ['Recorded execution data below has not been independently scientifically validated.', '']
    if report['proposal_fixture']:
        lines += ['The supplied proposal uses synthetic offline fixture evidence.', '']
    lines += ['## Abstract', '',
              'This record links an execution ledger to supplied proposal evidence. '
              'No causal, significance, novelty or generalization claim is established.', '',
              '## Introduction', '',
              'The research proposal remains a proposal. Executing candidate code does not establish its hypothesis.', '',
              '## Background', '',
              'Source reading scope is recorded in the bibliography. Missing literature or experimental details remain unknown.', '',
              '## Related Work', '',
              'Only sources supplied as proposal evidence are listed below. Their inclusion is not independent verification.', '',
              '## Methods', '',
              'Candidate implementations and raw errors remain in the execution artifact. '
              'All recorded attempts, including failures, are retained in this view.', '',
              '## Experimental Setup', '']
    contract = report['contract']
    for name in ('protocol_id', 'dataset_id', 'split', 'metric', 'evaluator_version'):
        if name in contract:
            lines.append(f'- {_text(name)}: {_text(contract[name])}')
    lines += [f'- Contract digest: {_text(report.get("contract_digest"))}',
              'The contract is supplied execution metadata; a digest is not proof of approval or evaluator independence.', '',
              '## Results', '']
    if not attempts:
        lines.append('No execution attempts or measured results were supplied.')
    for attempt in attempts:
        label = ' (selected in execution ledger)' if attempt['selected'] else ''
        lines.append(f'- Attempt {_text(attempt["attempt_id"])}: {_text(attempt["status"])}{label}')
        if attempt['metrics']:
            for metric, value in sorted(attempt['metrics'].items()):
                lines.append(f'  - Recorded {_text(metric)}: {json.dumps(value, allow_nan=False)}')
        else:
            lines.append('  - No measured metrics recorded.')
        if attempt['error_present']:
            lines.append('  - Failure/error retained in the execution artifact.')
        if attempt['code_sha256']:
            lines.append(f'  - Candidate digest: {_text(attempt["code_sha256"])}')
    lines += ['', '## Discussion', '',
              'Development selection can be optimistic. Independent confirmation, repeated trials, '
              'uncertainty estimation and wider applicability are not established by this report.', '',
              '## Model Draft and Review', '',
              'UNVERIFIED MODEL COMMENTARY: generated section prose, critique and revision history '
              'are retained in the structured report for human review. None is rendered here as '
              'evidence, numerical experiment facts or verified references. Model review is not independent scientific validation.', '',
              '## Supplied References', '']
    for reference in report['references']:
        lines.append(f'- {_text(reference["paper_id"])}: {_text(reference["title"])}. '
                     f'Reading scope: {_text(reference["evidence_scope"])}.')
        if reference['url']:
            # Plain escaped source metadata, not a model-generated or executable link.
            lines.append(f'  Source identifier: {_text(reference["url"])}')
    if not report['references']:
        lines.append('No supplied proposal references; literature support remains unavailable.')
    analysis=report.get('research_analysis')
    if isinstance(analysis,dict) and analysis.get('schema_version')=='sage.sr_analysis.v1':
        lines += ['', '## Bounded heldout experiment', '',
                  'Owned analytic functions and an owned LSH proxy; this is not a reproduction of the cited implementations.',
                  'Numbers below are recomputed from the frozen confirmation ledger. Seed intervals do not cover arbitrary new tasks.', '',
                  '| Arm | Mean test R2 | Mean OOD R2 | Mean nodes | Accepted | Heldout semantic violations |',
                  '|---|---:|---:|---:|---:|---:|']
        for arm,row in analysis['summaries'].items():
            lines.append(f'| {_text(arm)} | {row["test_r2"]:.6f} | {row["ood_r2"]:.6f} | {row["final_size"]:.3f} | {row["accepted"]} | {row["heldout_semantic_violations"]} |')
        lines += ['', 'Primary hypothesis status: '+_text(analysis['primary_claim_status'])+'.', '',
                  '| Probe verified minus control | Mean test R2 difference | Seed bootstrap 95% interval | Holm p |',
                  '|---|---:|---|---:|']
        for row in analysis['contrasts']:
            lines.append(f'| {_text(row["control"])} | {row["mean_delta_test_r2"]:.6f} | [{row["ci95"][0]:.6f}, {row["ci95"][1]:.6f}] | {row["holm_p"]:.6f} |')
        lines += ['', 'Complexity matching criteria all met: '+str(analysis['all_complexity_matches_met'])+'.',
                  'The fixed penalty ladder does not guarantee a matched-complexity comparison. See analysis.json for per-function distances.',
                  'Extra hashing/probe cost is recorded; equal fitness-call counts do not imply equal total compute.',
                  'Independent scientific replication: not performed.']
    if report['errors'] or report['evidence_warnings']:
        lines += ['', 'Some writing or input checks did not complete cleanly; consult the structured error and evidence-warning records.']
    return '\n'.join(lines) + '\n'


def render_draft_markdown(report):
    """A separate, explicitly unverified prose artifact, never the evidence report.

    Model prose can contain unsupported claims or inline references even when its
    structured citation IDs pass validation. Escape markup and state that limit;
    do not treat labels as verification or add prose-derived bibliography entries.
    """
    lines = ['# UNVERIFIED MODEL DRAFT', '',
             'Scientific validation: not_performed.',
             'Human review required. Every paragraph below is model-generated commentary. '
             'Any numbers, conclusions or inline references in this draft may be unsupported '
             'or invented. Verify them against the separate deterministic evidence report '
             'and original supplied sources before use. This is not a validated manuscript '
             'or permission to publish.', '']
    lines += ['Draft readiness: '+_text(report.get('draft_readiness','not_assessed'))+'.', '']
    if report['dry_run']:
        lines += ['DRY RUN: no experiment was executed; this draft cannot establish measured results.', '']
    if report['fixture'] or report['proposal_fixture']:
        lines += ['SYNTHETIC FIXTURE: this draft contains synthetic demonstration material, not scientific findings.', '']
    for section in report['sections']:
        lines += [f'## {TITLES[section["section_id"]]}', '', 'UNVERIFIED MODEL COMMENTARY', '']
        if section['commentary']:
            for paragraph in re.split(r'\n\s*\n', section['commentary']):
                lines += [_text(paragraph), '']
        else:
            lines += ['No model draft is available for this section.', '']
        if section['citation_ids']:
            lines += ['Supplied source IDs selected by the model: ' +
                      ', '.join(_text(identity) for identity in section['citation_ids']) +
                      '. Whether these sources support the prose is unverified.', '']
    lines += ['## Supplied Source Catalog', '',
              'This catalog contains only supplied proposal evidence. It does not validate '
              'any additional references mentioned in generated prose.', '']
    for reference in report['references']:
        lines += [f'- {_text(reference["paper_id"])}: {_text(reference["title"])}. '
                  f'Reading scope: {_text(reference["evidence_scope"])}.']
    if not report['references']:
        lines += ['No supplied sources are available.']
    if report.get('research_analysis'):
        details=report.get('research_details',{})
        if details:
            lines += ['', '## Recorded implementation appendix', '',
                      'Controller-authored implementation notes and frozen configuration.', '']
            for key in ('selected_policy','functions','split_sizes','operators','inputs','search','hash','gate','exact_probe','semantic_audit','selection','unexecuted_controls'):
                if key in details:
                    value=json.dumps(details[key],ensure_ascii=False) if isinstance(details[key],(dict,list)) else details[key]
                    lines += ['- '+_text(key)+': '+_text(value)]
            for key in ('population','generations','development_seeds','confirmation_seeds'):
                if key in report['contract']:
                    lines += ['- '+_text(key)+': '+_text(json.dumps(report['contract'][key]))]
        # The numerical appendix is controller rendered from recorded analysis,
        # never copied from or inferred out of model prose.
        facts=render_markdown(report)
        marker='## Bounded heldout experiment\n'
        if marker in facts:
            lines += ['', '## Recorded measurement appendix', '',
                      'Controller-rendered data from the frozen experiment; separate from unverified prose.', '',
                      facts.split(marker,1)[1]]
    return '\n'.join(lines) + '\n'


def proposal_context(proposal):
    """Stable semantic view; replay logs and duplicate histories are not evidence.

    Keep source extractions and accepted requirements intact. The complete ledger
    remains in artifacts, without being copied into every section request.
    """
    from ..discussion.context import compact_payload, compact_handoff
    view = {key: deepcopy(proposal[key]) for key in
            ('topic', 'mode', 'status', 'selected_index', 'errors', 'evidence') if key in proposal}
    view['candidates'] = []
    for candidate in proposal.get('candidates', []):
        chain = candidate.get('chain', {})
        novelty = candidate.get('novelty', {})
        view['candidates'].append({
            **{key: deepcopy(candidate[key]) for key in ('idea', 'future', 'human_considerations') if key in candidate},
            'chain': {key: deepcopy(chain[key]) for key in ('evidence', 'trend', 'entities', 'relation', 'stop_reasons') if key in chain},
            'novelty': {**{key: deepcopy(novelty[key]) for key in ('status', 'summary', 'similar_paper_id', 'basis') if key in novelty},
                        'compared_source_ids': [p.get('paper_id') for p in novelty.get('compared_papers', [])],
                        **{key:deepcopy(novelty[key]) for key in ('research_claims','review_receipt') if key in novelty}},
            'rejected_attempts': [{key: deepcopy(attempt[key]) for key in
                ('attempt', 'summary', 'similar_paper_id', 'queries') if key in attempt}
                for attempt in candidate.get('rejected_attempts', [])]})
    experiment = proposal.get('experiment')
    if isinstance(experiment, dict):
        view['experiment'] = {key: deepcopy(experiment[key]) for key in
                              ('proposal', 'status', 'design_contract') if key in experiment}
    discussion = proposal.get('discussion')
    if isinstance(discussion, dict):
        view['discussion'] = {'status': discussion.get('status'),
            'critiques': [{key: deepcopy(c[key]) for key in
                ('critique_id', 'status', 'requested_change', 'uncertainty', 'error_code') if key in c}
                for c in discussion.get('critiques', [])]}
        if discussion.get('plan_handoff'):
            view['discussion']['plan_handoff'] = compact_handoff(discussion['plan_handoff'])
    view['evidence_ids'] = [source['paper_id'] for source in supplied_references(proposal)]
    view['history_scope'] = 'Final proposal and supplied evidence only; full history and audit are retained separately.'
    return compact_payload('report', view)


async def generate_report(runtime, proposal: dict, execution: dict, *, on_progress=None) -> dict:
    """Draft/review with the supplied Runtime; deterministic facts survive model failure."""
    if not isinstance(proposal, dict) or not isinstance(execution, dict):
        raise ValueError('Proposal and execution must be dictionaries')
    references = supplied_references(proposal)
    reference_ids = {r['paper_id'] for r in references}
    observations, warnings, dry_run = recorded_observations(execution)
    contract = execution.get('contract', {})
    report = {'schema_version': 'sage.report.v1', 'status': 'running',
              'scientific_validation': 'not_performed', 'fixture': execution.get('fixture') is True,
              'proposal_fixture': proposal.get('mode') == 'offline', 'dry_run': dry_run,
              'execution_status': execution.get('status', 'unknown'),
              'contract': deepcopy(contract) if isinstance(contract, dict) else {},
              'contract_digest': execution.get('contract_digest'),
              'selected_attempt_id': execution.get('selected_attempt_id'),
              'observations': observations, 'references': references, 'sections': [],
              'model_review': None, 'revision_history': [], 'errors': [],
              'evidence_warnings': warnings,
              'rendering_policy': 'deterministic_evidence_only_model_prose_quarantined',
              'source_methods': ['PaperSolver.gen_initial_report', 'PaperSolver.system_prompt',
                                 'PaperSolver.solve', 'PaperSolver.process_command', 'agents.get_score']}
    if execution.get('research_analysis') is not None:
        report['research_analysis']=deepcopy(execution['research_analysis'])
    if execution.get('research_details') is not None:
        report['research_details']=deepcopy(execution['research_details'])
    report['sections'] = [{'section_id': name, 'title': TITLES[name], 'commentary': '',
                           'citation_ids': [], 'claim_status': 'unverified_model_commentary',
                           'rendered_in_markdown': False, 'status': 'not_generated'} for name in SECTIONS]
    if on_progress:
        on_progress(report)
    context = {'proposal': proposal_context(proposal), 'references': references, 'contract': report['contract'],
               'execution_status': report['execution_status'], 'observations': observations,
               'fixture': report['fixture'], 'dry_run': dry_run,
               'scientific_validation': 'not_performed'}
    if 'research_analysis' in report:
        context['research_analysis']=report['research_analysis']
    if 'research_details' in report:
        context['research_details']=report['research_details']
        context['writing_priority']='Describe the executed pilot in actual prose. Discuss unexecuted proposal controls only as future work and limitations; never turn them into completed methods.'
    stage = 'writing.scaffold'
    try:
        def validate_scaffold(values):
            if parse_json(values['sections'], 'Report scaffold') != list(SECTIONS):
                raise InvalidResponse('Report scaffold must preserve all designated sections')
        await runtime.ask(stage, scaffold_prompt(), ('sections',), validate=validate_scaffold)
        for section in report['sections']:
            stage = 'writing.section'
            values = await runtime.ask(stage, section_prompt(section['section_id'], context, report['sections']),
                                       ('section',), validate=lambda values: parse_section(values['section'], reference_ids))
            section.update(parse_section(values['section'], reference_ids))
            if on_progress:
                on_progress(report)
            runtime.event(stage, 'drafted', section_id=section['section_id'], claim_status='unverified_model_commentary')
        stage = 'review.report'
        report['model_review'] = await review_report(runtime, context, report['sections'])
        rounds = min(runtime.config.refinement_rounds, 3)
        for round_index in range(rounds):
            current_review = report['model_review']
            if not current_review['requires_revision']:
                break
            stage = 'writing.revise'
            entry = {'round': round_index + 1, 'status': 'started', 'accepted': False,
                     'basis': 'unverified_model_score_only', 'edits': [], 'model_review': None}
            report['revision_history'].append(entry)
            values = await runtime.ask(stage, revision_prompt(context, report['sections'], current_review),
                                       ('edits',), validate=lambda values: parse_edits(values['edits'], reference_ids))
            edits = parse_edits(values['edits'], reference_ids)
            entry['edits'] = deepcopy(edits)
            if not edits:
                entry['status'] = 'no_edits'
                break
            candidate = deepcopy(report['sections'])
            for edit in edits:
                candidate[SECTIONS.index(edit['section_id'])].update(edit)
            stage = 'review.report'
            candidate_review = await review_report(runtime, context, candidate)
            entry['model_review'] = candidate_review
            if candidate_review['model_score'] > current_review['model_score']:
                entry['accepted'] = True
                entry['previous_sections'] = deepcopy(report['sections'])
                entry['previous_review'] = current_review
                report['sections'], report['model_review'] = candidate, candidate_review
            entry['status'] = 'accepted' if entry['accepted'] else 'retained_previous_draft'
            if on_progress:
                on_progress(report)
            runtime.event('writing.revise', entry['status'], round=round_index + 1,
                          basis='unverified_model_score_only')
        report['status'] = 'completed_with_uncertainty' if warnings else 'completed'
    except SageError as error:
        report['status'] = 'stopped' if isinstance(error, BudgetExceeded) else 'partial'
        report['errors'].append({'stage': stage, 'code': error.code,
                                 'message': 'Writing stage did not complete; recorded evidence is preserved.'})
        if report['revision_history'] and report['revision_history'][-1]['status'] == 'started':
            report['revision_history'][-1]['status'] = 'failed_previous_draft_preserved'
        runtime.event('writing.report', report['status'], error_code=error.code)
    report['markdown'] = render_markdown(report)
    # Completion describes a bounded software workflow, not manuscript readiness.
    # Keep an unresolved reviewer request visible even when the call chain ended.
    review=report.get('model_review')
    report['draft_readiness']=('incomplete' if not report['status'].startswith('completed') else
        ('revision_required' if review is None or review.get('requires_revision') else 'draft_for_human_review'))
    report['draft_markdown'] = render_draft_markdown(report)
    if on_progress:
        on_progress(report)
    return report
