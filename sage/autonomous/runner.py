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
from ..config import REVIEW_MAX_OUTPUT_TOKENS
from ..errors import ConfigurationError
from .service import ResearchService, serve, serve_grader, now
from .skills import assemble_native_task
from .export import export_submissions
from .revision_policy import revision_policy, score_observations
from .lifecycle import track_native_processes, stop_tracked_processes

ARIS_COMMIT = '15c0b799e6cd5fbc4da381a5786dd0bc2cdf15ee'
CORAL_COMMIT = '0123dfb939b35228cf2c1fde224cd0561e727408'
ROOT = Path(__file__).resolve().parents[2]


def command(argv, **kwargs):
    return subprocess.run([str(x) for x in argv], check=True, capture_output=True,
                          text=True, timeout=300, **kwargs).stdout.strip()


def source_manifest(root):
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted((root / 'sage').rglob('*')) if p.suffix in ('.py', '.md')}


def launcher_identity():
    """Bind the manager's existing lifecycle checks to this exact Linux process."""
    from .lifecycle import process_identity
    try:
        identity = process_identity(os.getpid())
        if identity['state'] == 'Z' or identity['uid'] != os.geteuid():
            raise ValueError('Invalid launcher identity')
        return identity
    except (OSError, ValueError, KeyError, IndexError, StopIteration):
        raise ConfigurationError('Cannot verify the launcher Linux process identity') from None


def runtime_failure_receipt(destination):
    """A manager-side fatal lifecycle receipt must never become workflow success."""
    path = Path(destination) / 'runtime-crash.json'
    if not path.exists() and not path.is_symlink():
        return None
    receipt = {'path': path.name, 'readable': False}
    try:
        if path.is_symlink() or path.stat().st_size > 262144:
            return receipt
        raw = path.read_bytes()
        receipt['sha256'] = hashlib.sha256(raw).hexdigest()
        value = json.loads(raw)
        if isinstance(value, dict):
            receipt['readable'] = True
    except (OSError, ValueError):
        pass
    return receipt


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


def launch_settings(args, model_config):
    """Record effective limits/model settings, never credentials or proxy URLs."""
    from ..providers import _https_endpoint
    native_endpoint = _https_endpoint(dsh_endpoint(os.environ), 'Native DSH endpoint')
    chat = {key: getattr(model_config, key) for key in
            ('model', 'provider', 'endpoint', 'is_azure', 'api_version', 'deepseek_thinking')}
    return {'budgets': {'research_tools': args.max_tools, 'coordination_tools': 4000,
                        'formal_attempts': args.max_attempts, 'wall_seconds': args.wall_seconds,
                        'basis': 'SAGE tool attempts; not a total model-request, token or currency cap'},
            'model_configuration': {
                'native_researcher': {'model': model_config.model, 'provider': 'deepseek-official',
                    'endpoint': native_endpoint, 'transport': 'messages'},
                'reader': {**chat, 'environment_role': 'main', 'timeout_seconds': 180},
                'reviewer': {**chat, 'environment_role': 'main', 'timeout_seconds': 240},
                'independent_model_family': False}}


class NativeStopRequested(Exception):
    """A recorded signal, raised only at controlled launcher boundaries."""


def check_stop_requested(stop_requested):
    if stop_requested is not None and stop_requested():
        raise NativeStopRequested('Autonomous research interrupted')


def wait_native_manager(process, destination, deadline, agent_uid, known, *, started,
                        stop_requested=None):
    """Wait on the existing manager while retaining its separate child groups."""
    previous = None
    while True:
        check_stop_requested(stop_requested)
        snapshot = track_native_processes(process.pid, destination, known, agent_uid)
        check_stop_requested(stop_requested)
        identities = sorted(known.values(), key=lambda item: item['pid'])
        if identities != previous:
            atomic_json(destination / 'process.json', {'manager_pid': process.pid, 'started': started,
                'tracked_processes': identities, 'tracking_observed_at': now(),
                'unreadable_processes': snapshot['unreadable']})
            previous = identities
        code = process.poll()
        check_stop_requested(stop_requested)
        if code is not None:
            return code
        remaining = deadline - time.time()
        if remaining <= 0:
            raise subprocess.TimeoutExpired(process.args, 0)
        try:
            process.wait(timeout=min(0.5, remaining))
        except subprocess.TimeoutExpired:
            pass


