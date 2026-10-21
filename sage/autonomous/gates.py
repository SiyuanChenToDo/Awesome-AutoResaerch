"""Deterministic review-completion checks, not scientific validation."""
from datetime import datetime


def frozen_problem_anchors(primary, primary_sha, team=None, research_slot=None):
    """Use manager-frozen problems, never an author's mutable anchor claim."""
    anchors = {}
    if team:
        is_synthesis = not team.grade_errors(primary, primary_sha)
        for candidate in primary.get('candidates', []):
            if not isinstance(candidate, dict):
                continue
            ident = candidate.get('id')
            origin = candidate.get('origin', {}) if is_synthesis else {}
            slot = origin.get('slot') if is_synthesis else research_slot
            source_id = origin.get('candidate_id') if is_synthesis else ident
            proposal = team.state['proposals'].get(str(slot), {}).get('document', {})
            original = next((c for c in proposal.get('candidates', [])
                             if c.get('id') == source_id), None)
            if original and isinstance(original.get('problem'), str) and original['problem'].strip():
                anchors[ident] = {'problem': original['problem'], 'scope': 'manager_frozen_initial_proposal'}
    return {'status': 'available' if anchors else 'not_frozen', 'candidates': anchors,
            'instruction': 'Compare current problem against its frozen initial problem. A justified pivot is allowed but must be identified; no anchor means drift was not independently checked.'}


def advisory_errors(primary_sha, reviews, team=None):
    """Require post-synthesis reviews and a review of the actual submitted file.

    A review of an independent researcher's old proposal cannot discharge the
    coordinator's synthesis review requirement. Distinct receipts count once;
    these remain same-family advice, not independent scientific acceptance.
    """
    syntheses = team.state['syntheses'] if team else []
    registered = None
    if team:
        if not syntheses:
            return ['Register the completed synthesis before requesting its advisory reviews']
        registered = {}
        for synthesis in syntheses:
            sha = synthesis['primary_sha256']
            time = datetime.fromisoformat(synthesis['receipt']['time'])
            registered[sha] = min(registered.get(sha, time), time)
    eligible = {}
    for review in reviews:
        if review.get('grading') is not False or not isinstance(review.get('id'), str):
            continue
        sha = review.get('input_sha256')
        if not isinstance(sha, str) or len(sha) != 64:
            continue
        if team:
            try:
                after_synthesis = (sha in registered and
                                   datetime.fromisoformat(review['time']) >= registered[sha])
            except (KeyError, TypeError, ValueError):
                continue
            if review.get('research_slot') != 0 or sha not in registered or not after_synthesis:
                continue
        eligible[review['id']] = review
    errors = []
    if len(eligible) < 2:
        errors.append('Obtain at least two advisory reviews of the registered synthesis lineage; '
                      'researcher-stage or formal grades do not count')
    if not any(r['input_sha256'] == primary_sha for r in eligible.values()):
        errors.append('Obtain an advisory review of the exact current primary artifact after its last change')
    return errors
