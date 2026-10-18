"""One launch of the actual CORAL AgentManager and native DeepSeek Harness.

No generated conjectures, search queries or paper corpus are supplied by this
launcher. Only the research brief, tool contracts and upstream skills are seeded.
"""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import secrets
import shlex
import shutil
import signal
import subprocess
import sys
import time
from ..artifacts import atomic_json, atomic_text
from ..errors import ConfigurationError
from .service import ResearchService, serve, serve_grader, now
from .skills import assemble_native_task

ARIS_COMMIT = '15c0b799e6cd5fbc4da381a5786dd0bc2cdf15ee'
CORAL_COMMIT = '0123dfb939b35228cf2c1fde224cd0561e727408'
ROOT = Path(__file__).resolve().parents[2]


def command(argv, **kwargs):
    return subprocess.run([str(x) for x in argv], check=True, capture_output=True,
                          text=True, timeout=300, **kwargs).stdout.strip()


def source_manifest(root):
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted((root / 'sage').rglob('*')) if p.suffix in ('.py', '.md')}


def dsh_endpoint(env):
    # DSH uses DeepSeek's Messages transport, while SAGE's reader/critic uses
    # Chat Completions. Reusing the Chat root produces /v1/messages -> HTTP 404.
    return env.get('SAGE_DSH_BASE_URL') or 'https://api.deepseek.com/anthropic'


def require_pin(path, expected):
    try:
        current = command(['git', '-C', path, 'rev-parse', 'HEAD'])
        dirty = command(['git', '-C', path, 'status', '--porcelain', '--untracked-files=no'])
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        raise ConfigurationError('Native upstream must be installed from its pinned editable Git checkout') from None
    if current != expected:
        raise ConfigurationError('Native upstream checkout does not match the reviewed source pin')
    if dirty:
        raise ConfigurationError('Native upstream checkout has tracked modifications')


def prepare(destination, *, topic, aris_root, coral_python, dsh, agent_user, max_attempts=4):
    """Create a reproducible native task. This function never calls a model."""
    destination = Path(destination)
    seed = destination / 'seed'
    seed.mkdir()
    workflow = (Path(__file__).parent / 'workflow.md').read_text(encoding='utf-8')
    native_task, skill_receipt = assemble_native_task(aris_root, workflow)
    # DSH's shipped 64-KiB workspace-instruction budget would cut these original
    # methods and the following task in the middle. Reserve room for CORAL's
    # wrapper and parent instructions; retain the full original source files.
    instruction_budget = max(262144, len(native_task.encode('utf-8')) + 65536)
    skill_receipt['instruction_context_budget_bytes'] = instruction_budget
    atomic_json(destination / 'aris-inputs.json', skill_receipt)
    # Keep literal shell ${...} examples out of OmegaConf. CORAL repeatedly
    # serializes its task config; DSH natively loads this paired instruction file
    # alongside the AGENTS.md that CORAL generates, without config interpolation.
    atomic_text(seed / 'AGENTS.local.md', native_task)
    atomic_text(seed / 'RESEARCH_BRIEF.md', f'# Research direction\n\n{topic}\n\n' + workflow)
    atomic_text(seed / '.gitignore', '.dsh/\n__pycache__/\n.venv/\n')
    command(['git', 'init', '-q', seed])
    command(['git', '-C', seed, 'add', '.'])
    command(['git', '-C', seed, '-c', 'user.name=SAGE', '-c', 'user.email=sage@localhost',
             'commit', '-qm', 'Empty research project: direction and workflow only'])
    grader = destination / 'grader'
    grader.mkdir()
    atomic_text(grader / 'pyproject.toml', '[build-system]\nrequires=["setuptools>=68"]\nbuild-backend="setuptools.build_meta"\n'
        '[project]\nname="sage-conjecture-grader"\nversion="1.0.0"\n'
        '[tool.setuptools]\npy-modules=["sage_conjecture_grader"]\n')
    shutil.copy2(Path(__file__).parent / 'grader.py', grader / 'sage_conjecture_grader.py')
    patch = destination / 'research.patch.yml'
    # API credentials remain inherited environment references. Neither provider
    # keys nor the transient research-service token appear in saved config.
    atomic_text(patch, f'- id: agent-instructions\n  config:\n    maxBytes: {instruction_budget}\n'
        '    maxSourceBytes: 1048576\n'
        '- insert:\n'
        '    - id: sage-aris-skills\n      name: "@deepseek-ai/dsh-skill-filesystem"\n      config:\n'
        '        providerName: aris\n        includeDefaultRoots: false\n        watch: false\n'
        f'        bundledSkillDir: {json.dumps(str(aris_root / "skills"))}\n'
        '    - id: sage-research-mcp\n      name: "@deepseek-ai/dsh-mcp-client"\n      config:\n'
        '        serverName: sage_research\n        transport: stdio\n'
        f'        command: {json.dumps(str(coral_python))}\n'
        f'        args: ["{ROOT / "sage" / "autonomous" / "mcp.py"}"]\n'
        '        toolCallTimeoutMs: 1800000\n        failOnStartupError: true\n        env:\n'
        '          SAGE_RESEARCH_PORT: !!js process.env.SAGE_RESEARCH_PORT\n'
        '          SAGE_RESEARCH_TOKEN: !!js process.env.SAGE_RESEARCH_TOKEN\n')
    patch.chmod(0o644)  # Native DSH runs as the isolated non-root account.
    config = {'task': {'name': 'autonomous-conjectures', 'description': workflow,
                       'tips': 'Read RESEARCH_BRIEF.md; all research decisions belong to the agent.'},
        'grader': {'entrypoint': 'sage_conjecture_grader:Grader', 'setup': [f'uv pip install --no-deps {shlex.quote(str(grader))}'],
                   'timeout': 600, 'direction': 'maximize'},
        'agents': {'count': 1, 'runtime': 'dsh', 'model': os.environ.get('SAGE_MAIN_MODEL', 'deepseek-flash'),
            # DSH streams progress to stderr, while CORAL's stdout-only stall
            # clock falsely restarts a working headless session. The outer
            # wall deadline still bounds the entire run; crash recovery stays on.
            'isolate_user': agent_user, 'max_turns': 0, 'timeout': 0,
            'runtime_options': {'command': str(dsh), 'profile': 'headless', 'patch': str(patch),
                                'permission_mode': 'danger-full-access', 'tools_mode': 'native'},
            'heartbeat': [{'name': 'reflect', 'every': 1}, {'name': 'pivot', 'every': 3, 'trigger': 'plateau'}],
            'research': True},
        'workspace': {'repo_path': str(seed), 'results_dir': str(destination / 'results'),
                      'run_dir': str(destination / 'native-run')},
        'run': {'session': 'local', 'verbose': False, 'stop': {'max_real_attempts': max_attempts}}}
    atomic_json(destination / 'task.yaml', config)  # JSON is valid YAML.
    return config


