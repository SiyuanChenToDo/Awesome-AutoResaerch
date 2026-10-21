# Derived from CoI-Agent DeepResearchAgent.deep_research_paper_with_chain, Apache-2.0.
# MODIFIED for SAGE 2026-10-17: separated synthesis and bounded novelty regeneration.
# Source and modification map: NOTICE.md and docs/sage-migration.md.
"""Synthesize chain trends and produce auditable, explicitly unverified ideas."""
from __future__ import annotations
from ..types import Candidate, paper_record
from .prompts import (get_deep_trend_idea_chains_prompt, get_deep_generate_future_direciton_prompt,
                      get_deep_generate_idea_prompt, get_deep_final_idea_prompt)


class Ideation:
    def __init__(self, runtime, review):
        self.runtime, self.review = runtime, review

    async def generate(self, chain, topic, *, lens=None):
        import json
        rich = self.runtime.config.evidence_mode == 'capsule'
        entities = [e.entities for e in chain.evidence]
        trend_prompt = get_deep_trend_idea_chains_prompt(chain.text, entities, topic)
        if chain.relation == 'topic_time':
            trend_prompt = (f'Topic: {topic}. Compare these dated, thematically retrieved source-scoped evidence cards: {chain.text}. '
                            f'Entities: {entities}. Describe similarities, differences and evidence gaps only. '
                            'No citation graph was retrieved; do not assert influence, causal progression, '
                            'or that one paper builds on another. Output <trend>comparison</trend>.')
        response = await self.runtime.ask('ideation.trend', trend_prompt, ('trend',))
        chain.trend = response['trend']
        prompt = f'Topic: {topic}. Merge, simplify and deduplicate these source-grounded entities: {entities}. Output <entities>cleaned entities</entities>.'
        response = await self.runtime.ask('ideation.entities', prompt, ('entities',))
        chain.entities = response['entities']
        rejected = []
        for attempt in range(self.runtime.config.novelty_attempts):
            future_prompt = get_deep_generate_future_direciton_prompt(chain.text, chain.trend, topic, chain.entities)
            if rich:
                future_prompt = (f'Topic: {topic}. Evidence cards: {chain.text}\nComparison: {chain.trend}\n'
                    'Identify 2-3 specific unresolved mechanisms or failures grounded in source excerpts. '
                    'Distinguish author-stated limitations from your inferred gaps and unobserved details. '
                    'Absence from a read chunk is not absence from the paper or literature. '
                    'Output <future>bounded directions with source IDs</future><human>alternative explanations and decisive controls</human>.')
            future = await self.runtime.ask('ideation.future', future_prompt,
                                            ('future', 'human'))
            method_prompt = get_deep_generate_idea_prompt(chain.text, chain.trend, topic, chain.entities, future['future'], rejected)
            if rich:
                method_prompt = (f'Topic: {topic}\nEvidence: {chain.text}\nDirections: {future["future"]}\n'
                    f'Rejected attempts: {json.dumps(rejected)}\n'
                    'Develop ONE implementable research idea. Specify inputs/outputs, mechanism or equation, '
                    'why it addresses the evidenced bottleneck, closest baseline and actual technical difference. '
                    'New mechanism and new evaluation contribution are both allowed; label which you propose. '
                    'Give a minimal falsification experiment, capacity/compute controls, implementation risks. '
                    'No invented numerical findings, novelty proof or unsupported paper details. '
                    'Output <method>steps and test</method><novelty>claimed delta, unverified</novelty>'
                    '<motivation>source IDs, gap versus inference</motivation>.')
            if lens:
                method_prompt += '\nAssigned analytic lens: ' + lens + '. Keep the same evidence standard; seek a distinct falsifiable hypothesis, not merely different wording.'
                self.runtime.event('ideation.lens', 'assigned', lens=lens)
            raw = await self.runtime.ask('ideation.generate', method_prompt,
                                         ('method', 'novelty', 'motivation'))
            final_prompt = get_deep_final_idea_prompt(chain.text, chain.trend, raw, topic)
            if rich:
                final_prompt = (f'Topic: {topic}\nSource evidence: {chain.text}\nProposed idea: {json.dumps(raw)}\n'
                    'Return <final_idea>one concise idea card</final_idea>, at most 650 words. Include '
                    'Title; Problem; Source-grounded gap (with supplied paper/chunk IDs); Proposed mechanism '
                    '(inputs, outputs, key equation or steps); Closest baseline and claimed difference; '
                    'Falsifiable prediction; Minimal experiment and matched controls; Risks and missing evidence. '
                    'Clearly separate paper claims from your proposal. Do not convert missing text into novelty '
                    'or extend author-reported numerical results. No generic research agenda or fabricated citations.')
            final = await self.runtime.ask('ideation.finalize', final_prompt, ('final_idea',))
            assessment = await self.review.novelty(final['final_idea'], topic)
            candidate = Candidate(final['final_idea'], chain, future['future'], future['human'], assessment, list(rejected))
            if assessment.status != 'similar_work_found':
                return candidate
            rejected.append({'attempt': attempt + 1, 'idea': final['final_idea'], 'summary': assessment.summary,
                             'similar_paper_id': assessment.similar_paper_id, 'queries': assessment.searched_queries,
                             'compared_papers': [paper_record(p) for p in assessment.compared_papers]})
            self.runtime.event('ideation.regenerate', 'overlapping_prior_work', attempt=attempt + 1)
        candidate.rejected_attempts = rejected
        self.runtime.event('ideation.regenerate', 'attempt_limit', attempts=len(rejected))
        return candidate
