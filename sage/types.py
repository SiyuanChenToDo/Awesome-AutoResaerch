"""Named SAGE contracts: generated proposals are never measured research results."""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import Any, Literal, Protocol


@dataclass(frozen=True)
class Paper:
    paper_id: str
    title: str
    abstract: str = ""
    year: int | None = None
    url: str = ""
    citation_count: int | None = 0
    article: dict[str, Any] | None = None
    evidence_scope: str = "abstract_only"
    publication_date: str | None = None
    authors: tuple[str, ...] = ()
    source_provider: str = "unspecified"


@dataclass(frozen=True)
class Evidence:
    paper: Paper
    idea: str
    experiment: str
    entities: str
    references: list[str]
    capsule: dict[str, Any] = field(default_factory=dict)


@dataclass
class Chain:
    evidence: list[Evidence]
    trend: str
    entities: str
    stop_reasons: list[str] = field(default_factory=list)
    relation: str = "citation_reference"

    @property
    def text(self) -> str:
        prefix = ("TOPIC/TIME CHAIN: chronological thematic comparison only; no citation, reference, "
                  "influence or historical dependency edges were retrieved. Do not claim one paper builds on another.\n"
                  if self.relation == "topic_time" else "")
        import json
        return prefix + "\n\n".join(f"{i}.Paper:{e.paper.title} date:{e.paper.publication_date} " +
                                      ('Evidence capsule: ' + json.dumps(e.capsule, ensure_ascii=False) if e.capsule else f'idea:{e.idea}')
                                      for i, e in enumerate(self.evidence))


@dataclass(frozen=True)
class NoveltyAssessment:
    status: Literal["not_established", "similar_work_found", "no_similar_work_found"]
    searched_queries: list[str]
    compared_papers: list[Paper]
    summary: str
    similar_paper_id: str | None = None
    basis: str = "model_assessment_of_retrieved_sources"
    comparisons: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class Candidate:
    idea: str
    chain: Chain
    future: str
    human_considerations: str
    novelty: NoveltyAssessment
    rejected_attempts: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class ExperimentPlan:
    proposal: str
    revisions: list[dict[str, Any]] = field(default_factory=list)
    status: str = "proposal_only"
    design_contract: dict[str, Any] = field(default_factory=dict)


@dataclass
class RunResult:
    topic: str
    mode: str
    status: str = "running"
    candidates: list[Candidate] = field(default_factory=list)
    selected_index: int | None = None
    ranking: dict[str, Any] = field(default_factory=dict)
    experiment: ExperimentPlan | None = None
    audit: list[dict[str, Any]] = field(default_factory=list)
    usage: dict[str, Any] = field(default_factory=dict)
    errors: list[dict[str, str]] = field(default_factory=list)
    validation: dict[str, Any] = field(default_factory=dict)
    execution_status: str = "not_implemented"
    writing_status: str = "not_implemented"
    scientific_validation: str = "not_performed"
    schema_version: str = "sage.run.v1"
    discussion: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class LanguageModel(Protocol):
    async def complete(self, stage: str, prompt: str, *, max_tokens: int) -> str: ...


class PaperSource(Protocol):
    async def search(self, query: str, *, limit: int, publication_date: str | None = None) -> list[Paper]: ...
    async def related(self, paper: Paper, *, direction: str, limit: int) -> list[Paper]: ...


def paper_record(paper: Paper) -> dict[str, Any]:
    """Retrieval evidence without an unbounded duplicate of attached full text."""
    record = {name: getattr(paper, name) for name in ('paper_id', 'title', 'abstract', 'year', 'url', 'evidence_scope', 'publication_date')}
    if paper.authors or paper.source_provider != 'unspecified':
        record['authors'] = list(paper.authors)
        record['source_provider'] = paper.source_provider
    return record
