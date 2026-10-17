"""Real subprocess smoke of exactly two reviewed synthetic programs.

This is not a generic execution backend, Docker test, or live-model evaluation.
Only the literal source below is accepted, and only its input path is changed.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from sage.config import RunConfig
from sage.execution.fixtures import (
    BASELINE_CODE, IMPROVED_CODE, LaboratoryFixtureModel, fixture_contract,
)
from sage.fixtures import FixtureSource
from sage.orchestration.laboratory import run_laboratory

REVIEWED = (
    'import json\nxs = json.load(open("/input/features.json"))["features"]\nprint(json.dumps([x for x in xs]))',
    'import json\nxs = json.load(open("/input/features.json"))["features"]\nprint(json.dumps([2*x for x in xs]))',
)


class ReviewedSubprocessBackend:
    fixture = True

    def __init__(self):
        self.records = []

    async def predict(self, code, features, *, timeout):
        if code not in REVIEWED:
            raise ValueError('Only reviewed literal synthetic programs may execute')
        with tempfile.TemporaryDirectory(prefix='sage-reviewed-') as directory:
            root = Path(directory)
            data = root / 'features.json'
            data.write_text(json.dumps({'features': list(features)}), encoding='utf-8')
            source = root / 'reviewed.py'
            source.write_text(code.replace('"/input/features.json"', repr(str(data))), encoding='utf-8')
            environment = {'LANG': 'C.UTF-8'}
            # Windows needs this OS path; no API credentials or general environment inherited.
            if os.name == 'nt' and 'SystemRoot' in os.environ:
                environment['SystemRoot'] = os.environ['SystemRoot']
            process = subprocess.run([sys.executable, '-I', str(source)], cwd=root,
                env=environment, stdin=subprocess.DEVNULL, capture_output=True,
                text=True, timeout=min(timeout, 5), check=True)
            if len(process.stdout) > 1000 or process.stderr:
                raise ValueError('Unexpected reviewed fixture output')
            predictions = json.loads(process.stdout)
            self.records.append((process.returncode, predictions))
            return predictions


class ReviewedHybridExecutionTests(unittest.IsolatedAsyncioTestCase):
    async def test_hybrid_real_execution_of_exact_reviewed_scripts(self):
        self.assertEqual((BASELINE_CODE, IMPROVED_CODE), REVIEWED)
        backend = ReviewedSubprocessBackend()
        contract = fixture_contract()
        result = await run_laboratory(
            'Synthetic hybrid subprocess validation', LaboratoryFixtureModel(), FixtureSource(),
            config=RunConfig(discussion_mode='hybrid'), contract=contract, backend=backend,
            allow_execution=True, approved_contract_digest=contract.sha256,
        )
        self.assertEqual(result['status'], 'completed_fixture')
        self.assertEqual(backend.records, [(0, [0, 1, 2]), (0, [0, 2, 4])])
        self.assertEqual([a['metrics']['mse'] for a in result['execution']['attempts']], [5/3, 0])
        self.assertEqual(result['execution']['selected_attempt_id'], 'attempt-2')
        handoff = result['proposal']['discussion']['plan_handoff']
        self.assertTrue(handoff['bound_to_plan'])
        self.assertTrue(handoff['requirements'])
        self.assertEqual(result['scientific_validation'], 'not_performed')
        self.assertIn('SYNTHETIC FIXTURE', result['report']['markdown'])

    async def test_unreviewed_source_is_rejected_before_process_spawn(self):
        backend = ReviewedSubprocessBackend()
        from unittest.mock import patch
        with patch('subprocess.run', side_effect=AssertionError('Must not spawn')):
            with self.assertRaises(ValueError):
                await backend.predict('print("not allowlisted")', (1,), timeout=1)
        self.assertEqual(backend.records, [])
