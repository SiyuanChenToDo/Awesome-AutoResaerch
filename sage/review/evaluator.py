"""Fixed deterministic contract audit, independent of generated prose and rankings.

This does not evaluate scientific truth, factual correctness or research quality.
It checks internal consistency only and cannot replace independent experiments.
"""
from __future__ import annotations


def audit_result(result, config):
    issues = []
    if result.status.startswith('completed'):
        if not result.candidates:
            issues.append('Completed run has no candidates')
        if result.selected_index is None or not 0 <= result.selected_index < len(result.candidates):
            issues.append('Selected index is invalid')
        if result.experiment is None or not result.experiment.proposal:
            issues.append('Completed run has no experiment proposal')
    if result.scientific_validation != 'not_performed':
        issues.append('Pipeline cannot assert scientific validation')
    if len(result.candidates) > config.max_candidates:
        issues.append('Candidate limit exceeded')
    for candidate in result.candidates:
        chain = candidate.chain
        if not config.min_chain_length <= len(chain.evidence) <= config.max_chain_length:
            issues.append('Chain size violates limits')
        ids = [e.paper.paper_id for e in chain.evidence]
        if len(ids) != len(set(ids)):
            issues.append('Chain contains duplicate paper IDs')
        if not candidate.idea or not chain.trend or not chain.entities:
            issues.append('Candidate contract is incomplete')
        novelty = candidate.novelty
        if not novelty.compared_papers and novelty.status != 'not_established':
            issues.append('Empty retrieval cannot establish a novelty comparison')
        if novelty.similar_paper_id and novelty.similar_paper_id not in {p.paper_id for p in novelty.compared_papers}:
            issues.append('Similar paper is not in retrieved evidence')
    for kind in ('model', 'search'):
        count = result.usage.get(kind + '_calls', 0)
        started = sum(e['status'] == 'started' and e.get('kind') == kind for e in result.audit)
        if count != started or count > getattr(config, 'max_' + kind + '_calls'):
            issues.append(kind + ' attempt accounting is inconsistent')
    if result.usage.get('reserved_output_tokens', 0) > config.max_reserved_output_tokens:
        issues.append('Output-token reserve limit exceeded')
    if result.experiment and result.experiment.status != 'proposal_only':
        issues.append('Experimental plan must remain proposal-only')
    if result.ranking and result.ranking.get('scientific_validation') is not False:
        issues.append('Model preference is not scientific validation')
    return {'evaluator': 'sage.contract_audit.v1', 'contract_passed': not issues, 'issues': issues,
            'scope': 'structural_consistency_only', 'scientific_quality_assessed': False}
