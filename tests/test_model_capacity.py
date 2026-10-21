"""Capacity and dispatch contracts with local tokenizer stubs, never APIs."""
import hashlib
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

from sage.autonomous.repair import ReviewStageError, validated_completion
from sage.config import REVIEW_MAX_OUTPUT_TOKENS
from sage.errors import RequestCapacityError
from sage.providers import (CHAT_OVERHEAD_RESERVE, DEEPSEEK_CONTEXT_TOKENS,
                            MODEL_PAYLOAD_LIMIT_BYTES, OpenAIConfig, OpenAIModel,
                            deepseek_tokenizer_path)


def model(*, token_count=100, **config):
    response = SimpleNamespace(choices=[SimpleNamespace(
        message=SimpleNamespace(content='{}', refusal=None), finish_reason='stop')])
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(
        create=AsyncMock(return_value=response))))
    instance = OpenAIModel(OpenAIConfig(api_key='fixture-secret',
        **({'provider': 'deepseek', 'model': 'deepseek-flash'} | config)), client=client)
    instance._tokenizer = SimpleNamespace(encode=Mock(
        return_value=SimpleNamespace(ids=range(token_count))))
    return instance


class ModelCapacityTests(unittest.IsolatedAsyncioTestCase):
    async def test_large_official_request_keeps_exact_prompt_and_wire_output(self):
        instance = model(token_count=472706)
        prompt = 'evidence\n' * 210000
        self.assertGreater(len(prompt), 1_000_000)
        measured = instance.preflight(prompt, max_tokens=32768)
        await instance.complete('fixture', prompt, max_tokens=32768)
        wire = instance._client.chat.completions.create.call_args.kwargs
        self.assertEqual(wire['messages'], [{'role': 'user', 'content': prompt}])
        self.assertEqual(wire['max_tokens'], 32768)
        self.assertNotIn('max_completion_tokens', wire)
        self.assertEqual(measured['total_reserved_tokens'], 509570)
        self.assertEqual(instance.request_count, 1)
        instance._tokenizer.encode.assert_called_once_with(prompt, add_special_tokens=False)

    def test_context_includes_output_and_chat_allowance_at_exact_boundary(self):
        available = DEEPSEEK_CONTEXT_TOKENS - 32768 - CHAT_OVERHEAD_RESERVE
        instance = model(token_count=available)
        self.assertEqual(instance.preflight('at boundary', max_tokens=32768)
                         ['total_reserved_tokens'], DEEPSEEK_CONTEXT_TOKENS)
        instance = model(token_count=available + 1)
        with self.assertRaises(RequestCapacityError) as caught:
            instance.preflight('over boundary', max_tokens=32768)
        self.assertEqual(caught.exception.reason, 'context_capacity_exceeded')
        self.assertEqual(caught.exception.diagnostic()['total_reserved_tokens'],
                         DEEPSEEK_CONTEXT_TOKENS + 1)
        self.assertFalse(caught.exception.diagnostic()['network_request'])

    def test_capacity_copies_cannot_mutate_cached_result(self):
        instance = model()
        initial = instance.preflight('same', max_tokens=20)
        initial['text_tokens'] = 0
        instance.last_request_capacity['text_tokens'] = -1
        self.assertEqual(instance.preflight('same', max_tokens=20)['text_tokens'], 100)
        instance._tokenizer.encode.assert_called_once()
        instance.preflight('same', max_tokens=21)
        self.assertEqual(instance._tokenizer.encode.call_count, 2)

    def test_unknown_profile_never_inherits_official_context(self):
        cases = ({'model': 'deepseek-v4.1-unknown'},
                 {'endpoint': 'https://custom.example/v1'},
                 {'endpoint': 'https://api.deepseek.com:444'},
                 {'endpoint': 'https://api.deepseek.com/unverified'},
                 {'provider': 'openai', 'endpoint': 'https://api.deepseek.com'})
        for config in cases:
            with self.subTest(config=config):
                instance = model(**config)
                result = instance.preflight('small request', max_tokens=12)
                self.assertIsNone(result['context_tokens'])
                self.assertIsNone(result['text_tokens'])
                with self.assertRaises(RequestCapacityError) as caught:
                    instance.preflight('x' * 1_000_001, max_tokens=12)
                self.assertEqual(caught.exception.reason, 'unknown_model_capacity')
                instance._tokenizer.encode.assert_not_called()

    def test_only_official_endpoint_variants_use_profile(self):
        for endpoint in (None, 'https://api.deepseek.com', 'https://api.deepseek.com/v1/',
                         'https://api.deepseek.com:443/v1'):
            with self.subTest(endpoint=endpoint):
                self.assertEqual(model(endpoint=endpoint).preflight('probe', max_tokens=1)
                                 ['context_tokens'], DEEPSEEK_CONTEXT_TOKENS)

    def test_payload_utf8_bytes_are_separate_from_tokens_and_characters(self):
        instance = model(token_count=1)
        # Fits the character bound but crosses the finite UTF-8 payload bound.
        prompt = '\u4e2d' * (MODEL_PAYLOAD_LIMIT_BYTES // 3 + 1)
        with self.assertRaises(RequestCapacityError) as caught:
            instance.preflight(prompt, max_tokens=1)
        self.assertEqual(caught.exception.reason, 'payload_limit_exceeded')
        self.assertEqual(caught.exception.diagnostic()['input_utf8_bytes'], len(prompt.encode()))
        instance._tokenizer.encode.assert_not_called()

    async def test_invalid_inputs_and_output_budgets_never_dispatch(self):
        instance = model()
        for prompt, tokens, reason in ((None, 1, 'invalid_prompt'), (' ', 1, 'invalid_prompt'),
             ('\ud800', 1, 'invalid_prompt'), ('x', True, 'invalid_output_budget'),
             ('x', 0, 'invalid_output_budget'), ('x', 393217, 'invalid_output_budget'),
             ('x' * (MODEL_PAYLOAD_LIMIT_BYTES + 1), 1, 'payload_limit_exceeded')):
            with self.subTest(reason=reason), self.assertRaises(RequestCapacityError) as caught:
                await instance.complete('fixture', prompt, max_tokens=tokens)
            self.assertEqual(caught.exception.reason, reason)
        self.assertEqual(instance.request_count, 0)
        instance._client.chat.completions.create.assert_not_called()

    def test_missing_asset_fails_before_sdk_initialization_without_path_leak(self):
        with tempfile.TemporaryDirectory() as directory:
            instance = OpenAIModel(OpenAIConfig(api_key='fixture-secret', provider='deepseek',
                model='deepseek-flash', deepseek_tokenizer_path=str(Path(directory) / 'private-path')))
            with patch('sage.providers.importlib.import_module') as importer:
                with self.assertRaises(RequestCapacityError) as caught:
                    instance.preflight('probe', max_tokens=1)
                importer.assert_not_called()
            self.assertEqual(caught.exception.reason, 'tokenizer_asset_missing')
            self.assertNotIn('private-path', json.dumps(caught.exception.diagnostic()))
            self.assertIsNone(instance._client)
            self.assertEqual(instance.request_count, 0)

    def test_asset_integrity_checked_before_loading_tokenizer(self):
        with tempfile.TemporaryDirectory() as directory:
            asset = Path(directory) / 'tokenizer.json'
            asset.write_text('{"malicious": "fixture-secret"}', encoding='utf-8')
            instance = model(deepseek_tokenizer_path=str(asset))
            instance._tokenizer = None
            with patch('sage.providers.importlib.import_module') as importer:
                with self.assertRaises(RequestCapacityError) as caught:
                    instance.preflight('probe', max_tokens=1)
                importer.assert_not_called()
            self.assertEqual(caught.exception.reason, 'tokenizer_asset_invalid')
            self.assertNotIn('fixture-secret', json.dumps(caught.exception.diagnostic()))

    def test_verified_json_load_is_cached_and_dependency_errors_are_sanitized(self):
        with tempfile.TemporaryDirectory() as directory:
            asset = Path(directory) / 'tokenizer.json'
            raw = b'{"fixture": true}'
            asset.write_bytes(raw)
            tokenizer = SimpleNamespace(encode=Mock(return_value=SimpleNamespace(ids=[1, 2])))
            module = SimpleNamespace(Tokenizer=SimpleNamespace(from_str=Mock(return_value=tokenizer)))
            with patch('sage.providers.DEEPSEEK_V4_TOKENIZER_SHA256', hashlib.sha256(raw).hexdigest()):
                instance = model(deepseek_tokenizer_path=str(asset))
                instance._tokenizer = None
                with patch('sage.providers.importlib.import_module', return_value=module) as importer:
                    self.assertEqual(instance.preflight('probe1', max_tokens=1)['text_tokens'], 2)
                    self.assertEqual(instance.preflight('probe2', max_tokens=1)['text_tokens'], 2)
                importer.assert_called_once_with('tokenizers')
                module.Tokenizer.from_str.assert_called_once_with(raw.decode())
                for error in (ImportError('fixture-secret'), RuntimeError('fixture-secret')):
                    instance._tokenizer = None
                    with patch('sage.providers.importlib.import_module', side_effect=error):
                        with self.assertRaises(RequestCapacityError) as caught:
                            instance.preflight('new probe', max_tokens=1)
                    self.assertEqual(caught.exception.reason, 'tokenizer_unavailable')
                    self.assertNotIn('fixture-secret', str(caught.exception))

    def test_default_cache_path_and_optional_setup_override(self):
        config = OpenAIConfig.from_env(env={'SAGE_MAIN_MODEL': 'deepseek-flash',
            'OPENAI_API_KEY': 'fixture-secret', 'SAGE_MODEL_PROVIDER': 'deepseek',
            'SAGE_DEEPSEEK_V4_TOKENIZER_PATH': '/fixture/tokenizer.json'})
        self.assertEqual(config.deepseek_tokenizer_path, '/fixture/tokenizer.json')
        self.assertEqual(deepseek_tokenizer_path(),
            Path.home() / '.cache/sage/tokenizers/deepseek-v4/tokenizer.json')
        self.assertNotIn('/fixture', repr(config))

    def test_local_error_diagnostic_contains_only_authored_text_and_counts(self):
        error = RequestCapacityError('untrusted fixture-secret', {
            'text_tokens': 'fixture-secret', 'input_characters': 100,
            'input_utf8_bytes': True, 'prompt': 'fixture-secret'})
        diagnostic = error.diagnostic()
        self.assertNotIn('fixture-secret', json.dumps(diagnostic))
        self.assertNotIn('text_tokens', diagnostic)
        self.assertNotIn('input_utf8_bytes', diagnostic)
        self.assertEqual(diagnostic['input_characters'], 100)
        self.assertFalse(diagnostic['network_request'])


class RepairCapacityTests(unittest.IsolatedAsyncioTestCase):
    async def test_local_rejection_is_not_reported_as_dispatch_or_transport_failure(self):
        instance = model(token_count=DEEPSEEK_CONTEXT_TOKENS)
        event = Mock()
        with self.assertRaises(ReviewStageError) as caught:
            await validated_completion(instance, 'scientific_review', 'fixture', lambda x: x,
                                       repairs=2, event=event)
        calls = caught.exception.details['model_calls']
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]['transport'], 'not_dispatched')
        self.assertFalse(calls[0]['network_request'])
        self.assertIsNone(calls[0]['usage'])
        self.assertEqual([x.args[0] for x in event.call_args_list], ['review_stage_local_rejected'])
        self.assertIn('text_tokens', caught.exception.details['validation_error'])
        self.assertEqual(instance.request_count, 0)
        instance._client.chat.completions.create.assert_not_called()

    async def test_format_repair_preflights_appended_response_and_stops_before_second_api(self):
        instance = model()
        instance._tokenizer.encode.side_effect = lambda text, **kwargs: SimpleNamespace(
            ids=range(1 if text == 'frozen prompt' else DEEPSEEK_CONTEXT_TOKENS))
        event = Mock()
        def invalid(value):
            raise ValueError('fixture schema failure')
        with self.assertRaises(ReviewStageError) as caught:
            await validated_completion(instance, 'scientific_review', 'frozen prompt', invalid,
                                       repairs=1, event=event)
        calls = caught.exception.details['model_calls']
        self.assertEqual([x['transport'] for x in calls], ['completed', 'not_dispatched'])
        self.assertEqual(calls[0]['validation'], 'failed')
        self.assertNotEqual(calls[0]['prompt_sha256'], calls[1]['prompt_sha256'])
        self.assertEqual(instance.request_count, 1)
        self.assertEqual(instance._tokenizer.encode.call_count, 2)
        self.assertEqual(sum(x.args[0] == 'review_model_dispatched' for x in event.call_args_list), 1)
        self.assertIn('prior_response_untrusted', instance._tokenizer.encode.call_args.args[0])

    async def test_successful_repair_events_disclose_capacity_before_dispatch(self):
        instance = model()
        event = Mock()
        result, calls = await validated_completion(instance, 'scientific_review', 'fixture',
                                                   lambda value: value, event=event)
        self.assertEqual(result, {})
        self.assertEqual(calls[0]['capacity']['status'], 'passed')
        dispatch = event.call_args_list[0]
        self.assertEqual(dispatch.args, ('review_model_dispatched',))
        self.assertEqual(dispatch.kwargs['capacity']['requested_output_tokens'], REVIEW_MAX_OUTPUT_TOKENS)

    async def test_dispatch_budget_rejection_still_prevents_api(self):
        instance = model()
        def event(name, **kwargs):
            if name == 'review_model_dispatched':
                raise ValueError('fixture budget exhausted')
        with self.assertRaisesRegex(ReviewStageError, 'budget exhausted') as caught:
            await validated_completion(instance, 'scientific_review', 'fixture', lambda x: x,
                                       event=event)
        self.assertEqual(caught.exception.details['model_calls'], [])
        self.assertEqual(instance.request_count, 0)


if __name__ == '__main__':
    unittest.main()
