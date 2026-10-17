"""Bounded report drafts and deterministic execution-evidence rendering."""
from .report import EvidenceWriter, generate_report, render_markdown, render_draft_markdown
from .fixtures import FixtureReportModel, fixture_responses

__all__ = ['EvidenceWriter', 'generate_report', 'render_markdown', 'render_draft_markdown',
           'FixtureReportModel', 'fixture_responses']
