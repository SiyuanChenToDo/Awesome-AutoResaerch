"""Independent adversarial checks of Agent Laboratory adaptation boundaries."""
import unittest
from dataclasses import FrozenInstanceError, replace
from sage.config import RunConfig
from sage.errors import ConfigurationError, ProviderError
from sage.runtime import Runtime
from sage.types import ExperimentPlan
from sage.execution import ExperimentRunner
from sage.execution.commands import apply_command
from sage.execution.fixtures import fixture_contract, TrustedFixtureBackend, BASELINE_CODE


class Model:
    def __init__(self, command, fail_reflection=False):
        self.command, self.fail_reflection = command, fail_reflection
    async def complete(self, stage, prompt, *, max_tokens):
        if stage == 'execution.reflect':
            if self.fail_reflection:
                raise ProviderError('secret-token-must-not-leak')
            return '<reflection>Continue bounded exploration.</reflection>'
        return '<command>' + self.command + '</command>'


def runtime(model):
    return Runtime(model, model, None, RunConfig())


class IndependentContractTests(unittest.TestCase):
    def test_immutable_contract_and_redaction(self):
        c = fixture_contract()
        with self.assertRaises(FrozenInstanceError):
            c.targets = (1, 1, 1)
        with self.assertRaises(ConfigurationError):
            replace(c, targets=[0, 2, 4])
        self.assertNotIn('targets', c.public_record())
        self.assertNotEqual(c.sha256, replace(c, targets=(1, 2, 4)).sha256)

    def test_metric_rejects_self_reported_and_nonfinite_outputs(self):
        c = fixture_contract()
        for invalid in ({'mse': 0}, [True, 2, 4], [0, float('nan'), 4], [0, 2], 'accuracy=1.0'):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                c.evaluate(invalid)
        self.assertEqual(c.evaluate([0, 1, 2]), {'mse': 5 / 3})

    def test_single_command_strict_and_inclusive_edits(self):
        self.assertEqual(apply_command('```EDIT 1 2\nx\n```', 'a\nb\nc\nd'), 'a\nx\nd')
        for bad in ('```EDIT 0 3\nx\n```', '```EDIT 2 1\nx\n```',
                    '```REPLACE\nx\n```\n```REPLACE\ny\n```',
                    'prefix\n```REPLACE\nx\n```', '```REPLACE\nx\n```\nsuffix'):
            with self.subTest(command=bad), self.assertRaises(ValueError):
                apply_command(bad, 'a\nb\nc')

    def test_execution_requires_exact_contract_approval(self):
        c = fixture_contract()
        for kw in ({}, {'allow_execution': True}, {'allow_execution': True, 'approved_contract_digest': 'wrong'}):
            with self.subTest(kw=kw), self.assertRaises(ConfigurationError):
                ExperimentRunner(runtime(Model('')), c, backend=TrustedFixtureBackend(), **kw)


class IndependentRunnerTests(unittest.IsolatedAsyncioTestCase):
    async def test_arbitrary_source_is_not_executed_by_fixture(self):
        backend = TrustedFixtureBackend()
        with self.assertRaises(ValueError):
            await backend.predict('raise RuntimeError("arbitrary code")', (1,), timeout=1)

    async def test_dry_run_validates_syntax_but_no_metrics(self):
        model = Model('```REPLACE\nraise RuntimeError("must never execute")\n```')
        result = await ExperimentRunner(runtime(model), fixture_contract()).run(ExperimentPlan('proposal'))
        self.assertEqual(result['status'], 'dry_run')
        self.assertEqual(result['attempts'][0]['metrics'], {})
        self.assertIsNone(result['selected_attempt_id'])

    async def test_all_rejected_commands_count_and_stop(self):
        c = replace(fixture_contract(), max_attempts=3, max_repairs=5)
        r = runtime(Model('```EDIT 100 200\nx\n```'))
        result = await ExperimentRunner(r, c).run(ExperimentPlan('proposal'))
        self.assertEqual(len(result['attempts']), 3)
        self.assertEqual(r.usage['model_calls'], 3)
        self.assertTrue(all(a['status'] == 'failed' for a in result['attempts']))
        self.assertEqual(result['status'], 'no_valid_candidate')

    async def test_reflection_failure_preserves_successful_measurement(self):
        c = fixture_contract()
        model = Model('```REPLACE\n' + BASELINE_CODE + '\n```', fail_reflection=True)
        result = await ExperimentRunner(runtime(model), c, backend=TrustedFixtureBackend(),
            allow_execution=True, approved_contract_digest=c.sha256).run(ExperimentPlan('proposal'))
        self.assertEqual(result['attempts'][0]['status'], 'evaluated_fixture')
        self.assertEqual(result['attempts'][0]['metrics']['mse'], 5 / 3)
        self.assertEqual(result['selected_attempt_id'], 'attempt-1')
        self.assertNotIn('secret-token', str(result))
