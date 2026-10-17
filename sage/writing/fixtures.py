"""Offline report responses, not research prose or scientific findings."""
from collections import Counter, deque
import json
from ..errors import ProviderError
from ..review.report import RANGES
from .prompts import SECTIONS


def fixture_responses():
    review = {'summary': 'Synthetic fixture review of a software workflow.',
              'strengths': ['The evidence boundary is explicit.'],
              'weaknesses': ['Scientific validation remains unperformed.'],
              'questions': ['What independent evaluation is appropriate?'],
              'limitations': ['Synthetic data cannot establish research effectiveness.'],
              'ethical_concerns': False, 'requires_revision': True,
              'ratings': {name: min(3, maximum) for name, maximum in RANGES.items()}}
    return {'writing.scaffold': '<sections>' + json.dumps(SECTIONS) + '</sections>',
            'writing.section': '<section>' + json.dumps({'commentary': 'Synthetic draft commentary: the proposed study needs independent evidence review.', 'citation_ids': []}) + '</section>',
            'review.report': '<review>' + json.dumps(review) + '</review>',
            'writing.revise': '<edits>' + json.dumps([{'section_id': 'discussion', 'commentary': 'Synthetic revised commentary: preserve failed attempts and obtain independent confirmation before drawing research conclusions.', 'citation_ids': []}]) + '</edits>'}


class FixtureReportModel:
    def __init__(self, *, overrides=None):
        self.calls = Counter()
        self.overrides = {stage: deque(values) for stage, values in (overrides or {}).items()}

    async def complete(self, stage, prompt, *, max_tokens):
        self.calls[stage] += 1
        if self.overrides.get(stage):
            value = self.overrides[stage].popleft()
            if isinstance(value, BaseException):
                raise value
            return value
        responses = fixture_responses()
        if stage not in responses:
            raise ProviderError('Report fixture has no response for requested stage')
        if stage == 'review.report' and self.calls[stage] > 1:
            review = json.loads(responses[stage][len('<review>'):-len('</review>')])
            review['ratings']['overall'] = 4
            review['requires_revision'] = False
            return '<review>' + json.dumps(review) + '</review>'
        return responses[stage]
