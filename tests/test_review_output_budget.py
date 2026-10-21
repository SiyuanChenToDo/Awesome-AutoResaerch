"""Named review-chain output budget (49152) and the native maxTokens patch.

Evidence (2026-10-19 unattended run): novelty_feedback completion P100 was
~32.1k tokens, 2% below the former 32768 cap, and 25 of 36 review dispatches
entered repair retries consistent with truncation. The native DSH plugin
@deepseek-ai/dsh-llm-deepseek defaults to maxTokens=256000, a per-request hard
cap that also pre-reserves context (input budget = 1048576 - maxTokens).
"""
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

from sage.config import REVIEW_MAX_OUTPUT_TOKENS
from sage.errors import RequestCapacityError
from sage.providers import (CHAT_OVERHEAD_RESERVE, DEEPSEEK_CONTEXT_TOKENS,
                            DEEPSEEK_MAX_OUTPUT_TOKENS, OpenAIConfig, OpenAIModel)


def official_model(token_count):
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(
        create=mock.AsyncMock(return_value=SimpleNamespace(
            model='deepseek-flash', id='fixture-response', usage=None,
            choices=[SimpleNamespace(message=SimpleNamespace(content='{}', refusal=None),
                                     finish_reason='stop')])))))
    instance = OpenAIModel(OpenAIConfig(api_key='fixture-secret', provider='deepseek',
                                        model='deepseek-flash'), client=client)
    instance._tokenizer = SimpleNamespace(encode=mock.Mock(
        return_value=SimpleNamespace(ids=range(token_count))))
    return instance


class ReviewOutputBudgetTests(unittest.TestCase):
    def test_named_budget_is_49152_and_preflight_formula_still_holds(self):
        self.assertEqual(REVIEW_MAX_OUTPUT_TOKENS, 49152)
        # Still inside the RunConfig.max_tokens_per_call validation bound (65536)
        # and the official per-request output ceiling.
        self.assertLessEqual(REVIEW_MAX_OUTPUT_TOKENS, 65536)
        self.assertLessEqual(REVIEW_MAX_OUTPUT_TOKENS, DEEPSEEK_MAX_OUTPUT_TOKENS)
        at_boundary = DEEPSEEK_CONTEXT_TOKENS - REVIEW_MAX_OUTPUT_TOKENS - CHAT_OVERHEAD_RESERVE
        instance = official_model(at_boundary)
        measured = instance.preflight('at boundary', max_tokens=REVIEW_MAX_OUTPUT_TOKENS)
        self.assertEqual(measured['total_reserved_tokens'], DEEPSEEK_CONTEXT_TOKENS)
        over = official_model(at_boundary + 1)
        with self.assertRaises(RequestCapacityError) as caught:
            over.preflight('over boundary', max_tokens=REVIEW_MAX_OUTPUT_TOKENS)
        self.assertEqual(caught.exception.reason, 'context_capacity_exceeded')

    def test_no_magic_32768_remains_in_sage_sources(self):
        root = Path(__file__).resolve().parents[1] / 'sage'
        for path in sorted(root.rglob('*.py')):
            text = path.read_text(encoding='utf-8')
            self.assertNotIn('32768', text,
                             f'{path.relative_to(root)} still hardcodes the old review cap')

    def test_research_patch_caps_native_max_tokens_and_sets_burst_guardrail(self):
        from sage.autonomous.runner import prepare
        from sage.autonomous.skills import REQUIRED_REFERENCES, REQUIRED_SKILLS
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for name in REQUIRED_SKILLS:
                skill = root / 'ARIS' / 'skills' / name / 'SKILL.md'
                skill.parent.mkdir(parents=True, exist_ok=True)
                skill.write_text('Original fixture skill: ' + name)
            for name in REQUIRED_REFERENCES:
                reference = root / 'ARIS' / 'skills' / name
                reference.parent.mkdir(parents=True, exist_ok=True)
                reference.write_text('Original fixture reference: ' + name)
            config = prepare(root, topic='Topic', aris_root=root / 'ARIS',
                             coral_python=Path('/python'), dsh=Path('/dsh'), agent_user='research')
            text = (root / 'research.patch.yml').read_text(encoding='utf-8')
            # One cordis overlay keying into dsh-base's existing llm-deepseek entry;
            # the per-launch provider/model overlay is a separate runtime-config
            # patch written by dsh_runtime.start(), never this file.
            self.assertIn('- id: llm-deepseek\n  config:\n    maxTokens: 65536\n', text)
            self.assertEqual(text.count('- id: llm-deepseek'), 1)
            agents = config['agents']
            self.assertEqual(agents['restart_burst_threshold'], 3)
            self.assertEqual(agents['restart_burst_window'], 120)
            self.assertEqual(agents['restart_pause_seconds'], 300)
            # The widened window must still satisfy coral/config.py:
            # pause_seconds >= window when the breaker is enabled.
            self.assertGreaterEqual(agents['restart_pause_seconds'], agents['restart_burst_window'])


if __name__ == '__main__':
    unittest.main()
