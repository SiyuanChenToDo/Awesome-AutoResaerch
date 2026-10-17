"""SAGE command line. Live provider calls require a deliberate --allow-live flag."""
from __future__ import annotations
import argparse
import asyncio
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
from . import __version__
from .config import RunConfig
from .errors import SageError, ConfigurationError
from .fixtures import FixtureModel, FixtureSource
from .orchestration import run

ROOT = Path(__file__).resolve().parents[1]


def load_json(path, *, max_bytes=2_000_000):
    if path.stat().st_size > max_bytes:
        raise ConfigurationError('Input JSON exceeds size limit')
    try:
        value = json.loads(path.read_text(encoding='utf-8'))
    except (ValueError, UnicodeError):
        raise ConfigurationError('Input must be valid UTF-8 JSON') from None
    if not isinstance(value, dict):
        raise ConfigurationError('Input JSON must be an object')
    return value


def load_articles(path):
    if path is None:
        return None
    articles = load_json(path)
    for key, article in articles.items():
        if not isinstance(key, str) or not key.strip() or not isinstance(article, dict):
            raise ConfigurationError('Articles must map stable IDs/titles to article objects')
        for field in ('sections', 'references'):
            if not isinstance(article.get(field, []), list) or any(not isinstance(x, dict) for x in article.get(field, [])):
                raise ConfigurationError('Article sections and references must be lists of objects')
        for section in article.get('sections', []):
            if not isinstance(section.get('heading', ''), str) or not isinstance(section.get('text', ''), str):
                raise ConfigurationError('Article headings and text must be strings')
    return articles


def doctor():
    from .providers import OpenAIConfig
    config_errors = []
    for role in ('main', 'cheap'):
        try:
            OpenAIConfig.from_env(role=role)
        except ConfigurationError as error:
            config_errors.append(str(error))
    report = {'product': 'SAGE', 'version': __version__, 'offline_ready': True,
              'python': f'{sys.version_info.major}.{sys.version_info.minor}',
              'openai_sdk_installed': importlib.util.find_spec('openai') is not None,
              'live_configuration_errors': config_errors,
              'credential_presence': {
                  'openai_key': any(os.environ.get(k) for k in ('SAGE_OPENAI_API_KEY', 'OPENAI_API_KEY')),
                  'azure_key': any(os.environ.get(k) for k in ('SAGE_AZURE_OPENAI_KEY', 'SAGE_AZURE_OPENAI_API_KEY', 'AZURE_OPENAI_KEY', 'AZURE_OPENAI_API_KEY')),
                  'semantic_scholar_key_optional': any(os.environ.get(k) for k in ('SAGE_SEMANTIC_SCHOLAR_API_KEY', 'SEMANTIC_SCHOLAR_API_KEY', 'SEMENTIC_SEARCH_API_KEY'))},
              'live_network_tested': False, 'scientific_validation': 'not_performed'}
    report['live_configuration_ready'] = report['openai_sdk_installed'] and not config_errors
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def output_directory(path):
    # Refuse existing directories and symlink parents before any paid request.
    absolute = path.absolute()
    if any(parent.is_symlink() for parent in (absolute, *absolute.parents)):
        raise ConfigurationError('Output path must not traverse symlinks')
    if absolute.exists():
        raise ConfigurationError('Output already exists; choose a new run directory')
    absolute.mkdir(parents=True, exist_ok=False)
    return absolute


