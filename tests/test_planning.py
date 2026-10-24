import asyncio
import json
import threading
import unittest
from unittest.mock import AsyncMock, patch
from sage.planning import Planner, PlanningError, validate_request, validate_response, model_question

def payload(i='request_1234567890', **kw):
    return dict(request_id=i, seed='LLM 数学创造力', turns=[], allow_live=True, **kw)

def response():
    return {'question':{'title':'如何干预关系表示？','hint':'区分解释','options':[{'label':'开放权重模型','detail':'检查激活'}]},'summary':'目标已明确，资源未定','ready':False}

class PlanningTests(unittest.TestCase):
    def test_context_and_deduplication_and_opt_in(self):
        seen=[]
        async def ask(data):
            seen.append(data)
            return validate_response(json.dumps(response()))
        planner=Planner(ask)
        obj=payload();obj['turns']=[{'question':'模型是否可访问？','answer':'只有 API','skipped':False}]
        result=planner.step('alice',obj)
        self.assertEqual(seen[0]['conversation'][0]['answer'],'只有 API')
        self.assertEqual(planner.step('alice',obj),result);self.assertEqual(len(seen),1)
        changed=dict(obj,seed='different')
        with self.assertRaises(PlanningError):planner.step('alice',changed)
        with self.assertRaises(PlanningError):planner.step('bob',dict(obj,allow_live=False))
        self.assertEqual(len(seen),1)
        planner.step('bob',obj);self.assertEqual(len(seen),2)

    def test_failure_is_cached_redacted_and_counts_against_budget(self):
        async def fail(_):raise RuntimeError('secret-key-not-for-user')
        planner=Planner(fail)
        for _ in range(2):
            with self.assertRaises(PlanningError) as ctx:planner.step('a',payload())
            self.assertNotIn('secret',str(ctx.exception))
        self.assertEqual(len(planner.calls),1)
        for i in range(29):
            with self.assertRaises(PlanningError):planner.step('a',payload('unique_request_id_'+str(i)))
        with self.assertRaises(PlanningError) as ctx:planner.step('a',payload('another_request_id'))
        self.assertEqual(ctx.exception.status,429)
        self.assertEqual(len(planner.calls),30)

    def test_concurrent_calls_for_same_account_do_not_double_spend(self):
        started=threading.Event();release=threading.Event()
        async def ask(_):
            started.set()
            await asyncio.to_thread(release.wait)
            return response()
        planner=Planner(ask);thread=threading.Thread(target=lambda:planner.step('a',payload()));thread.start()
        self.assertTrue(started.wait(3))
        try:
            with self.assertRaises(PlanningError) as ctx:planner.step('a',payload())
            self.assertEqual(ctx.exception.status,429)
            self.assertEqual(len(planner.calls),1)
        finally:release.set();thread.join(3)

    def test_limits_and_schema(self):
        for change in [{'seed':'x'*2001},{'turns':[{'question':'q','answer':'a','skipped':False}]*12},{'turns':[{'question':'q','answer':'','skipped':False}]},{'request_id':'x'}]:
            with self.assertRaises(PlanningError):validate_request(dict(payload(),**change))
        self.assertEqual(len(validate_response(json.dumps(response()))['question']['options']),1)
        for bad in ['not json','[]','{}',json.dumps(dict(response(),ready='yes'))]:
            with self.assertRaises(PlanningError):validate_response(bad)

    def test_provider_receives_data_closes_and_preserves_usage(self):
        model=type('Model',(),{})()
        model.complete=AsyncMock(return_value=json.dumps(response()))
        model.aclose=AsyncMock()
        model.last_usage={'prompt_tokens':123,'completion_tokens':45,'total_tokens':168}
        data={'topic':'untrusted <script>','conversation':[{'question':'q','answer':'change direction','skipped':False}]}
        with patch('sage.providers.OpenAIModel.from_env',return_value=model):
            result=asyncio.run(model_question(data))
        prompt=model.complete.call_args.args[1]
        self.assertIn('change direction',prompt);self.assertIn('untrusted <script>',prompt)
        model.aclose.assert_awaited_once()
        self.assertEqual(result['usage']['total_tokens'],168)

if __name__=='__main__':unittest.main()
