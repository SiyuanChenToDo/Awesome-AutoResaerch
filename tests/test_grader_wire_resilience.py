"""Regression tests: the CORAL grader shim must never raise on malformed wire responses.

Observed in the wild (run manual-20261021-162740 finalization): the research
service returned a response without a numeric 'score' and without a truthy
'error', and Grader.evaluate raised KeyError('score'), which CORAL surfaced as
"Grader raised: KeyError: 'score'". A malformed or partial wire response is an
operational failure sentinel, never an exception.
"""
import importlib
import io
import json
import os
import sys
import types
import unittest
from unittest import mock


def _fake_coral():
    coral = types.ModuleType('coral')
    coral_grader = types.ModuleType('coral.grader')
    coral_types = types.ModuleType('coral.types')

    class TaskGrader:
        pass

    class Score:
        def __init__(self, value, name, rationale=''):
            self.value = value
            self.name = name
            self.rationale = rationale

    class ScoreBundle:
        def __init__(self, scores, aggregated=None, feedback='', metadata=None):
            self.scores = scores
            self.aggregated = aggregated
            self.feedback = feedback
            self.metadata = metadata or {}

    coral_grader.TaskGrader = TaskGrader
    coral_types.Score = Score
    coral_types.ScoreBundle = ScoreBundle
    coral.grader = coral_grader
    coral.types = coral_types
    return {'coral': coral, 'coral.grader': coral_grader, 'coral.types': coral_types}


class GraderWireResilienceTests(unittest.TestCase):
    def setUp(self):
        self._modules = _fake_coral()
        self._real_modules = {name: sys.modules.get(name) for name in self._modules}
        sys.modules.update(self._modules)
        self.addCleanup(self._restore_modules)
        if 'sage.autonomous.grader' in sys.modules:
            del sys.modules['sage.autonomous.grader']
        self.grader_module = importlib.import_module('sage.autonomous.grader')

    def _restore_modules(self):
        for name, module in self._real_modules.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module

    def _grader(self, wire_json):
        grader = self.grader_module.Grader()
        grader.codebase_path = self._tmp_conjectures()
        grader.tasks = [types.SimpleNamespace(metadata={'agent_id': 'captain-nemo'})]
        payload = wire_json.encode('utf-8') + b'\n'
        connection = mock.MagicMock()
        connection.__enter__.return_value.makefile.return_value = io.BytesIO(payload)
        socket_factory = mock.MagicMock(return_value=connection)
        return grader, socket_factory

    def _tmp_conjectures(self):
        import tempfile
        from pathlib import Path
        directory = tempfile.mkdtemp()
        Path(directory, 'conjectures.json').write_text('{"candidates": []}', encoding='utf-8')
        self.addCleanup(lambda: __import__('shutil').rmtree(directory, ignore_errors=True))
        return directory

    def _evaluate(self, wire_obj):
        grader, socket_factory = self._grader(json.dumps(wire_obj, ensure_ascii=False))
        with mock.patch.object(self.grader_module.socket, 'socket', socket_factory), \
                mock.patch.object(self.grader_module.socket, 'AF_UNIX', 1, create=True), \
                mock.patch.dict(os.environ, {'SAGE_GRADER_SOCKET': '/tmp/fake-grader.sock'}):
            return grader.evaluate()

    def test_response_without_score_is_sentinel_not_keyerror(self):
        bundle = self._evaluate({'error': None, 'evaluation_status': None})
        self.assertEqual(bundle.metadata['evaluation_status'], 'malformed_service_response')
        self.assertEqual(bundle.scores['proposal'].value, 0.0)
        self.assertEqual(bundle.aggregated, 0.0)
        self.assertEqual(bundle.metadata['scientific_validation'], 'not_performed')
        self.assertIn('operational_failure_sentinel', bundle.metadata['score_semantics'])

    def test_nonfinite_boolean_out_of_range_and_nonobject_are_sentinels(self):
        for value in ([1], None, {'score': True}, {'score': float('nan')},
                      {'score': float('inf')}, {'score': -1}, {'score': 1.1}):
            with self.subTest(value=value):
                result = self._evaluate(value)
                self.assertEqual(result.aggregated, 0)
                self.assertIsNone(result.metadata['scientific_score'])

    def test_response_with_truthy_error_still_raises_runtimeerror(self):
        with self.assertRaises(RuntimeError):
            self._evaluate({'error': 'ReviewStageError'})

    def test_completed_response_passes_score_through(self):
        bundle = self._evaluate({'score': 0.748, 'scientific_score': 0.748,
                                 'evaluation_status': 'completed', 'contract_errors': []})
        self.assertEqual(bundle.scores['proposal'].value, 0.748)
        self.assertEqual(bundle.aggregated, 0.748)
        self.assertEqual(bundle.metadata['evaluation_status'], 'completed')

    def test_contract_failed_response_keeps_zero_sentinel(self):
        bundle = self._evaluate({'score': 0.0, 'scientific_score': None,
                                 'evaluation_status': 'contract_failed',
                                 'contract_errors': ['Obtain a fresh-context critique']})
        self.assertEqual(bundle.scores['proposal'].value, 0.0)
        self.assertEqual(bundle.metadata['scientific_score'], None)


if __name__ == '__main__':
    unittest.main()
