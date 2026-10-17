# Derived from CoI-Agent DeepResearchAgent chain/extraction methods, Apache-2.0.
# MODIFIED for SAGE 2026-10-17: named evidence, bounded graph traversal, scope labels.
# Source and modification map: NOTICE.md and docs/sage-migration.md.
"""Read evidence and traverse forward citations and backward references."""
from __future__ import annotations
import json
from ..errors import InvalidResponse, NoEvidence
from ..runtime import string_list
from ..types import Evidence, Chain, paper_record
from .prompts import get_deep_reference_prompt, get_deep_judge_relevant_prompt


def paper_content(paper):
    lines = [f'Evidence scope: {paper.evidence_scope}', f'Paper ID: {paper.paper_id}',
             f'Source: {paper.url}', f'Title: {paper.title}', f'Abstract: {paper.abstract}']
    if paper.article:
        # User-provided article JSON follows the upstream sections/references shape.
        for section in paper.article.get('sections', []):
            lines.append(f"Section: {section.get('heading', '')}\n{section.get('text', '')}\nReference IDs: {section.get('publication_ref', [])}")
        lines.append('<References>')
        for reference in paper.article.get('references', []):
            lines.append(json.dumps(reference, ensure_ascii=False))
        lines.append('</References>')
    else:
        lines.append('FULL TEXT UNAVAILABLE. Do not infer unprovided experimental details or references.')
    return '\n'.join(lines)


class Literature:
    def __init__(self, runtime, discovery):
        self.runtime, self.discovery = runtime, discovery

    async def extract(self, paper, topic):
        response = await self.runtime.ask('literature.extract', get_deep_reference_prompt(paper_content(paper), topic),
                                          ('idea', 'experiment', 'entities', 'references'), cheap=True,
                                          validate=lambda r: string_list(r['references'], self.runtime.config.max_related))
        self.runtime.event('literature.evidence', 'extracted', paper=paper_record(paper), extraction=dict(response))
        return Evidence(paper=paper, idea=response['idea'], experiment=response['experiment'], entities=response['entities'],
                        references=string_list(response['references'], self.runtime.config.max_related))

    async def relevant(self, paper, topic):
        def validate(response):
            if response['relevant'] not in ('0', '1'):
                raise InvalidResponse('Relevance must be 0 or 1')
        response = await self.runtime.ask('literature.relevance', get_deep_judge_relevant_prompt(paper.title, paper.abstract, topic),
                                          ('relevant',), validate=validate)
        return response['relevant'] == '1'

    async def build_chain(self, anchor, topic):
        first = await self.extract(anchor, topic)
        evidence, seen, reasons = [first], {anchor.paper_id, anchor.title.casefold()}, []
        maximum = self.runtime.config.max_chain_length
        current = anchor
        # Preserve CoI's forward-first traversal, then fill gaps from references.
        for _ in range(maximum - 1):
            candidates = await self.discovery.related(current, topic, 'citations', exclude=seen)
            chosen = None
            for paper in candidates:
                seen.update((paper.paper_id, paper.title.casefold()))
                if await self.relevant(paper, topic):
                    chosen = await self.extract(paper, topic)
                    break
            if chosen is None:
                reasons.append('forward_exhausted_or_irrelevant')
                break
            evidence.append(chosen)
            current = chosen.paper
            if len(evidence) >= maximum:
                break
        current, references = anchor, list(first.references)
        for _ in range(maximum - len(evidence)):
            chosen = None
            while references:
                reference = references.pop(0)
                if reference.casefold() in seen:
                    continue
                candidates = await self.discovery.search(reference, limit=1, exclude=seen)
                for paper in candidates:
                    seen.update((paper.paper_id, paper.title.casefold()))
                    if await self.relevant(paper, topic):
                        chosen = await self.extract(paper, topic)
                        break
                if chosen:
                    break
            if chosen is None:
                candidates = await self.discovery.related(current, topic, 'references', exclude=seen)
                for paper in candidates:
                    seen.update((paper.paper_id, paper.title.casefold()))
                    if await self.relevant(paper, topic):
                        chosen = await self.extract(paper, topic)
                        break
            if chosen is None:
                reasons.append('backward_exhausted_or_irrelevant')
                break
            evidence.insert(0, chosen)
            references = list(chosen.references)
            current = chosen.paper
        if len(evidence) < self.runtime.config.min_chain_length:
            self.runtime.event('literature.chain', 'insufficient_evidence', anchor_id=anchor.paper_id, paper_ids=[e.paper.paper_id for e in evidence])
            raise NoEvidence('Retrieved chain is shorter than min_chain_length')
        if len(evidence) >= maximum:
            reasons.append('max_chain_length')
        return Chain(evidence=evidence, trend='', entities='', stop_reasons=reasons)
