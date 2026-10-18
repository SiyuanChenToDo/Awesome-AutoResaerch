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
            return ScoreBundle(scores={'proposal': Score(0.0, 'proposal', 'No conjectures.json yet')},
                               aggregated=0.0, feedback='Generate primary conjectures and use the research tools before submitting.')
        # Grader checkout is a different worktree; the manager-owned service
        # accepts only paths within this run and checks source IDs against its cache.
        # CORAL supplies the submitting identity in manager-created Task metadata,
        # outside the agent-authored primary manuscript.
        agent_id = self.tasks[0].metadata.get('agent_id') if self.tasks else None
        payload = json.dumps({'artifact_path': str(path), 'agent_id': agent_id}).encode() + b'\n'
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
            connection.settimeout(600)
            connection.connect(os.environ['SAGE_GRADER_SOCKET'])
            connection.sendall(payload)
            with connection.makefile('rb') as response:
                result = json.loads(response.readline(2_000_001))
        if result.get('error'):
            raise RuntimeError('Research service grading failed: ' + result['error'])
        feedback = json.dumps(result, ensure_ascii=False)
        return ScoreBundle(scores={'proposal': Score(result['score'], 'proposal_readiness',
            'Advisory model opinion after source/testability checks; not scientific validation')},
            aggregated=result['score'], feedback=feedback,
            metadata={'scientific_validation': 'not_performed', 'independent_acceptance': False})
