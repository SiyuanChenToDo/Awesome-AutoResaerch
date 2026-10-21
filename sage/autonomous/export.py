"""Export the latest valid submission while preserving the historical best.

A single uncalibrated model score must not silently roll back a later protocol.
The highest score remains a labelled historical artifact, never a truth claim.
"""
import hashlib
from pathlib import Path

from ..artifacts import atomic_bytes, atomic_json
from .report import validate_report


def export_submissions(private, destination, grades):
    eligible = [g for g in grades if g.get('contract_errors') == []
                and g.get('evaluation_status', 'completed') == 'completed'
                and type(g.get('score')) in (int, float) and 0 <= g['score'] <= 1]
    if not eligible:
        return {'selected_grade': None, 'best_score_grade': None,
                'policy': 'latest_contract_valid_submission', 'files': {}}
    latest = eligible[-1]
    best = max(eligible, key=lambda g: g['score'])
    private, destination = Path(private), Path(destination)
    # Read and verify all inputs before writing any exported artifact.
    contents = {}
    alignments = {}
    for grade in (latest, best):
        sha = grade['primary_sha256']
        raw = (private / f'conjectures-{sha}.json').read_bytes()
        if hashlib.sha256(raw).hexdigest() != sha:
            raise ValueError('Graded primary bytes do not match their recorded SHA-256')
        report_file = grade.get('report_file', f'report-{sha}.md')
        report = (private / report_file).read_bytes()
        if grade.get('report_sha256') and hashlib.sha256(report).hexdigest() != grade['report_sha256']:
            raise ValueError('Graded report bytes do not match their recorded SHA-256')
        version = grade.get('synthesis_version')
        alignment = validate_report(raw, report, synthesis_version=version)
        if alignment['errors']:
            raise ValueError('Graded report is not internally bound to its primary: ' + '; '.join(alignment['errors']))
        contents[(sha, report_file)] = (raw, report)
        alignments[(sha, report_file)] = alignment
    files = {}
    for prefix, grade in (('', latest), ('latest-', latest), ('best-score-', best)):
        primary, report = contents[(grade['primary_sha256'],
                                   grade.get('report_file', f'report-{grade["primary_sha256"]}.md'))]
        atomic_bytes(destination / f'{prefix}conjectures.json', primary)
        atomic_bytes(destination / f'{prefix}CONJECTURES.md', report)
        files[prefix or 'primary'] = {'primary': f'{prefix}conjectures.json',
                                     'report': f'{prefix}CONJECTURES.md',
                                     'primary_sha256': grade['primary_sha256'],
                                     'report_sha256': hashlib.sha256(report).hexdigest(),
                                     'report_alignment': alignments[(grade['primary_sha256'],
                                         grade.get('report_file', f'report-{grade["primary_sha256"]}.md'))]}
    receipt = {'policy': 'latest_contract_valid_submission', 'selected_grade': latest,
               'best_score_grade': best, 'files': files,
               'scientific_validation': 'not_performed',
               'explanation': 'Latest valid protocol is primary; highest single model score is historical, not a calibrated quality ordering.'}
    atomic_json(destination / 'export-selection.json', receipt)
    return receipt
