"""Evidence-led revision guidance and descriptive same-input score diagnostics.

These observations do not calibrate the model, establish improvement or request
extra reviews. Revision decisions must cite scientific problems and evidence;
the latest valid export must not become a search for the largest sampled score.
"""
from __future__ import annotations

import math
import re


def revision_policy():
    return {
        'version': 'sage.evidence_led_revision.v1',
        'score_role': 'advisory_readiness_signal_only',
        'single_score_rollback': False,
        'retain_candidates_to_avoid_schema': True,
        'calibration': 'none',
        'decision_basis': ['supported_problem', 'adjudicated_remedy',
                           'source_evidence', 'falsification_protocol', 'feasibility'],
        'required_decision_record': ['issue_id', 'problem_assessment',
                                     'remedy_assessment', 'decision', 'reason',
                                     'changed_fields', 'remaining_uncertainty'],
        'score_dispersion_is_not': ['estimated_population_variance', 'significance_test',
                                    'independent_validation', 'scientific_quality_ordering'],
        'request_extra_calls': False,
    }


def score_observations(receipts):
    """Compare only recorded identical numeric prompts and model identities.

    Missing prompt hashes are excluded rather than guessed from artifact hashes:
    evidence, anchors or hidden author fields may have changed. This deliberately
    returns a range, not confidence intervals or a calibrated noise estimate.
    """
    groups = {}
    for receipt in receipts:
        if not isinstance(receipt, dict):
            continue
        # A repair prompt includes the previous response and validation error.
        # Even when it preserves ratings, it is not an identical prompt repeat.
        # Conservatively omit repaired numeric stages from dispersion groups.
        if any(isinstance(call, dict) and call.get('stage') == 'scientific_review'
               and call.get('attempt', 1) != 1 for call in receipt.get('model_calls', [])):
            continue
        digest = receipt.get('review_prompt_sha256')
        model = receipt.get('reviewer_model')
        score = receipt.get('review', {}).get('score') if isinstance(receipt.get('review'), dict) else None
        if (not isinstance(digest, str) or not re.fullmatch('[0-9a-f]{64}', digest)
                or not isinstance(model, str) or not model.strip()
                or type(score) not in (int, float) or not math.isfinite(score)
                or not 0 <= score <= 1):
            continue
        groups.setdefault((digest, model), []).append((receipt.get('id'), score))
    result = []
    for (digest, model), values in groups.items():
        if len(values) < 2:
            continue
        scores = [score for _, score in values]
        low, high = min(scores), max(scores)
        result.append({'review_prompt_sha256': digest, 'reviewer_model': model,
                       'receipt_ids': [ident for ident, _ in values],
                       'sample_count': len(values), 'scores': scores,
                       'observed_min': low, 'observed_max': high,
                       'observed_range': round(high - low, 12),
                       'interpretation': ('same_input_observed_score_dispersion'
                                          if high > low else 'same_input_observed_agreement'),
                       'calibration': 'none',
                       'scientific_quality_change': 'not_established',
                       'decision': 'adjudicate_problems_and_remedies_not_single_score'})
    return result