def stop_native_manager(process, destination, agent_uid, known, *, grace_seconds=120):
    """Let CORAL stop workers, then verify and reap any separately grouped tail."""
    observation_errors = []
    def observe():
        try:
            track_native_processes(process.pid, destination, known, agent_uid)
        except Exception as error:
            kind = type(error).__name__
            if kind not in observation_errors:
                observation_errors.append(kind)
    observe()
    manager_signal = None
    if process.poll() is None:
        process.send_signal(signal.SIGTERM)
        manager_signal = 'SIGTERM'
        end = time.monotonic() + grace_seconds
        # CORAL interrupts each worker sequentially (up to 20 seconds each),
        # then closes its grader. A 20-second manager grace truncated that work.
        while process.poll() is None and time.monotonic() < end:
            observe()
            try:
                process.wait(timeout=min(0.2, max(0, end - time.monotonic())))
            except subprocess.TimeoutExpired:
                pass
    try:
        cleanup = stop_tracked_processes(process.pid, destination, known, agent_uid)
    except Exception as error:
        cleanup = {'verified_no_active_tracked_processes': False,
                   'process_cleanup_error': type(error).__name__}
    try:
        process.wait(timeout=1)
    except subprocess.TimeoutExpired:
        pass
    return {'manager_signal': manager_signal, 'manager_returncode': process.poll(),
            'grace_seconds': grace_seconds, 'process_observation_errors': observation_errors,
            **cleanup}


def drain_native_run(service, process, destination, agent_uid, known, server, grader_server,
                     grader_socket, reason):
    """Keep independent cleanup steps running when one fails; never fake idle."""
    receipt = {'service_idle': False, 'verified_no_active_tracked_processes': process is None,
               'errors': []}
    def attempt(stage, operation):
        try:
            return operation()
        except Exception as error:
            receipt['errors'].append({'stage': stage, 'error_type': type(error).__name__})
            return None
    attempt('service.begin_shutdown', lambda: service.begin_shutdown(reason))
    if process is not None:
        stopped = attempt('native_process_cleanup', lambda:
            stop_native_manager(process, destination, agent_uid, known))
        if stopped:
            receipt.update(stopped)
    receipt['service_idle'] = attempt('service.wait_for_idle', lambda:
                                     service.wait_for_idle(timeout=190)) is True
    for name, instance in (('research_server', server), ('grader_server', grader_server)):
        if instance is not None:
            attempt(name + '.shutdown', instance.shutdown)
            if not receipt['service_idle']:
                instance.block_on_close = False
            attempt(name + '.server_close', instance.server_close)
    if grader_socket is not None:
        attempt('grader_socket.unlink', lambda: grader_socket.unlink(missing_ok=True))
        attempt('grader_socket_directory.rmdir', grader_socket.parent.rmdir)
    receipt['cleanup_complete'] = (receipt['service_idle']
        and receipt['verified_no_active_tracked_processes'] and not receipt['errors'])
    return receipt


