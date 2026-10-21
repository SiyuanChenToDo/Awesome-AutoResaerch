"""Native CORAL TaskGrader for evidence-scoped scientific conjectures.

This executes no agent code. Scientific opinions come from a fresh provider call;
the deterministic source checks and that opinion are reported separately.
"""
import json
import os
import socket
from pathlib import Path
from coral.grader import TaskGrader
from coral.types import Score, ScoreBundle


class Grader(TaskGrader):
    def evaluate(self):
        path = Path(self.codebase_path) / 'conjectures.json'
        if not path.is_file() or path.is_symlink():
            return ScoreBundle(scores={'proposal': Score(0.0, 'proposal', 'Operational failure: no safe primary file; no scientific rating')},
                               aggregated=0.0, feedback='Generate primary conjectures and use the research tools before submitting.',
                               metadata={'evaluation_status': 'missing_primary', 'scientific_score': None,
                                         'score_semantics': 'operational_failure_sentinel_not_scientific_rating',
                                         'scientific_validation': 'not_performed', 'independent_acceptance': False})
        # Grader checkout is a different worktree; the manager-owned service
        # accepts only paths within this run and checks source IDs against its cache.
        # CORAL supplies the submitting identity in manager-created Task metadata,
        # outside the agent-authored primary manuscript.
        agent_id = self.tasks[0].metadata.get('agent_id') if self.tasks else None
        payload = json.dumps({'artifact_path': str(path), 'agent_id': agent_id}).encode() + b'\n'
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
            connection.settimeout(1800)
            connection.connect(os.environ['SAGE_GRADER_SOCKET'])
            connection.sendall(payload)
            with connection.makefile('rb') as response:
                result = json.loads(response.readline(2_000_001))
        if result.get('error'):
            raise RuntimeError('Research service grading failed: ' + result['error'])
        feedback = json.dumps(result, ensure_ascii=False)
        # The service normally always includes 'score', but the wire response
        # must never crash the grader: a malformed or partial response is an
        # operational failure sentinel, not an exception (observed in the wild
        # as KeyError escaping evaluate() during finalization).
        score_value = result.get('score')
        if not isinstance(score_value, (int, float)):
            return ScoreBundle(scores={'proposal': Score(0.0, 'proposal',
                'Operational failure: research service returned no numeric score; no scientific rating')},
                aggregated=0.0, feedback=feedback,
                metadata={'evaluation_status': result.get('evaluation_status') or 'malformed_service_response',
                          'scientific_score': None,
                          'score_semantics': 'operational_failure_sentinel_not_scientific_rating',
                          'scientific_validation': 'not_performed', 'independent_acceptance': False})
        completed = result.get('evaluation_status', 'completed') == 'completed' and not result.get('contract_errors')
        return ScoreBundle(scores={'proposal': Score(score_value, 'proposal_readiness',
            ('Advisory model opinion after source/testability checks; not scientific validation' if completed else
             'Operational failure sentinel; no scientific rating was established'))},
            aggregated=score_value, feedback=feedback,
            metadata={'scientific_validation': 'not_performed', 'independent_acceptance': False,
                      'evaluation_status': result.get('evaluation_status'),
                      'scientific_score': result.get('scientific_score') if completed else None})
