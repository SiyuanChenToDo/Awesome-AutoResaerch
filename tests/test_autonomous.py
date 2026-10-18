import copy
import json
from pathlib import Path
import tempfile
import unittest
from sage.autonomous.service import candidate_errors, read_primary, ResearchService
from sage.autonomous.runner import prepare, dsh_endpoint
from sage.autonomous.skills import REQUIRED_SKILLS, assemble_native_task


def candidates():
    return {'candidates': [{'id': f'C{i}', 'title': 'Hypothesis', 'problem': 'Problem',
        'hypothesis': 'Conditional prediction', 'mechanism': 'Mechanistic explanation',
        'assumptions': 'Specified conditions', 'source_ids': ['p1', 'p2'],
        'closest_prior_art': [{'paper_id': 'p1', 'overlap': 'Same problem', 'difference': 'Specific mechanism'}],
        'falsification': {'test': 'Held-out test', 'controls': 'Matched control', 'metric': 'Error', 'reject_if': 'No effect'},
        'risks': ['Prior art overlap'], 'status': 'provisional'} for i in range(8)], 'selected_ids': ['C0']}


class AutonomousTests(unittest.TestCase):
    def test_messages_endpoint_does_not_inherit_chat_completion_root(self):
        self.assertEqual(dsh_endpoint({'SAGE_OPENAI_BASE_URL': 'https://api.deepseek.com'}),
                         'https://api.deepseek.com/anthropic')
        self.assertEqual(dsh_endpoint({'SAGE_DSH_BASE_URL': 'https://gateway.example/anthropic'}),
                         'https://gateway.example/anthropic')

    def test_source_and_status_contract_fails_closed(self):
        item = candidates()
        self.assertEqual(candidate_errors(item, {'p1': {}, 'p2': {}}, {'p1': {'claims': [1]}}), [])
        item['candidates'][0]['source_ids'] = ['invented', 'p2']
        item['candidates'][1]['status'] = 'validated'
        errors = candidate_errors(item, {'p1': {}, 'p2': {}}, {'p1': {'claims': [1]}})
        self.assertTrue(any('actually retrieved' in x for x in errors))
        self.assertTrue(any('provisional' in x for x in errors))

    def test_no_capsule_or_falsifier_is_not_ready(self):
        item = candidates()
        item['candidates'][0]['falsification'].pop('reject_if')
        errors = candidate_errors(item, {'p1': {}, 'p2': {}}, {})
        self.assertTrue(any('quote-checked' in x for x in errors))
        self.assertTrue(any('rejection criterion' in x for x in errors))

    def test_primary_path_escape_and_symlink_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); inside = root / 'run'; inside.mkdir()
            outside = root / 'secret.json'; outside.write_text('{}')
            with self.assertRaises(ValueError):
                read_primary(outside, inside)
            try:
                (inside / 'link.json').symlink_to(outside)
            except OSError:
                return
            with self.assertRaises(ValueError):
                read_primary(inside / 'link.json', inside)

    def test_empty_retrieval_never_passes_grade(self):
        import asyncio
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            checkout = root / 'native-run' / '.coral' / 'private' / 'grader_checkouts' / 'fixture'
            checkout.mkdir(parents=True)
            artifact = checkout / 'conjectures.json'
            artifact.write_text(json.dumps(candidates()))
            service = ResearchService(root / 'private', root, 'topic')
            result = asyncio.run(service.grade(artifact))
            self.assertEqual(result['score'], 0)
            self.assertTrue(result['contract_errors'])
            self.assertEqual(service.reviews, [])

    def test_agent_owned_document_cannot_be_submitted_as_private_grade(self):
        import asyncio
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); path = root / 'conjectures.json'; path.write_text('{}')
            service = ResearchService(root / 'private', root, 'topic')
            with self.assertRaises(ValueError):
                asyncio.run(service.grade(path))

    def test_seed_is_empty_and_native_driver_is_configured(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for name in REQUIRED_SKILLS:
                skill = root / 'ARIS' / 'skills' / name / 'SKILL.md'
                skill.parent.mkdir(parents=True)
                skill.write_text('Original skill: ' + name + '\nLiteral ${shell(example)}', encoding='utf-8')
            config = prepare(root, topic='Topic', aris_root=root / 'ARIS', coral_python=Path('/python'),
                             dsh=Path('/dsh'), agent_user='research')
            self.assertEqual(config['agents']['runtime'], 'sage.autonomous.dsh_runtime:ResumableDeepSeekRuntime')
            self.assertEqual(config['agents']['count'], 4)
            self.assertEqual([a['runtime_options']['research_slot'] for a in config['agents']['assignments']], [0,1,2,3])
            self.assertTrue(all(a['count'] == 1 for a in config['agents']['assignments']))
            self.assertIn('team protocol', (root / 'seed' / 'AGENTS.local.md').read_text())
            self.assertEqual(config['agents']['runtime_options']['session_state_dir'], str(root / 'session-state'))
            self.assertEqual(config['run']['session'], 'local')
            self.assertEqual(config['agents']['isolate_user'], 'research')
            self.assertEqual(config['agents']['timeout'], 0)
            self.assertIn('1800000', (root/'research.patch.yml').read_text())
            self.assertFalse((root / 'seed' / 'conjectures.json').exists())
            self.assertFalse(list((root / 'seed').glob('*.pdf')))
            self.assertIn('process.env.SAGE_RESEARCH_TOKEN', (root / 'research.patch.yml').read_text())
            receipt = json.loads((root / 'aris-inputs.json').read_text())
            self.assertEqual(len(receipt['skills']), 5)
            self.assertGreater(receipt['instruction_context_budget_bytes'], 65536)
            self.assertIn('${shell(example)}', (root / 'seed' / 'AGENTS.local.md').read_text())
            for name in REQUIRED_SKILLS:
                self.assertIn('Original skill: ' + name, (root / 'seed' / 'AGENTS.local.md').read_text())
            if __import__('os').name == 'posix':
                self.assertTrue((root / 'research.patch.yml').stat().st_mode & 0o004)

    def test_missing_required_skill_cannot_silently_become_a_catalog_only_run(self):
        with tempfile.TemporaryDirectory() as folder:
            from sage.errors import ConfigurationError
            with self.assertRaises(ConfigurationError):
                assemble_native_task(Path(folder), 'Workflow')

    def test_rejected_candidate_cannot_be_a_survivor(self):
        item = candidates()
        item['candidates'][0]['disposition'] = 'rejected'
        errors = candidate_errors(item, {'p1': {}, 'p2': {}}, {'p1': {'claims': [1]}})
        self.assertTrue(any('Rejected candidates' in x for x in errors))

    def test_cli_scales_only_the_default_shared_budget_with_team_size(self):
        from unittest.mock import patch
        from sage.cli import main
        for options, expected in (([], 640), (['--researchers','1'], 160),
                                  (['--researchers','4','--max-tools','240'], 240)):
            with self.subTest(options=options), tempfile.TemporaryDirectory() as folder:
                with patch('sage.autonomous.runner.run', return_value=0) as run:
                    self.assertEqual(main(['autonomous','--output', str(Path(folder) / 'run'), *options]), 0)
                    self.assertEqual(run.call_args.args[0].max_tools, expected)


if __name__ == '__main__':
    unittest.main()