def prepare(destination, *, topic, aris_root, coral_python, dsh, agent_user, max_attempts=4,
            researchers=4, discussion_rounds=2, wall_seconds=7200):
    """Create a reproducible native task. This function never calls a model."""
    destination = Path(destination)
    seed = destination / 'seed'
    seed.mkdir()
    if researchers not in (1, 2, 3, 4) or not 1 <= discussion_rounds <= 3:
        raise ConfigurationError('Use 1–4 researchers and 1–3 discussion rounds')
    workflow = (Path(__file__).parent / 'workflow.md').read_text(encoding='utf-8')
    if researchers > 1:
        workflow += '\n\n' + (Path(__file__).parent / 'team-workflow.md').read_text(encoding='utf-8')
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
    from .mcp import MAX_TOOL_RESULT_BYTES
    # API credentials remain inherited environment references. Neither provider
    # keys nor the transient research-service token appear in saved config.
    # Official defaults spill results at 12,500 estimated tokens (~50 KB) and
    # prune their middle at 8,192 characters during compaction. Both break JSON.
    # Retain every packet admitted by our finite byte boundary; this is not an
    # enlargement of the model context window or scientific evidence compression.
    # The DSH provider plugin @deepseek-ai/dsh-llm-deepseek defaults to
    # maxTokens=256000: a per-request output hard cap that also pre-reserves
    # context (its input budget is the 1048576 window minus maxTokens, i.e.
    # 792576 by default). Measured on the 2026-10-19 run, the native research
    # agents' single-request outputs had P100 ~= 25k tokens (assistant bytes
    # of four sessions, tokenizer-converted), so 256000 needlessly gives up
    # ~190k input tokens and invites provider-side window errors. 65536 is
    # 2 x P100 rounded to a power of two and restores the input budget to
    # 983040. Cordis merges same-id patch entries deep, so this config keys
    # into dsh-base's existing `llm-deepseek` entry (distinct from the
    # `agent-default-model` provider/model overlay written per launch).
    atomic_text(patch, f'- id: agent-instructions\n  config:\n    maxBytes: {instruction_budget}\n'
        '    maxSourceBytes: 1048576\n'
        '- id: spill-policy\n  config:\n'
        f'    maxInlineTokens: {MAX_TOOL_RESULT_BYTES + 256}\n'
        '- id: tool-result-pruner\n  config:\n'
        f'    thresholdChars: {MAX_TOOL_RESULT_BYTES}\n'
        '- id: llm-deepseek\n  config:\n'
        '    maxTokens: 65536\n'
        '- insert:\n'
        '    - id: sage-aris-skills\n      name: "@deepseek-ai/dsh-skill-filesystem"\n      config:\n'
        '        providerName: aris\n        includeDefaultRoots: false\n        watch: false\n'
        f'        bundledSkillDir: {json.dumps(str(aris_root / "skills"))}\n'
        '    - id: sage-research-mcp\n      name: "@deepseek-ai/dsh-mcp-client"\n      config:\n'
        '        serverName: sage_research\n        transport: stdio\n'
        f'        command: {json.dumps(str(coral_python))}\n'
        '        args: ["-m", "sage.autonomous.mcp"]\n'
        '        toolCallTimeoutMs: 1800000\n        failOnStartupError: true\n        env:\n'
        f'          PYTHONPATH: {json.dumps(str(ROOT))}\n'
        '          SAGE_RESEARCH_PORT: !!js process.env.SAGE_RESEARCH_PORT\n'
        '          SAGE_RESEARCH_TOKEN: !!js process.env.SAGE_RESEARCH_TOKEN\n')
    patch.chmod(0o644)  # Native DSH runs as the isolated non-root account.
    config = {'task': {'name': 'autonomous-conjectures', 'description': workflow,
                       'tips': 'Read RESEARCH_BRIEF.md; all research decisions belong to the agent.'},
        'grader': {'entrypoint': 'sage_conjecture_grader:Grader', 'setup': [f'uv pip install --no-deps {shlex.quote(str(grader))}'],
                   'timeout': 1800, 'direction': 'maximize'},
        'agents': {'count': researchers, 'runtime': 'sage.autonomous.dsh_runtime:ResumableDeepSeekRuntime',
            'model': os.environ.get('SAGE_MAIN_MODEL', 'deepseek-flash'),
            # DSH streams progress to stderr, while CORAL's stdout-only stall
            # clock falsely restarts a working headless session. The outer
            # wall deadline still bounds the entire run; crash recovery stays on.
            'isolate_user': agent_user, 'max_turns': 0, 'timeout': 0,
            # CORAL's default 30-second burst window can never trip at the
            # observed 20-25s restart cadence (successive crashes land just
            # outside the window), so its circuit breaker never interposed.
            # A 120s window lets the breaker pause the agent after 3 crashes;
            # pause_seconds=300 >= window satisfies coral/config.py. This is
            # only a rate-limiting guardrail — the primary recovery fix is the
            # per-agent restart ledger and fresh-session escape in
            # sage/autonomous/dsh_runtime.py.
            'restart_burst_threshold': 3, 'restart_burst_window': 120,
            'restart_pause_seconds': 300,
            'runtime_options': {'command': str(dsh), 'profile': 'headless', 'patch': str(patch),
                                'session_state_dir': str(destination / 'session-state'),
                                'lifecycle_timeout_seconds': wall_seconds,
                                'lifecycle_poll_seconds': 20,
                                'permission_mode': 'danger-full-access', 'tools_mode': 'native'},
            'heartbeat': [{'name': 'reflect', 'every': 1}, {'name': 'pivot', 'every': 3, 'trigger': 'plateau'}],
            'research': True},
        'workspace': {'repo_path': str(seed), 'results_dir': str(destination / 'results'),
                      'run_dir': str(destination / 'native-run')},
        'run': {'session': 'local', 'verbose': False, 'stop': {'max_real_attempts': max_attempts}}}
    if researchers > 1:
        config['agents']['assignments'] = [
            {'count': 1, 'runtime_options': {'research_slot': slot,
                                          'research_team_size': researchers}}
            for slot in range(researchers)]
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
    model_config = OpenAIConfig.from_env()  # Fail before any native agent or paid request.
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
    if any(importlib.util.find_spec(package) is None for package in ('openai', 'pypdf', 'tokenizers')):
        # Reuse the one-time installed environment instead of requiring the
        # operator to install packages into their system Python as well.
        if Path(sys.executable).absolute() == coral_python:
            raise ConfigurationError('Native Python environment lacks openai/pypdf/tokenizers; rerun setup_autonomous.py')
        destination.rmdir()  # Exclusively created by the CLI; still empty.
        env = dict(os.environ, PYTHONPATH=str(ROOT))
        return subprocess.call([str(coral_python), '-m', 'sage', 'autonomous', '--allow-live',
            '--output', str(destination), '--topic', args.topic, '--coral-python', str(coral_python),
            '--aris-root', str(aris_root), '--dsh', str(dsh), '--agent-user', args.agent_user,
            '--max-attempts', str(args.max_attempts), '--max-tools', str(args.max_tools),
            '--wall-seconds', str(args.wall_seconds), '--researchers', str(args.researchers),
            '--discussion-rounds', str(args.discussion_rounds)], cwd=ROOT, env=env)
    from ..providers import OpenAIModel
    # Check the installed vocabulary before any native researcher/paid request.
    # This small probe checks the asset; every real prompt is counted separately.
    capacity_preflight = {role: OpenAIModel.from_env(role=role, env=os.environ).preflight(
        'SAGE startup capacity preflight', max_tokens=REVIEW_MAX_OUTPUT_TOKENS) for role in ('main', 'cheap')}
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
    owner_identity = launcher_identity()
    manifest = {'started': now(), 'topic': topic, 'framework_files': source_manifest(ROOT),
        'launcher_identity': owner_identity,
        'upstreams': {'ARIS': ARIS_COMMIT, 'CORAL': CORAL_COMMIT},
        'integration': 'native CORAL AgentManager -> native DSH -> original ARIS skills + SAGE research tools',
        'seeded_paper_corpus': False, 'seeded_hypotheses': False,
        'agent_uid': user.pw_uid, 'researchers': args.researchers,
        'discussion_rounds': args.discussion_rounds, 'scientific_validation': 'not_performed',
        **launch_settings(args, model_config), 'model_capacity_preflight': capacity_preflight}
    atomic_json(destination / 'launch.json', manifest)
    prepare(destination, topic=topic, aris_root=aris_root, coral_python=coral_python,
            dsh=dsh, agent_user=args.agent_user, max_attempts=args.max_attempts,
            researchers=args.researchers, discussion_rounds=args.discussion_rounds,
            wall_seconds=args.wall_seconds)
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
    service = ResearchService(destination / 'service-private', destination, topic, max_tools=args.max_tools,
                              researchers=args.researchers, discussion_rounds=args.discussion_rounds,
                              require_protocol=True, enable_peer_audit=True,
                              max_formal_attempts=args.max_attempts,
                              deadline=time.time() + args.wall_seconds)
    manifest['budgets']['deadline_unix'] = service.deadline
    atomic_json(destination / 'launch.json', manifest)
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
    env = dict(os.environ, ARIS_REPO=str(aris_root), DEEPSEEK_API_KEY=key, PYTHONPATH=str(ROOT),
        DEEPSEEK_BASE_URL=dsh_endpoint(os.environ), SAGE_RESEARCH_TOKEN=token,
        PYTHONUNBUFFERED='1',
        SAGE_RUNTIME_DEADLINE_UNIX=str(service.deadline),
        SAGE_LAUNCHER_PID=str(owner_identity['pid']),
        SAGE_LAUNCHER_START_TICKS=str(owner_identity['start_ticks']),
        SAGE_RUN_ROOT=str(destination),
        GIT_CONFIG_SYSTEM=str(git_config),
        UV_CONSTRAINT=str(dependency_file),
        GIT_AUTHOR_NAME='SAGE Research Agent', GIT_AUTHOR_EMAIL='sage@localhost',
        GIT_COMMITTER_NAME='SAGE Research Agent', GIT_COMMITTER_EMAIL='sage@localhost')
    if (home / 'wheelhouse').is_dir():
        env.setdefault('UV_FIND_LINKS', str(home / 'wheelhouse'))
    # The grader subprocess inherits these variables from the CORAL manager.
    process = process_started = server = grader_server = grader_socket = None
    status, stop_reason, stop_signal = 'failed', 'launch_failed', None
    launcher_error = None
    finalization_errors = []
    known_processes = {}
    shutdown = {'service_idle': False, 'verified_no_active_tracked_processes': False}
    def interrupted(signum, frame):
        nonlocal stop_signal
        # Raising InterruptedError here can be swallowed by /proc or subprocess
        # OSError handlers. Record intent without unwinding their internal locks.
        if stop_signal is None:
            stop_signal = signal.Signals(signum).name
    stop_requested = lambda: stop_signal is not None
    prior_signal = signal.signal(signal.SIGTERM, interrupted)
    prior_interrupt = signal.signal(signal.SIGINT, interrupted)
    try:
        check_stop_requested(stop_requested)
        server = serve(service, token)
        check_stop_requested(stop_requested)
        grader_server, grader_socket = serve_grader(service)
        check_stop_requested(stop_requested)
        env.update(SAGE_RESEARCH_PORT=str(server.server_port), SAGE_GRADER_SOCKET=str(grader_socket))
        with (destination / 'manager.log').open('w', encoding='utf-8') as log:
            check_stop_requested(stop_requested)
            process = subprocess.Popen([str(coral_python), '-m', 'coral.cli', 'start',
                '--config', str(destination / 'task.yaml')], cwd=destination,
                env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True,
                extra_groups=[])
            process_started = now()
            check_stop_requested(stop_requested)
            atomic_json(destination / 'process.json', {'manager_pid': process.pid, 'started': process_started})
            try:
                code = wait_native_manager(process, destination, service.deadline, user.pw_uid,
                                           known_processes, started=process_started,
                                           stop_requested=stop_requested)
                check_stop_requested(stop_requested)
                status = 'native_manager_finished' if code == 0 else 'native_manager_failed'
                # Exit zero alone does not reveal why an external manager stopped.
                stop_reason = 'manager_exited'
            except subprocess.TimeoutExpired:
                status = 'time_budget_reached'
                stop_reason = 'wall_time_budget'
            except (NativeStopRequested, KeyboardInterrupt):
                status = 'interrupted'
                stop_reason = 'user_interrupt'
    except (NativeStopRequested, KeyboardInterrupt):
        status = 'interrupted'
        stop_reason = 'user_interrupt'
    except Exception as error:
        # Preserve a terminal failure after cleanup. External exception messages
        # can contain credentials or model data, so retain only the safe type.
        status, stop_reason = 'failed', 'launcher_exception'
        launcher_error = {'error_type': type(error).__name__, 'stage': 'native_supervision'}
    finally:
        # Prevent a second signal from cutting off cleanup between worker groups.
        signal.signal(signal.SIGTERM, lambda *_: None)
        signal.signal(signal.SIGINT, lambda *_: None)
        try:
            if stop_signal is not None:
                status, stop_reason = 'interrupted', 'user_interrupt'
            stop_reason = service.shutdown_reason or stop_reason
            shutdown = drain_native_run(service, process, destination, user.pw_uid, known_processes,
                                        server, grader_server, grader_socket, stop_reason)
        finally:
            signal.signal(signal.SIGTERM, prior_signal)
            signal.signal(signal.SIGINT, prior_interrupt)
        process_receipt = {'manager_pid': process.pid if process else None,
            'started': process_started if process else None,
            'tracked_processes': sorted(known_processes.values(), key=lambda item: item['pid']),
            'stop_reason': stop_reason, 'stop_signal': stop_signal, 'shutdown': shutdown}
        operations = [('process_persistence', lambda: atomic_json(destination / 'process.json', process_receipt))]
        if shutdown['service_idle']:
            operations.append(('service_persistence', service.save))
        for stage, operation in operations:
            try:
                operation()
            except Exception as error:
                finalization_errors.append({'stage': stage, 'error_type': type(error).__name__})
    runtime_crash = None
    unchanged = None
    finalization_stage = 'runtime_receipt'
    try:
        runtime_crash = runtime_failure_receipt(destination)
        if runtime_crash is not None:
            status, stop_reason = 'failed', 'runtime_supervision_failed'
        cleanup_complete = shutdown['cleanup_complete']
        if finalization_errors:
            status, stop_reason = 'failed', 'finalization_exception'
        finalization_stage = 'export_selection'
        exported = (export_submissions(service.private, destination, service.grades) if cleanup_complete else
                    {'selected_grade': None, 'best_score_grade': None, 'policy': 'withheld_until_cleanup_complete'})
        selected = exported['selected_grade']
        finalization_stage = 'result_metadata'
        selected_review = next((r for r in service.reviews if selected and r['id'] == selected.get('review_id')), None)
        finalization_stage = 'source_verification'
        unchanged = manifest['framework_files'] == source_manifest(ROOT)
        finalization_stage = 'result_metadata'
        team = service.team.summary() if service.team else None
        complete = (status == 'native_manager_finished' and not finalization_errors and cleanup_complete and selected is not None and unchanged and
                    (team is None or not service.team.grade_errors(
                        json.loads((destination / 'conjectures.json').read_text(encoding='utf-8')),
                        selected['primary_sha256'])))
        final = {'status': status, 'stop_reason': stop_reason, 'stop_signal': stop_signal,
            'launcher_error': launcher_error,
            'runtime_crash': runtime_crash, 'finalization_errors': finalization_errors,
            'shutdown': shutdown, 'finished': now(), 'output': str(destination),
            'papers_retrieved': len(service.papers), 'papers_read': len(service.cards),
            'searches': len(service.searches), 'critiques': len(service.reviews),
            'framework_unchanged_during_run': unchanged,
            'workflow_status': 'completed_autonomous_conjectures' if complete else 'incomplete',
            'graded_attempts': len(service.grades), 'selected_grade': selected,
            'formal_attempts_used': service.formal_attempts,
            'complete_scientific_reviews': sum(g.get('evaluation_status') == 'completed' for g in service.grades),
            'best_score_grade': exported['best_score_grade'], 'export_policy': exported['policy'],
            'research_team': team,
            'aris_skill_inputs': json.loads((destination / 'aris-inputs.json').read_text(encoding='utf-8')),
            'model_review_status': ('high_priority_issues_open' if selected_review and
                any(x.get('severity') == 'high' for x in selected_review['review']['issues']) else 'model_review_only'),
            'scientific_validation': 'not_performed', 'independent_acceptance': False,
            'revision_policy': revision_policy(),
            'score_observations': score_observations(service.reviews),
            'aris_independent_gate': 'BLOCKED: API-only same-family critiques cannot certify acceptance'}
    except Exception as error:
        finalization_errors.append({'stage': finalization_stage, 'error_type': type(error).__name__})
        complete = False
        # An invalid export or broken auxiliary artifact remains a failure. Keep
        # the original submissions untouched and write only the run's outcome.
        final = {'status': 'failed', 'stop_reason': 'finalization_exception',
            'stop_signal': stop_signal, 'launcher_error': launcher_error,
            'runtime_crash': runtime_crash, 'finalization_errors': finalization_errors,
            'shutdown': shutdown, 'finished': now(), 'output': str(destination),
            'workflow_status': 'incomplete', 'framework_unchanged_during_run': unchanged,
            'papers_retrieved': len(service.papers), 'papers_read': len(service.cards),
            'searches': len(service.searches), 'critiques': len(service.reviews),
            'graded_attempts': len(service.grades), 'formal_attempts_used': service.formal_attempts,
            'complete_scientific_reviews': sum(isinstance(g, dict) and
                g.get('evaluation_status') == 'completed' for g in service.grades),
            'selected_grade': None, 'best_score_grade': None,
            'export_policy': 'unverified_due_finalization_failure', 'scientific_score': None,
            'scientific_validation': 'not_performed', 'independent_acceptance': False}
    atomic_json(destination / 'result.json', final)
    print(json.dumps(final, ensure_ascii=False, indent=2))
    return 0 if complete else 1
