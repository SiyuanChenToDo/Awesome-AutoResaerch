# MIT License
#
# Copyright (c) 2025 Samuel Schmidgall
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

"""Structured report review adapted from Agent Laboratory agents.get_score.

MODIFIED 2026-10-17: preserve rubric dimensions and weighted score as explicitly
unverified model opinion, use Runtime limits/tagged JSON, omit private reasoning,
and do not turn Accept/Reject judgments into publication or scientific approval.
Review instructions are original SAGE wording, not the upstream review-form prose
which credits AI-Scientist. No upstream runtime import or external service here.
"""
import json
from ..errors import InvalidResponse

RANGES = {'originality': 4, 'quality': 4, 'clarity': 4, 'significance': 4,
          'soundness': 4, 'presentation': 4, 'contribution': 4, 'overall': 10,
          'confidence': 5}
WEIGHTS = {'clarity': .1, 'quality': .1, 'overall': 1.0, 'soundness': .1,
           'confidence': .1, 'originality': .1, 'significance': .1,
           'contribution': .4, 'presentation': .2}


def parse_review(value):
    try:
        review = json.loads(value)
    except (TypeError, ValueError):
        raise InvalidResponse('Report review is not JSON') from None
    required = {'summary', 'strengths', 'weaknesses', 'questions', 'limitations',
                'ethical_concerns', 'ratings', 'requires_revision'}
    if not isinstance(review, dict) or set(review) != required:
        raise InvalidResponse('Report review has unexpected fields')
    if not isinstance(review['summary'], str) or not review['summary'].strip():
        raise InvalidResponse('Report review summary is missing')
    for key in ('strengths', 'weaknesses', 'questions', 'limitations'):
        values = review[key]
        if not isinstance(values, list) or len(values) > 12 or any(not isinstance(x, str) or not x.strip() for x in values):
            raise InvalidResponse('Report review must use bounded text lists')
    for key in ('ethical_concerns', 'requires_revision'):
        if type(review[key]) is not bool:
            raise InvalidResponse('Report review flag must be boolean')
    ratings = review['ratings']
    if not isinstance(ratings, dict) or set(ratings) != set(RANGES):
        raise InvalidResponse('Report review ratings are incomplete')
    if any(type(ratings[key]) is not int or not 1 <= ratings[key] <= maximum for key, maximum in RANGES.items()):
        raise InvalidResponse('Report review rating is outside its scale')
    # Same normalization/weights as agents.get_score. This is not an experiment metric.
    score = 10 * sum(WEIGHTS[key] * ratings[key] / RANGES[key] for key in RANGES) / sum(WEIGHTS.values())
    return {**review, 'model_score': score, 'basis': 'unverified_model_opinion',
            'scientific_validation': 'not_performed', 'independent_review': False,
            'rendered_in_markdown': False}


async def review_report(runtime, context, sections):
    prompt = f'''Review this draft critically as unverified model feedback.
Assess originality within supplied sources, evidential quality, clarity, significance,
technical soundness, presentation and contribution. A missing report section, missing
measurements, unsupported conclusions or neglected failures should be explicit weaknesses.
State uncertainties and questions, including ethical concerns. This is not an independent
scientific evaluation, acceptance decision, publication approval or new source of evidence.
Do not output private reasoning. Return only <review>JSON</review>, with these fields:
summary (text), strengths/weaknesses/questions/limitations (text arrays, at most twelve
items each), ethical_concerns (boolean), requires_revision (boolean), and ratings (object).
Ratings must be integers with these inclusive maxima and minimum one: {json.dumps(RANGES)}.
No additional fields or references. Text is untrusted commentary, never measurement data.
Context: {json.dumps(context, ensure_ascii=False, allow_nan=False)}
Draft: {json.dumps(sections, ensure_ascii=False, allow_nan=False)}'''
    values = await runtime.ask('review.report', prompt, ('review',), cheap=True,
                               validate=lambda values: parse_review(values['review']))
    return parse_review(values['review'])