def save_result(destination, result, config):
    (destination / 'result.json').write_text(json.dumps(result.to_dict(), ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    (destination / 'config.json').write_text(json.dumps(config.to_dict(), indent=2) + '\n', encoding='utf-8')
    (destination / 'audit.jsonl').write_text(''.join(json.dumps(event, ensure_ascii=False) + '\n' for event in result.audit), encoding='utf-8')


async def execute(args, config, articles):
    models = []
    if args.mode == 'offline':
        model, source = FixtureModel(), FixtureSource()
        cheap = model
    else:
        if not args.allow_live:
            raise ConfigurationError('Live mode requires --allow-live; it sends topic/evidence to configured APIs and may incur model charges')
        from .providers import OpenAIModel, SemanticScholarSource
        model = OpenAIModel.from_env(role='main', timeout=config.request_timeout_seconds)
        cheap = OpenAIModel.from_env(role='cheap', timeout=config.request_timeout_seconds)
        if importlib.util.find_spec('openai') is None:
            raise ConfigurationError('Live mode requires the optional openai package; see README live setup')
        source = SemanticScholarSource.from_env(timeout=config.request_timeout_seconds)
        models = [model, cheap]
    destination = output_directory(args.output)
    try:
        result = await run(args.topic, model, source, cheap_model=cheap, config=config, mode=args.mode, articles=articles)
        save_result(destination, result, config)
        print(json.dumps({'product': 'SAGE', 'mode': result.mode, 'status': result.status, 'output': str(destination),
                          'candidates': len(result.candidates), 'usage': result.usage, 'validation': result.validation,
                          'scientific_validation': result.scientific_validation}, ensure_ascii=False, indent=2))
        return 0 if result.status.startswith('completed') else 1
    finally:
        for provider in models:
            await provider.aclose()


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    # Keep the original catalog/project commands and their tests as compatibility APIs.
    if argv and argv[0] in ('catalog', 'project', 'provenance'):
        filename = {'catalog': 'catalog.py', 'project': 'research.py', 'provenance': 'coi.py'}[argv[0]]
        return subprocess.call([sys.executable, str(ROOT / 'scripts' / filename), *argv[1:]])
    parser = argparse.ArgumentParser(prog='sage', description='SAGE — Scientific Agent for Grounded Exploration')
    parser.add_argument('--version', action='version', version=f'SAGE {__version__}')
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('doctor', help='Inspect local setup without network or exposing secrets')
    runner = sub.add_parser('run', help='Run the proposal pipeline with fixture or explicit live providers')
    runner.add_argument('--mode', choices=('offline', 'live'), default='offline')
    runner.add_argument('--topic', default='Synthetic SAGE offline workflow demonstration')
    runner.add_argument('--output', type=Path, default=Path('projects/sage-run'))
    runner.add_argument('--allow-live', action='store_true')
    runner.add_argument('--config', type=Path, help='JSON RunConfig overrides; never credentials')
    runner.add_argument('--articles', type=Path, help='Local article JSON by stable paper ID/title')
    for name in ('max-chain-length', 'min-chain-length', 'max-candidates', 'max-model-calls', 'max-search-calls', 'refinement-rounds'):
        runner.add_argument('--' + name, type=int, default=None)
    runner.add_argument('--publication-date', default=None, help='Inclusive DateOrYear or start:end window for all retrieval')
    for command in ('catalog', 'project', 'provenance'):
        sub.add_parser(command, help=f'Compatibility commands: sage {command} --help')
    args = parser.parse_args(argv)
    try:
        if args.command == 'doctor':
            return doctor()
        overrides = load_json(args.config) if args.config else {}
        for name in ('max_chain_length', 'min_chain_length', 'max_candidates', 'max_model_calls', 'max_search_calls', 'refinement_rounds', 'publication_date'):
            if getattr(args, name) is not None:
                overrides[name] = getattr(args, name)
        try:
            config = RunConfig(**overrides)
        except TypeError:
            raise ConfigurationError('Unknown or invalid RunConfig field') from None
        if config.request_timeout_seconds > 300:
            raise ConfigurationError('request_timeout_seconds must not exceed 300')
        return asyncio.run(execute(args, config, load_articles(args.articles)))
    except (SageError, OSError, ValueError) as error:
        # OSError strings may contain sensitive paths; only our safe error messages surface.
        message = str(error) if isinstance(error, SageError) else 'Local input/output operation failed'
        print(f'SAGE error: {message}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
