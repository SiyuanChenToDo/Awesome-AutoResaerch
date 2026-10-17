"""SAGE limits are explicit and validated before any provider is contacted."""
from dataclasses import dataclass, asdict
import math
from .errors import ConfigurationError


@dataclass(frozen=True)
class RunConfig:
    max_chain_length: int = 4
    min_chain_length: int = 2
    max_candidates: int = 2
    max_queries: int = 3
    search_rewrites: int = 2
    max_related: int = 6
    novelty_attempts: int = 2
    refinement_rounds: int = 1
    retry_attempts: int = 2
    max_model_calls: int = 120
    max_search_calls: int = 60
    max_tokens_per_call: int = 2000
    max_reserved_output_tokens: int = 240000
    request_timeout_seconds: float = 45.0
    max_wall_seconds: float = 600.0
    max_prompt_chars: int = 100000
    max_response_chars: int = 100000
    publication_date: str | None = None
    discussion_mode: str = "none"
    discussion_students: int = 2
    discussion_rounds: int = 1
    discussion_prompt_version: str = "v2"
    evidence_mode: str = "legacy"
    paper_text_mode: str = "provided"
    rerank_mode: str = "auto"
    novelty_search_rewrites: int = 0
    capsule_chunk_chars: int = 7000
    capsule_max_chunks: int = 8
    capsule_max_claims: int = 18
    capsule_max_chars: int = 12000
    novelty_fulltext_papers: int = 0
    citation_policy: str = 'required'

    def __post_init__(self):
        if self.discussion_mode not in ('none', 'hybrid') or self.discussion_prompt_version not in ('v1', 'v2', 'v3'):
            raise ConfigurationError('Invalid discussion mode or prompt version')
        if self.evidence_mode not in ('legacy', 'capsule') or self.paper_text_mode not in ('provided', 'arxiv'):
            raise ConfigurationError('Invalid evidence or paper text mode')
        if self.rerank_mode not in ('auto', 'model', 'semantic', 'lexical'):
            raise ConfigurationError('Invalid rerank mode')
        if self.citation_policy not in ('required', 'prefer'):
            raise ConfigurationError('Invalid citation policy')
        bounds = {'novelty_search_rewrites': (0, 4), 'capsule_chunk_chars': (1000, 16000),
                  'capsule_max_chunks': (1, 20), 'capsule_max_claims': (1, 40),
                  'capsule_max_chars': (2000, 30000), 'novelty_fulltext_papers': (0, 5)}
        for name, (low, high) in bounds.items():
            value = getattr(self, name)
            if type(value) is not int or not low <= value <= high:
                raise ConfigurationError(f'{name} outside supported range')
        if type(self.discussion_students) is not int or not 2 <= self.discussion_students <= 4:
            raise ConfigurationError('discussion_students must be between 2 and 4')
        if type(self.discussion_rounds) is not int or not 1 <= self.discussion_rounds <= 3:
            raise ConfigurationError('discussion_rounds must be between 1 and 3')
        positive = ('max_chain_length', 'min_chain_length', 'max_candidates', 'max_queries',
                    'max_related', 'novelty_attempts', 'retry_attempts', 'max_model_calls',
                    'max_search_calls', 'max_tokens_per_call', 'max_reserved_output_tokens',
                    'max_prompt_chars', 'max_response_chars')
        for name in positive:
            value = getattr(self, name)
            if type(value) is not int or value < 1:
                raise ConfigurationError(f'{name} must be a positive integer')
        if self.discussion_mode == 'hybrid' and self.max_candidates < self.discussion_students:
            raise ConfigurationError('Hybrid requires max_candidates >= discussion_students')
        for name in ('search_rewrites', 'refinement_rounds'):
            value = getattr(self, name)
            if type(value) is not int or value < 0:
                raise ConfigurationError(f'{name} must be a nonnegative integer')
        if self.max_tokens_per_call > 65536 or self.max_prompt_chars > 250000:
            raise ConfigurationError('Model token/prompt limit exceeds provider capacity')
        if self.max_related > 100:
            raise ConfigurationError('max_related exceeds provider limit 100')
        if self.publication_date is not None:
            from .dates import publication_window
            publication_window(self.publication_date)
        if self.min_chain_length > self.max_chain_length:
            raise ConfigurationError('min_chain_length exceeds max_chain_length')
        for name in ('request_timeout_seconds', 'max_wall_seconds'):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
                raise ConfigurationError(f'{name} must be positive and finite')
        if self.request_timeout_seconds > 300:
            raise ConfigurationError('request_timeout_seconds exceeds provider limit 300')
        if self.max_candidates > 20 or self.max_chain_length > 30 or self.max_queries > 20 or self.retry_attempts > 5:
            raise ConfigurationError('candidate, chain, query or retry hard limit exceeded')

    def to_dict(self):
        return asdict(self)


def profile_overrides(name):
    """Explicit quality profile; keep small/offline compatibility defaults affordable."""
    if name == 'standard':
        return {}
    if name != 'research':
        raise ConfigurationError('Unknown research profile')
    return dict(evidence_mode='capsule', paper_text_mode='arxiv', rerank_mode='semantic',
                novelty_fulltext_papers=2, citation_policy='prefer',
                novelty_search_rewrites=2, max_candidates=4, max_chain_length=5,
                min_chain_length=3, max_queries=4, max_related=12,
                discussion_mode='hybrid', discussion_students=4, discussion_rounds=2,
                discussion_prompt_version='v3', max_model_calls=400,
                max_search_calls=160, max_wall_seconds=3600,
                max_tokens_per_call=4000, max_reserved_output_tokens=1600000,
                max_prompt_chars=180000)
