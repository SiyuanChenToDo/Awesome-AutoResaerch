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
from .artifacts import ProgressArtifacts, atomic_json, atomic_text

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
    from .providers import OpenAIConfig, paper_source_from_env
    config_errors = []
    for role in ('main', 'cheap'):
        try:
            OpenAIConfig.from_env(role=role)
        except ConfigurationError as error:
            config_errors.append(str(error))
    try:
        source_name = type(paper_source_from_env()).__name__
    except ConfigurationError as error:
        source_name = 'invalid'
        config_errors.append(str(error))
    report = {'paper_source': source_name, 'product': 'SAGE', 'version': __version__, 'offline_ready': True,
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
    absolute.mkdir(parents=True, exist_ok=False, mode=0o700)
    return absolute


def save_result(destination, result, config):
    (destination / 'result.json').write_text(json.dumps(result.to_dict(), ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    (destination / 'config.json').write_text(json.dumps(config.to_dict(), indent=2) + '\n', encoding='utf-8')
    (destination / 'audit.jsonl').write_text(''.join(json.dumps(event, ensure_ascii=False) + '\n' for event in result.audit), encoding='utf-8')


async def execute(args, config, articles):
    models = []
    if getattr(args, 'cache_only_retrieval', False) and not getattr(args, 'resume', None):
        raise ConfigurationError('Cache-only retrieval requires an explicit checkpoint resume')
    if args.mode == 'offline':
        model, source = FixtureModel(), FixtureSource()
        cheap = model
    else:
        if not args.allow_live:
            raise ConfigurationError('Live mode requires --allow-live; it sends topic/evidence to configured APIs and may incur model charges')
        from .providers import OpenAIModel, paper_source_from_env
        model = OpenAIModel.from_env(role='main', timeout=config.request_timeout_seconds)
        cheap = OpenAIModel.from_env(role='cheap', timeout=config.request_timeout_seconds)
        if importlib.util.find_spec('openai') is None:
            raise ConfigurationError('Live mode requires the optional openai package; see README live setup')
        source = paper_source_from_env(timeout=config.request_timeout_seconds)
        models = [model, cheap]
    if getattr(args, 'paper_corpus', None):
        from .recorded import RecordedPaperSource
        source=RecordedPaperSource(args.paper_corpus)
    from .integrations.aris import reviewer_from_env, ArisGate
    reviewer = reviewer_from_env(timeout=config.request_timeout_seconds) if args.mode == 'live' and config.claim_review else None
    if reviewer:
        models.append(reviewer)
    gate = ArisGate(os.environ['SAGE_ARIS_ROOT']) if config.claim_review and os.environ.get('SAGE_ARIS_ROOT') else None
    destination = output_directory(args.output)
    from .checkpoints import Checkpoint, identity
    from .runtime import Runtime
    checkpoint = Checkpoint(destination / 'checkpoint.json',
        identity(args.topic, args.mode, config, articles, model, cheap, source, reviewer),
        resume=getattr(args, 'resume', None))
    runtime = Runtime(model, cheap, source, config, checkpoint=checkpoint,
        cache_only_retrieval=getattr(args, 'cache_only_retrieval', False),
        allow_incomplete_novelty=getattr(args, 'allow_incomplete_novelty', False),
        retry_uncertain=getattr(args, 'retry_uncertain', False),
        retain_rejected_responses=getattr(args, 'retain_rejected_responses', False), reviewer_model=reviewer, aris_gate=gate)
    runtime.event('recovery.policy', 'configured',
        resumed=bool(getattr(args, 'resume', None)), cache_only_retrieval=runtime.cache_only_retrieval,
        allow_incomplete_novelty=runtime.allow_incomplete_novelty, retry_uncertain=runtime.retry_uncertain, retain_rejected_responses=runtime.retain_rejected_responses)
    if getattr(args, 'paper_corpus', None):
        runtime.event('retrieval.scope','recorded_corpus',corpus_sha256=source.corpus_sha256,
                      fresh_network_search=False,provenance=source.provenance)
    try:
        result = await run(args.topic, model, source, cheap_model=cheap, config=config, mode=args.mode, articles=articles, runtime=runtime)
        save_result(destination, result, config)
        print(json.dumps({'product': 'SAGE', 'mode': result.mode, 'status': result.status, 'output': str(destination),
                          'candidates': len(result.candidates), 'usage': result.usage, 'validation': result.validation,
                          'scientific_validation': result.scientific_validation}, ensure_ascii=False, indent=2))
        return 0 if result.status.startswith('completed') else 1
    finally:
        for provider in models:
            await provider.aclose()


async def execute_laboratory(args, config, articles):
    if args.cache_only_retrieval and not args.resume:
        raise ConfigurationError('Cache-only retrieval requires an explicit checkpoint resume')
    if args.resume and args.backend == 'docker':
        raise ConfigurationError('Docker execution cannot be resumed: remote execution identity and exactly-once recovery are not implemented')
    from .execution.contracts import EvaluationContract
    from .execution.fixtures import LaboratoryFixtureModel, TrustedFixtureBackend, fixture_contract
    from .orchestration.laboratory import run_laboratory
    if args.mode == 'live' and not args.contract:
        raise ConfigurationError('Live laboratory requires an explicit reviewed --contract; only scalar development MSE is supported')
    if args.contract:
        values = load_json(args.contract)
        for field in ('features', 'targets'):
            if isinstance(values.get(field), list):
                values[field] = tuple(values[field])
        try:
            contract = EvaluationContract(**values)
        except TypeError:
            raise ConfigurationError('Unknown or missing EvaluationContract field') from None
    else:
        contract = fixture_contract()
    backend = None
    if args.backend != 'dry-run' and not args.allow_execution:
        raise ConfigurationError('Selected backend requires --allow-execution')
    if args.backend == 'fixture':
        if args.mode != 'offline' or contract != fixture_contract():
            raise ConfigurationError('Fixture backend only supports offline synthetic fixture contract')
        backend = TrustedFixtureBackend()
    elif args.backend == 'docker':
        if not args.contract or not args.docker_image:
            raise ConfigurationError('Docker requires --contract and --docker-image pinned to a digest')
        from .execution.docker import DockerBackend
        backend = DockerBackend(image=args.docker_image, allow_execution=args.allow_execution)
    if args.allow_execution and backend is None:
        raise ConfigurationError('Choose an execution backend or omit --allow-execution')
    approved = args.approved_contract_digest
    if args.backend == 'fixture':
        approved = contract.sha256  # explicit fixture execution approves only the fixed synthetic contract
    if backend and approved != contract.sha256:
        raise ConfigurationError('Execution requires --approved-contract-digest matching reviewed full contract')
    models = []
    if args.mode == 'offline':
        model = cheap = LaboratoryFixtureModel()
        source = FixtureSource()
    else:
        if not args.allow_live:
            raise ConfigurationError('Live mode requires --allow-live; model calls transmit data and may incur charges')
        from .providers import OpenAIModel, paper_source_from_env
        model = OpenAIModel.from_env(role='main', timeout=config.request_timeout_seconds)
        cheap = OpenAIModel.from_env(role='cheap', timeout=config.request_timeout_seconds)
        source = paper_source_from_env(timeout=config.request_timeout_seconds)
        models = [model, cheap]
    if getattr(args, 'paper_corpus', None):
        from .recorded import RecordedPaperSource
        source=RecordedPaperSource(args.paper_corpus)
    from .integrations.aris import reviewer_from_env, ArisGate
    reviewer = reviewer_from_env(timeout=config.request_timeout_seconds) if args.mode == 'live' and config.claim_review else None
    if reviewer:
        models.append(reviewer)
    gate = ArisGate(os.environ['SAGE_ARIS_ROOT']) if config.claim_review and os.environ.get('SAGE_ARIS_ROOT') else None
    destination = output_directory(args.output)
    atomic_json(destination / 'config.json', config.to_dict())
    atomic_json(destination / 'contract.json', __import__('dataclasses').asdict(contract))
    from .checkpoints import Checkpoint, identity
    from .runtime import Runtime
    progress = ProgressArtifacts(destination)
    run_identity = {**identity(args.topic, args.mode, config, articles, model, cheap, source, reviewer),
                    'workflow': 'laboratory', 'contract_sha256': contract.sha256,
                    'execution_backend': args.backend, 'docker_image': args.docker_image}
    checkpoint = Checkpoint(destination / 'checkpoint.json', run_identity, resume=args.resume)
    runtime = Runtime(model, cheap, source, config, checkpoint=checkpoint,
        cache_only_retrieval=args.cache_only_retrieval,
        allow_incomplete_novelty=args.allow_incomplete_novelty,
        retry_uncertain=args.retry_uncertain,
        retain_rejected_responses=args.retain_rejected_responses,
        event_sink=progress.event, reviewer_model=reviewer, aris_gate=gate)
    runtime.event('recovery.policy', 'configured', workflow='laboratory',
                  resumed=bool(args.resume), backend=args.backend)
    if getattr(args, 'paper_corpus', None):
        runtime.event('retrieval.scope','recorded_corpus',corpus_sha256=source.corpus_sha256,
                      fresh_network_search=False,provenance=source.provenance)
    try:
        result = await run_laboratory(args.topic, model, source, contract=contract, cheap_model=cheap,
            config=config, mode=args.mode, articles=articles, backend=backend,
            allow_execution=args.allow_execution, approved_contract_digest=approved,
            runtime=runtime, on_progress=progress.snapshot)
        atomic_json(destination / 'result.json', result)
        if result['execution']:
            candidates = destination / 'candidates'
            candidates.mkdir()
            for index, attempt in enumerate(result['execution']['attempts'], 1):
                if attempt['code']:
                    atomic_text(candidates / f'attempt-{index}.py', attempt['code'] + '\n')
        if result['report']:
            atomic_text(destination / 'report.md', result['report']['markdown'])
            if result['report'].get('draft_markdown'):
                atomic_text(destination / 'draft.md', result['report']['draft_markdown'])
        print(json.dumps({'product': 'SAGE', 'status': result['status'], 'output': str(destination),
            'proposal_status': result['proposal']['status'],
            'execution_status': result['execution']['status'] if result['execution'] else None,
            'report_status': result['report']['status'] if result['report'] else None,
            'errors': result['errors'], 'usage': result['usage'],
            'scientific_validation': 'not_performed'}, indent=2))
        return 0 if result['status'] in ('dry_run', 'completed_fixture', 'completed_development', 'attempt_budget_exhausted') else 1
    finally:
        for provider in models:
            await provider.aclose()


async def execute_closed_loop(args, config):
    from .execution.research import validate_protocol
    from .checkpoints import Checkpoint, identity, digest
    from .runtime import Runtime
    from .providers import OpenAIModel
    from .recorded import RecordedPaperSource
    from .integrations.aris import reviewer_from_env, ArisGate
    from .orchestration.closed_loop import run_closed_loop
    contract=validate_protocol(load_json(args.protocol))
    if not args.allow_live or not args.allow_execution or args.approved_protocol_digest!=digest(contract):
        raise ConfigurationError('Closed loop requires live and execution opt-in with the exact frozen protocol digest')
    if not config.claim_review or config.discussion_mode!='hybrid' or not os.environ.get('SAGE_ARIS_ROOT'):
        raise ConfigurationError('Closed loop requires claim review, hybrid discussion and the pinned ARIS root')
    for path in (args.coral_python,args.candidate_python):
        if not path.is_absolute() or not path.is_file():
            raise ConfigurationError('Research runtime interpreter is unavailable')
    # Fresh-output only: never implicitly repeat confirmation after a crash.
    destination=output_directory(args.output)
    atomic_json(destination/'config.json',config.to_dict())
    model=OpenAIModel.from_env(role='main',timeout=config.request_timeout_seconds)
    cheap=OpenAIModel.from_env(role='cheap',timeout=config.request_timeout_seconds)
    reviewer=reviewer_from_env(timeout=config.request_timeout_seconds)
    source=RecordedPaperSource(args.paper_corpus)
    gate=ArisGate(os.environ['SAGE_ARIS_ROOT']) if os.environ.get('SAGE_ARIS_ROOT') else None
    checkpoint=Checkpoint(destination/'checkpoint.json',
        {**identity(args.topic,'live',config,None,model,cheap,source,reviewer),
         'workflow':'closed_loop','protocol_digest':digest(contract)})
    runtime=Runtime(model,cheap,source,config,checkpoint=checkpoint,reviewer_model=reviewer,aris_gate=gate,
                    retain_rejected_responses=True)
    runtime.event('retrieval.scope','recorded_corpus',corpus_sha256=source.corpus_sha256,
                  fresh_network_search=False,provenance=source.provenance)
    try:
        value=await run_closed_loop(args.topic,runtime,contract=contract,destination=destination,
            coral_python=args.coral_python,candidate_python=args.candidate_python,
            allow_execution=args.allow_execution,approved_protocol_digest=args.approved_protocol_digest)
        print(json.dumps({'status':value['status'],'output':str(destination),'usage':value['usage'],
                          'closure_checks':value.get('closure_checks'),'errors':value['errors']},ensure_ascii=False,indent=2))
        return 0 if value['status']=='completed_closed_loop' else 1
    finally:
        for provider in (model,cheap,reviewer):
            if provider is not None: await provider.aclose()


async def execute_write_report(args):
    from .writing.continuation import prepare_report_inputs
    from .writing import generate_report
    from .checkpoints import Checkpoint, code_version, digest, provider_identity
    from .runtime import Runtime
    from .providers import OpenAIModel
    if not args.allow_live: raise ConfigurationError('Writing requires explicit --allow-live')
    proposal,execution,lineage=prepare_report_inputs(args.input_run)
    config=RunConfig(max_model_calls=40,max_tokens_per_call=4000,max_reserved_output_tokens=160000,
                     max_wall_seconds=900,max_prompt_chars=200000,refinement_rounds=2)
    destination=output_directory(args.output)
    atomic_json(destination/'lineage.json',lineage);atomic_json(destination/'config.json',config.to_dict())
    model=OpenAIModel.from_env(role='main',timeout=config.request_timeout_seconds)
    cheap=OpenAIModel.from_env(role='cheap',timeout=config.request_timeout_seconds)
    source=FixtureSource()  # generate_report has no discovery/retrieval calls.
    checkpoint=Checkpoint(destination/'checkpoint.json',{'workflow':'write-report',
        'writer_code_sha256':code_version(),'input_sha256':digest(lineage),
        'providers':[provider_identity(model),provider_identity(cheap)]})
    runtime=Runtime(model,cheap,source,config,checkpoint=checkpoint,retain_rejected_responses=True)
    runtime.event('writing.input','verified_frozen_experiment',**lineage)
    try:
        report=await generate_report(runtime,proposal,execution,
            on_progress=lambda value:atomic_json(destination/'report.partial.json',value))
        report['lineage']=lineage;report['writer_code_sha256']=code_version()
        report['writing_providers']={'main':provider_identity(model),'cheap':provider_identity(cheap)}
        report['usage']=dict(runtime.usage)
        atomic_json(destination/'report.json',report)
        atomic_text(destination/'report.md',report['markdown'])
        atomic_text(destination/'draft.md',report['draft_markdown'])
        atomic_json(destination/'artifact-manifest.json',{p.name:{'bytes':p.stat().st_size,
            'sha256':__import__('hashlib').sha256(p.read_bytes()).hexdigest()}
            for p in sorted(destination.iterdir()) if p.is_file()})
        print(json.dumps({'status':report['status'],'draft_readiness':report['draft_readiness'],
            'output':str(destination),'usage':report['usage'],'new_training_runs':0,'new_final_test_accesses':0},indent=2))
        return 0 if report['status'].startswith('completed') else 1
    finally:
        await model.aclose();await cheap.aclose()


async def execute_write_paper(args):
    from .writing.continuation import prepare_report_inputs
    from .writing.manuscript import generate_manuscript, render_manuscript, validate_bundle
    from .checkpoints import Checkpoint, code_version, digest, provider_identity
    from .runtime import Runtime
    from .providers import OpenAIModel
    if not args.allow_live: raise ConfigurationError('Writing requires explicit --allow-live')
    _, execution, lineage = prepare_report_inputs(args.input_run)
    bundle = json.loads(args.evidence.read_text(encoding='utf-8'))
    validate_bundle(bundle)
    # Bind the numerical evidence to the verified execution; supplementary
    # research is a separate, explicitly supplied provenance-bearing record.
    if bundle['evidence'].get('original_analysis') != execution['research_analysis']:
        raise ConfigurationError('Manuscript evidence differs from verified experiment analysis')
    if bundle.get('lineage') != lineage:
        raise ConfigurationError('Manuscript evidence lineage differs from verified experiment')
    defaults = dict(max_model_calls=120, max_tokens_per_call=32768,
                    max_reserved_output_tokens=3932160, max_wall_seconds=7200,
                    request_timeout_seconds=300, max_prompt_chars=250000,
                    max_response_chars=250000,refinement_rounds=1)
    if args.config: defaults.update(json.loads(args.config.read_text(encoding='utf-8')))
    config = RunConfig(**defaults)
    destination = output_directory(args.output)
    # Assets are supplied separately and copied before rendering. They are
    # never interpreted as model commands or shell arguments.
    import shutil
    for assets in bundle.get('assets', {}).values():
        for asset in assets:
            name = asset['path']; rel = Path(name)
            if rel.is_absolute() or '..' in rel.parts or rel.suffix not in ('.tex','.pdf','.png'):
                raise ConfigurationError('Invalid supplied asset path')
            source_asset = args.evidence.parent / rel
            if not source_asset.resolve().is_relative_to(args.evidence.parent.resolve()) or source_asset.is_symlink():
                raise ConfigurationError('Asset escapes evidence directory')
            (destination / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source_asset, destination / rel)
    atomic_json(destination/'evidence.json',bundle)
    atomic_json(destination/'lineage.json',lineage)
    atomic_json(destination/'config.json',config.to_dict())
    model=OpenAIModel.from_env(role='main',timeout=config.request_timeout_seconds)
    cheap=OpenAIModel.from_env(role='cheap',timeout=config.request_timeout_seconds)
    checkpoint=Checkpoint(destination/'checkpoint.json',{'workflow':'write-paper',
        'writer_code_sha256':code_version(),'input_sha256':digest({'bundle':bundle,'config':config.to_dict()}),
        'providers':[provider_identity(model),provider_identity(cheap)]},resume=args.resume)
    runtime=Runtime(model,cheap,FixtureSource(),config,checkpoint=checkpoint,retain_rejected_responses=True,
                    retry_uncertain=args.retry_uncertain)
    runtime.event('manuscript.input','verified_frozen_experiment',**lineage)
    try:
        report=await generate_manuscript(runtime,bundle,
            on_progress=lambda value:atomic_json(destination/'manuscript.partial.json',value))
        report['lineage']=lineage
        report['writer_code_sha256']=code_version()
        report['writing_providers']={'main':provider_identity(model),'reviewer':provider_identity(model)}
        render_manuscript(report,bundle,destination)
        atomic_json(destination/'artifact-manifest.json',{str(p.relative_to(destination)).replace('\\','/'):
            {'bytes':p.stat().st_size,'sha256':__import__('hashlib').sha256(p.read_bytes()).hexdigest()}
            for p in sorted(destination.rglob('*')) if p.is_file()})
        print(json.dumps({'completeness':report['completeness'],'readiness':report['readiness'],
            'main_text_words':report['main_text_words'],'usage':report['usage'],'output':str(destination)},indent=2))
        return 0 if report['completeness']=='full_draft' else 1
    finally:
        await model.aclose();await cheap.aclose()


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    # Keep the original catalog/project commands and their tests as compatibility APIs.
    if argv and argv[0] in ('catalog', 'project', 'provenance'):
        filename = {'catalog': 'catalog.py', 'project': 'research.py', 'provenance': 'coi.py'}[argv[0]]
        return subprocess.call([sys.executable, str(ROOT / 'scripts' / filename), *argv[1:]])
    parser = argparse.ArgumentParser(prog='sage', description='SAGE — Scientific Agent for Grounded Exploration')
    parser.add_argument('--version', action='version', version=f'SAGE {__version__}')
    sub = parser.add_subparsers(dest='command', required=True)
    autonomous=sub.add_parser('autonomous',help='Native CORAL + ARIS + DeepSeek: autonomous evidence-scoped conjecture discovery')
    autonomous.add_argument('--output',type=Path,required=True)
    autonomous.add_argument('--topic',default='')
    autonomous.add_argument('--allow-live',action='store_true')
    autonomous.add_argument('--coral-python',type=Path)
    autonomous.add_argument('--aris-root',type=Path)
    autonomous.add_argument('--dsh',type=Path)
    autonomous.add_argument('--agent-user',default='sage-research')
    autonomous.add_argument('--max-attempts',type=int,default=4)
    autonomous.add_argument('--max-tools',type=int,default=160)
    autonomous.add_argument('--wall-seconds',type=int,default=7200)
    sub.add_parser('doctor', help='Inspect local setup without network or exposing secrets')
    coral = sub.add_parser('coral-evaluate', help='Execute a frozen reviewed task with the real CORAL grader')
    coral.add_argument('--contract',type=Path,required=True)
    coral.add_argument('--coral-python',type=Path,required=True)
    coral.add_argument('--output',type=Path,required=True)
    coral.add_argument('--allow-execution',action='store_true')
    coral.add_argument('--approved-contract-digest',required=True)
    runner = sub.add_parser('run', help='Run the proposal pipeline with fixture or explicit live providers')
    runner.add_argument('--mode', choices=('offline', 'live'), default='offline')
    runner.add_argument('--topic', default='Synthetic SAGE offline workflow demonstration')
    runner.add_argument('--output', type=Path, default=Path('projects/sage-run'))
    runner.add_argument('--allow-live', action='store_true')
    runner.add_argument('--config', type=Path, help='JSON RunConfig overrides; never credentials')
    runner.add_argument('--profile', choices=('standard', 'research'), default='standard',
                        help='Research: evidence capsules, semantic ranking, shared discussion and deeper bounded search')
    runner.add_argument('--resume', type=Path, help='Explicit matching checkpoint.json; keeps spent budgets and exact-input successful results')
    runner.add_argument('--cache-only-retrieval', action='store_true', help='Never issue new paper requests; cache misses remain unavailable')
    runner.add_argument('--allow-incomplete-novelty', action='store_true', help='Explicitly continue with unknown novelty after transient retrieval failures; never bypass missing chain evidence')
    runner.add_argument('--retain-rejected-responses', action='store_true', help='Retain bounded untrusted rejected model replies privately in checkpoint, never in public audit logs')
    runner.add_argument('--retry-uncertain', action='store_true', help='Permit another paid attempt after an ambiguous in-flight checkpoint request')
    runner.add_argument('--articles', type=Path, help='Local article JSON by stable paper ID/title')
    runner.add_argument('--paper-corpus',type=Path,help='Explicit fixed real-paper corpus; no fresh internet literature search')
    for name in ('max-chain-length', 'min-chain-length', 'max-candidates', 'max-model-calls', 'max-search-calls', 'refinement-rounds'):
        runner.add_argument('--' + name, type=int, default=None)
    runner.add_argument('--discussion-mode', choices=('none', 'hybrid'), default=None, help='Optional CoI student discussion before planning')
    runner.add_argument('--discussion-students', type=int, default=None)
    runner.add_argument('--discussion-rounds', type=int, default=None)
    runner.add_argument('--discussion-prompt-version', choices=('v1', 'v2', 'v3'), default=None)
    runner.add_argument('--publication-date', default=None, help='Inclusive DateOrYear or start:end window for all retrieval')
    for command in ('catalog', 'project', 'provenance'):
        sub.add_parser(command, help=f'Compatibility commands: sage {command} --help')
    lab = sub.add_parser('laboratory', parents=[runner], add_help=False, help='Proposal, bounded code generation and evidence report')
    lab.add_argument('--backend', choices=('dry-run', 'fixture', 'docker'), default='dry-run')
    lab.add_argument('--allow-execution', action='store_true')
    lab.add_argument('--contract', type=Path, help='Frozen scalar development EvaluationContract JSON')
    lab.add_argument('--approved-contract-digest', help='SHA-256 of the reviewed canonical full contract')
    lab.add_argument('--docker-image', help='Preinstalled image pinned by @sha256 digest')
    closed=sub.add_parser('closed-loop',help='Grounded proposal, two policy iterations, native CORAL GP training, holdout and report')
    closed.add_argument('--topic',required=True)
    closed.add_argument('--output',type=Path,required=True)
    closed.add_argument('--config',type=Path)
    closed.add_argument('--protocol',type=Path,required=True)
    closed.add_argument('--paper-corpus',type=Path,required=True)
    closed.add_argument('--coral-python',type=Path,required=True)
    closed.add_argument('--candidate-python',type=Path,required=True)
    closed.add_argument('--allow-live',action='store_true')
    closed.add_argument('--allow-execution',action='store_true')
    closed.add_argument('--approved-protocol-digest',required=True)
    paper=sub.add_parser('write-paper',help='Generate and revise a full manuscript with verified evidence, bibliography and assets')
    paper.add_argument('--input-run',type=Path,required=True)
    paper.add_argument('--evidence',type=Path,required=True)
    paper.add_argument('--output',type=Path,required=True)
    paper.add_argument('--config',type=Path)
    paper.add_argument('--resume',type=Path,help='Matching checkpoint from a prior output directory; spent requests remain counted')
    paper.add_argument('--retry-uncertain',action='store_true')
    paper.add_argument('--allow-live',action='store_true')
    writer=sub.add_parser('write-report',help='Compatibility evidence-ledger report; use write-paper for a full manuscript')
    writer.add_argument('--input-run',type=Path,required=True)
    writer.add_argument('--output',type=Path,required=True)
    writer.add_argument('--allow-live',action='store_true')
    args = parser.parse_args(argv)
    try:
        if args.command == 'doctor':
            return doctor()
        if args.command == 'autonomous':
            from .autonomous.runner import run as run_autonomous
            if args.max_attempts < 1 or args.max_tools < 1 or args.wall_seconds < 1:
                raise ConfigurationError('Autonomous budgets must be positive')
            return run_autonomous(args,output_directory(args.output))
        if args.command == 'write-paper':
            return asyncio.run(execute_write_paper(args))
        if args.command == 'write-report':
            return asyncio.run(execute_write_report(args))
        if args.command == 'coral-evaluate':
            from .integrations.coral import run_coral_task, validate_contract
            from .checkpoints import digest
            contract=validate_contract(load_json(args.contract))
            if not args.allow_execution or args.approved_contract_digest!=digest(contract):
                raise ConfigurationError('CORAL requires explicit execution opt-in and the exact reviewed contract digest')
            result=run_coral_task(contract,python=args.coral_python,destination=output_directory(args.output),
                allow_execution=args.allow_execution,approved_digest=args.approved_contract_digest)
            print(json.dumps({'status':result['status'],'output':str(args.output),
                'attempts':len(result['attempts']),'selected_attempt_id':result['selected_attempt_id'],
                'usage':result['usage'],'scientific_validation':'not_performed'},indent=2))
            return 0 if result['status']=='completed_development' else 1
        if args.command == 'closed-loop':
            from .config import profile_overrides
            overrides=profile_overrides('research');overrides.update(load_json(args.config) if args.config else {})
            try: config=RunConfig(**overrides)
            except TypeError: raise ConfigurationError('Unknown or invalid RunConfig field') from None
            return asyncio.run(execute_closed_loop(args,config))
        from .config import profile_overrides
        overrides = profile_overrides(args.profile)
        overrides.update(load_json(args.config) if args.config else {})
        for name in ('max_chain_length', 'min_chain_length', 'max_candidates', 'max_model_calls', 'max_search_calls', 'refinement_rounds', 'publication_date', 'discussion_mode', 'discussion_students', 'discussion_rounds', 'discussion_prompt_version'):
            if getattr(args, name) is not None:
                overrides[name] = getattr(args, name)
        try:
            config = RunConfig(**overrides)
        except TypeError:
            raise ConfigurationError('Unknown or invalid RunConfig field') from None
        if config.request_timeout_seconds > 300:
            raise ConfigurationError('request_timeout_seconds must not exceed 300')
        return asyncio.run(execute_laboratory(args, config, load_articles(args.articles)) if args.command == 'laboratory' else execute(args, config, load_articles(args.articles)))
    except (SageError, OSError, ValueError) as error:
        # OSError strings may contain sensitive paths; only our safe error messages surface.
        message = str(error) if isinstance(error, SageError) else 'Local input/output operation failed'
        print(f'SAGE error: {message}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
