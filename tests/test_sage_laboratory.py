import asyncio
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from sage.config import RunConfig
from sage.execution.fixtures import LaboratoryFixtureModel, TrustedFixtureBackend, fixture_contract
from sage.fixtures import FixtureSource
from sage.orchestration.laboratory import run_laboratory


class Laboratory(unittest.IsolatedAsyncioTestCase):
    async def test_composition_dry(self):
        result=await run_laboratory('synthetic',LaboratoryFixtureModel(),FixtureSource(),contract=fixture_contract())
        self.assertEqual(result['status'],'dry_run')
        self.assertIn('DRY RUN',result['report']['markdown'])
        self.assertEqual(result['execution']['attempts'][0]['metrics'],{})
    async def test_composition_fixture(self):
        c=fixture_contract()
        result=await run_laboratory('synthetic',LaboratoryFixtureModel(),FixtureSource(),contract=c,
            backend=TrustedFixtureBackend(),allow_execution=True,approved_contract_digest=c.sha256)
        self.assertEqual(result['status'],'completed_fixture')
        self.assertIn('SYNTHETIC FIXTURE',result['report']['markdown'])
        self.assertEqual(result['execution']['selected_attempt_id'],'attempt-2')
        stages={x['stage'] for x in result['audit']}
        self.assertIn('execution.generate',stages);self.assertIn('review.report',stages)
        self.assertGreater(result['usage']['model_calls'], result['proposal']['usage']['model_calls'])
    async def test_shared_budget(self):
        result=await run_laboratory('synthetic',LaboratoryFixtureModel(),FixtureSource(),contract=fixture_contract(),config=RunConfig(max_model_calls=1))
        self.assertEqual(result['status'],'proposal_failed');self.assertIsNone(result['execution'])
        self.assertEqual(result['usage']['model_calls'],1)


class CLI(unittest.TestCase):
    def test_fixture_cli(self):
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)/'run'
            result=subprocess.run([sys.executable,'-m','sage','laboratory','--backend','fixture','--allow-execution','--output',str(path)],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            payload=json.loads((path/'result.json').read_text())
            self.assertEqual(payload['status'],'completed_fixture')
            self.assertTrue((path/'contract.json').exists());self.assertTrue((path/'report.md').exists())
            self.assertTrue((path/'draft.md').exists());self.assertTrue((path/'candidates/attempt-1.py').exists())
    def test_live_requires_explicit_contract(self):
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)/'run'
            result=subprocess.run([sys.executable,'-m','sage','laboratory','--mode','live','--allow-live','--output',str(path)],capture_output=True,text=True)
            self.assertEqual(result.returncode,2);self.assertFalse(path.exists())
            self.assertIn('explicit reviewed --contract',result.stderr)

    def test_execution_requires_opt_in_before_output(self):
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)/'run'
            result=subprocess.run([sys.executable,'-m','sage','laboratory','--backend','fixture','--output',str(path)],capture_output=True,text=True)
            self.assertEqual(result.returncode,2);self.assertFalse(path.exists())

if __name__=='__main__':unittest.main()