def run(args, destination):
    if not args.allow_live:
        raise ConfigurationError('Autonomous research requires --allow-live')
    if os.name != 'posix':
        raise ConfigurationError('Native autonomous runtime currently requires Linux; use the configured AutoDL server')
    key = os.environ.get('SAGE_OPENAI_API_KEY') or os.environ.get('DEEPSEEK_API_KEY')
    if not key:
        raise ConfigurationError('Set SAGE_OPENAI_API_KEY or DEEPSEEK_API_KEY in the environment')
    os.environ.setdefault('SAGE_MODEL_PROVIDER', 'deepseek')
    os.environ.setdefault('SAGE_OPENAI_API_KEY', key)
    os.environ.setdefault('SAGE_OPENAI_BASE_URL', 'https://api.deepseek.com')
    os.environ.setdefault('SAGE_MAIN_MODEL', 'deepseek-flash')
    os.environ.setdefault('SAGE_CHEAP_MODEL', os.environ['SAGE_MAIN_MODEL'])
    if os.environ['SAGE_MODEL_PROVIDER'] != 'deepseek':
        raise ConfigurationError('This native DSH adapter currently supports the DeepSeek provider')
    from ..providers import OpenAIConfig
    OpenAIConfig.from_env()  # Fail before any native agent or paid request.
    home = Path(os.environ.get('SAGE_NATIVE_HOME', Path.home() / '.cache' / 'sage' / 'native'))
    metadata = home / 'runtime.json'
    if any(getattr(args, name) is None for name in ('coral_python', 'aris_root', 'dsh')):
        if not metadata.is_file():
            raise ConfigurationError('Run python scripts/setup_autonomous.py once to install the native runtimes')
        installed = json.loads(metadata.read_text(encoding='utf-8'))
        for name in ('coral_python', 'aris_root', 'dsh'):
            if getattr(args, name) is None:
                setattr(args, name, Path(installed[name]))
        os.environ['PATH'] = os.pathsep.join(installed.get('path', [])) + os.pathsep + os.environ.get('PATH', '')
    coral_python = args.coral_python.absolute()
    aris_root, dsh = args.aris_root.absolute(), args.dsh.absolute()
    import importlib.util
    if any(importlib.util.find_spec(package) is None for package in ('openai', 'pypdf')):
        # Reuse the one-time installed environment instead of requiring the
        # operator to install packages into their system Python as well.
        if Path(sys.executable).absolute() == coral_python:
            raise ConfigurationError('Native Python environment lacks openai/pypdf; rerun setup_autonomous.py')
        destination.rmdir()  # Exclusively created by the CLI; still empty.
        env = dict(os.environ, PYTHONPATH=str(ROOT))
        return subprocess.call([str(coral_python), '-m', 'sage', 'autonomous', '--allow-live',
            '--output', str(destination), '--topic', args.topic, '--coral-python', str(coral_python),
            '--aris-root', str(aris_root), '--dsh', str(dsh), '--agent-user', args.agent_user,
            '--max-attempts', str(args.max_attempts), '--max-tools', str(args.max_tools),
            '--wall-seconds', str(args.wall_seconds)], cwd=ROOT, env=env)
    require_pin(aris_root, ARIS_COMMIT)
    coral_root = Path(command([coral_python, '-c', 'import coral;from pathlib import Path;print(Path(coral.__file__).resolve().parent.parent)']))
    require_pin(coral_root, CORAL_COMMIT)
    if not dsh.is_file() or not shutil.which('node') or not shutil.which('uv'):
        raise ConfigurationError('Native runtime dependencies missing: run scripts/setup_autonomous.py first')
    if os.geteuid() != 0 or not args.agent_user:
        raise ConfigurationError('This Linux host adapter requires a manager running as root and a non-root --agent-user')
    import pwd
    user = pwd.getpwnam(args.agent_user)
    if user.pw_uid == 0:
        raise ConfigurationError('The native research agent must use a non-root OS account')
    # Manager-owned evidence is unreadable/unwritable by the native agent. Parent
    # traversal permissions must be configured during one-time server setup.
    destination.chmod(0o755)
    topic = args.topic or 'AI and machine learning: discover a concrete, mechanistic, falsifiable research gap using current literature; choose the subarea autonomously.'
    manifest = {'started': now(), 'topic': topic, 'framework_files': source_manifest(ROOT),
        'upstreams': {'ARIS': ARIS_COMMIT, 'CORAL': CORAL_COMMIT},
        'integration': 'native CORAL AgentManager -> native DSH -> original ARIS skills + SAGE research tools',
        'seeded_paper_corpus': False, 'seeded_hypotheses': False,
        'agent_uid': user.pw_uid, 'scientific_validation': 'not_performed'}
    atomic_json(destination / 'launch.json', manifest)
    prepare(destination, topic=topic, aris_root=aris_root, coral_python=coral_python,
            dsh=dsh, agent_user=args.agent_user, max_attempts=args.max_attempts)
    resolved = json.loads(command([coral_python, '-c',
        'import hashlib,json,sys;from coral.config import CoralConfig;'
        'c=CoralConfig.from_yaml(sys.argv[1]);c.to_yaml(sys.argv[2]);'
        'c=CoralConfig.from_yaml(sys.argv[2]);'
        'print(json.dumps({"resolved_task_sha256":hashlib.sha256(c.task.description.encode()).hexdigest()}))',
        destination / 'task.yaml', destination / 'native-config-resolved.yaml']))
    expected = json.loads((destination / 'aris-inputs.json').read_text(encoding='utf-8'))['coral_task_sha256']
    if resolved['resolved_task_sha256'] != expected:
        raise ConfigurationError('Native CORAL config did not preserve the complete original ARIS task input')
    atomic_json(destination / 'native-config-preflight.json', resolved)
    probe = command([coral_python, '-c',
        'import json,os,sys;from pathlib import Path;'
        'assert os.geteuid()!=0;assert not os.getgroups();'
        '[Path(p).read_bytes() for p in sys.argv[1:]];'
        'print(json.dumps({"uid":os.geteuid(),"gid":os.getegid(),"supplementary_groups":os.getgroups()}))',
        destination / 'research.patch.yml', aris_root / 'skills' / 'research-lit' / 'SKILL.md',
        ROOT / 'sage' / 'autonomous' / 'mcp.py'],
        cwd=destination, user=user.pw_uid, group=user.pw_gid, extra_groups=[])
    atomic_json(destination / 'isolation-preflight.json', json.loads(probe))
    token = secrets.token_hex(32)
    service = ResearchService(destination / 'service-private', destination, topic, max_tools=args.max_tools)
    server = serve(service, token)
    grader_server, grader_socket = serve_grader(service)
    # CORAL's OS-user helper adds safe.directory entries with git --system.
    # Confine that operation to this disposable run, preserving host settings.
    git_config = destination / 'git-system.conf'
    git_config.write_text('', encoding='utf-8')
    git_config.chmod(0o644)
    dependencies = command([coral_python, '-c',
        'import importlib.metadata as m;'
        'print("\\n".join(sorted({d.metadata["Name"]+"=="+d.version for d in m.distributions() '
        'if d.metadata.get("Name", "").lower() not in ("coral", "sage-conjecture-grader")})))'])
    dependency_file = destination / 'dependencies.txt'
    atomic_text(dependency_file, dependencies + '\n')
    env = dict(os.environ, ARIS_REPO=str(aris_root), DEEPSEEK_API_KEY=key,
        DEEPSEEK_BASE_URL=dsh_endpoint(os.environ), SAGE_RESEARCH_TOKEN=token,
        SAGE_RESEARCH_PORT=str(server.server_port), PYTHONUNBUFFERED='1',
        SAGE_GRADER_SOCKET=str(grader_socket),
        GIT_CONFIG_SYSTEM=str(git_config),
        UV_CONSTRAINT=str(dependency_file),
        GIT_AUTHOR_NAME='SAGE Research Agent', GIT_AUTHOR_EMAIL='sage@localhost',
        GIT_COMMITTER_NAME='SAGE Research Agent', GIT_COMMITTER_EMAIL='sage@localhost')
    if (home / 'wheelhouse').is_dir():
        env.setdefault('UV_FIND_LINKS', str(home / 'wheelhouse'))
    # The grader subprocess inherits these variables from the CORAL manager.
    process = None
    status = 'failed'
    def interrupted(signum, frame):
        raise InterruptedError('Autonomous research interrupted')
    prior_signal = signal.signal(signal.SIGTERM, interrupted)
    try:
        with (destination / 'manager.log').open('w', encoding='utf-8') as log:
            process = subprocess.Popen([str(coral_python), '-m', 'coral.cli', 'start',
                '--config', str(destination / 'task.yaml')], cwd=destination,
                env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True,
                extra_groups=[])
            atomic_json(destination / 'process.json', {'manager_pid': process.pid, 'started': now()})
            try:
                code = process.wait(timeout=args.wall_seconds)
                status = 'native_manager_finished' if code == 0 else 'native_manager_failed'
            except subprocess.TimeoutExpired:
                status = 'time_budget_reached'
            except (InterruptedError, KeyboardInterrupt):
                status = 'interrupted'
    finally:
        if process and process.poll() is None:
            process.send_signal(signal.SIGTERM)
            try:
                process.wait(timeout=20)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
        server.shutdown()
        grader_server.shutdown()
        grader_server.server_close()
        grader_socket.unlink(missing_ok=True)
        grader_socket.parent.rmdir()
        signal.signal(signal.SIGTERM, prior_signal)
        service.save()
    eligible = [g for g in service.grades if not g['contract_errors']]
    best = max(eligible, key=lambda g: g['score']) if eligible else None
    if best:
        sha = best['primary_sha256']
        shutil.copy2(service.private / f'conjectures-{sha}.json', destination / 'conjectures.json')
        shutil.copy2(service.private / f'report-{sha}.md', destination / 'CONJECTURES.md')
    selected_review = next((r for r in service.reviews if best and r['id'] == best.get('review_id')), None)
    unchanged = manifest['framework_files'] == source_manifest(ROOT)
    complete = (status == 'native_manager_finished' and best is not None and unchanged and
                sum(not r['grading'] for r in service.reviews) >= 2)
    final = {'status': status, 'finished': now(), 'output': str(destination),
        'papers_retrieved': len(service.papers), 'papers_read': len(service.cards),
        'searches': len(service.searches), 'critiques': len(service.reviews),
        'framework_unchanged_during_run': unchanged,
        'workflow_status': 'completed_autonomous_conjectures' if complete else 'incomplete',
        'graded_attempts': len(service.grades), 'selected_grade': best,
        'aris_skill_inputs': json.loads((destination / 'aris-inputs.json').read_text(encoding='utf-8')),
        'model_review_status': ('high_priority_issues_open' if selected_review and
            any(x.get('severity') == 'high' for x in selected_review['review']['issues']) else 'model_review_only'),
        'scientific_validation': 'not_performed', 'independent_acceptance': False,
        'aris_independent_gate': 'BLOCKED: API-only same-family critiques cannot certify acceptance'}
    atomic_json(destination / 'result.json', final)
    print(json.dumps(final, ensure_ascii=False, indent=2))
    return 0 if complete else 1
