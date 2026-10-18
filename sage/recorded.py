"""Explicit fixed real-paper corpus for controlled/recovery validation, never fresh search."""
from dataclasses import fields
import hashlib
import json
from pathlib import Path
import re
from .types import Paper
from .errors import ConfigurationError


class RecordedPaperSource:
    chain_relation='topic_time'
    fresh_search=False
    query_instructions='Search within the supplied fixed paper corpus using short technical terms. No fresh internet search occurs.'
    prompt_policy='This is a fixed previously retrieved real-paper corpus. No current or exhaustive literature search occurred; global novelty is unknown.\n'

    def __init__(self,path):
        data=Path(path).read_bytes()
        if len(data)>20_000_000:raise ConfigurationError('Recorded corpus exceeds input limit')
        self.corpus_sha256=hashlib.sha256(data).hexdigest()
        try:
            value=json.loads(data)
            if value['schema_version']!='sage.paper_corpus.v1' or not 1<=len(value['papers'])<=100:
                raise ValueError
            self.provenance=value['provenance']
            if not isinstance(self.provenance,dict):raise ValueError
            allowed={f.name for f in fields(Paper)}
            self.papers=[]
            for row in value['papers']:
                if not isinstance(row,dict) or not set(row)<=allowed or not isinstance(row.get('paper_id'),str) or not isinstance(row.get('title'),str):raise ValueError
                row={**row,'authors':tuple(row.get('authors',[])),'evidence_scope':'recorded_'+row.get('evidence_scope','abstract_only')}
                self.papers.append(Paper(**row))
        except (ValueError,KeyError,TypeError):
            raise ConfigurationError('Invalid fixed real-paper corpus') from None

    async def search(self,query,*,limit,publication_date=None):
        terms=set(re.findall(r'[a-z0-9]+',query.lower()))-{'the','and','for','with','in','of'}
        ranked=[]
        for p in self.papers:
            words=set(re.findall(r'[a-z0-9]+',(p.title+' '+p.abstract).lower()))
            score=len(words&terms)
            if score:ranked.append((score,p))
        return [p for _,p in sorted(ranked,key=lambda r:(-r[0],r[1].paper_id))][:limit]

    async def topic_related(self,paper,*,limit,publication_date=None):
        return [p for p in await self.search(paper.title,limit=len(self.papers)) if p.paper_id!=paper.paper_id][:limit]

    def relax_queries(self,query):
        words=query.split()
        return [' '.join(words[:4]),' '.join(words[:2])]
