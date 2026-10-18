"""Resume native DSH sessions through CORAL's public custom-runtime interface.

Lifecycle integration is adapted from CORAL's DeepSeekHarnessRuntime at
0123dfb939b35228cf2c1fde224cd0561e727408 (Apache-2.0; see NOTICE.md).
Modified for SAGE: native --json/--session-id, private exact-session recovery,
strict startup acknowledgement and metadata-only public logs. Upstream stays
unmodified. Native DSH remains responsible for restoring messages and tools.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
from pathlib import Path
import re
import signal
import subprocess
import threading
import uuid

from ..artifacts import atomic_json, atomic_text

logger = logging.getLogger(__name__)
_SESSION = re.compile(r'session-[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}\Z')
_OPTIONS = {'command', 'profile', 'patch', 'provider', 'permission_mode',
            'tools_mode', 'session_state_dir'}


def checked_id(value):
    # The pinned native headless creates session-${randomUUID()}. Never parse
    # identifiers from assistant prose or select the most recently modified file.
    if not isinstance(value, str) or not _SESSION.fullmatch(value):
        raise ValueError('Invalid native DSH session identifier')
    return value


def native_argv(command, *, profile='headless', patches=(), prompt='', resume_session_id=None):
    # --patch belongs to the outer launcher; --json starts headless's own
    # argument parser, so global patches MUST come before that boundary.
    argv = [str(command), '--profile', str(profile)]
    for patch in patches:
        argv.extend(['--patch', str(patch)])
    argv.append('--json')
    if resume_session_id is not None:
        argv.extend(['--session-id', checked_id(resume_session_id)])
    # Protect continuation prompts beginning with '-' from CLI interpretation.
    return argv + ['--', prompt]


def public_event(event):
    """Project native NDJSON to metadata; never export reasoning or tool data."""
    if not isinstance(event, dict) or event.get('type') == 'thinking':
        return None
    kind = event.get('type')
    if not isinstance(kind, str) or kind not in {
            'session', 'status', 'text', 'tool_call', 'tool_result', 'final', 'error'}:
        return None
    if kind == 'session':
        if not isinstance(event.get('cwd'), str):
            raise ValueError('Native DSH session event has no working directory')
        return {'type': kind, 'sessionId': checked_id(event.get('sessionId')), 'cwd': event['cwd']}
    out = {'type': kind}
    if kind in {'text', 'final'}:
        out['text_characters'] = len(event.get('text', '')) if isinstance(event.get('text', ''), str) else 0
    return out


def session_from_log(path):
    path = Path(path)
    if not path.is_file():
        return None
    found = None
    with path.open(encoding='utf-8') as stream:
        for line in stream:
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if isinstance(event, dict) and event.get('type') == 'session':
                current = checked_id(event.get('sessionId'))
                if found is not None and current != found:
                    raise ValueError('Conflicting native session identifiers in one launch')
                found = current
    return found


def state_path(worktree_path, state_root):
    cwd = str(Path(worktree_path).resolve())
    return Path(state_root) / (hashlib.sha256(cwd.encode()).hexdigest() + '.json')


def private_state_root(worktree_path, state_root):
    root = Path(state_root).absolute()
    if root.is_symlink() or root.parent.is_symlink() or root.resolve().is_relative_to(Path(worktree_path).resolve()):
        raise ValueError('Session state must be a manager-owned directory outside the agent worktree')
    if os.name == 'posix':
        parent = root.parent.stat()
        if parent.st_uid != os.geteuid() or parent.st_mode & 0o022:
            raise ValueError('Session state parent can be modified by another account')
        if root.exists() and (root.stat().st_uid != os.geteuid() or root.stat().st_mode & 0o077):
            raise ValueError('Existing session state is not manager-private')
    return root


def saved_session(worktree_path, agent_id, *, state_root):
    path = state_path(worktree_path, private_state_root(worktree_path, state_root))
    if not path.exists():
        return None
    if path.is_symlink():
        raise ValueError('Session pointer cannot be a symlink')
    try:
        value = json.loads(path.read_text(encoding='utf-8'))
        if (not isinstance(value, dict) or value.get('cwd') != str(Path(worktree_path).resolve())
                or value.get('agent_id') != agent_id):
            raise ValueError('Session pointer does not belong to this agent and worktree')
        return checked_id(value.get('session_id'))
    except (OSError, ValueError) as exc:
        raise ValueError('Cannot restore the recorded native session; refusing a fresh fallback') from exc


def save_session(worktree_path, agent_id, session_id, *, state_root):
    checked_id(session_id)
    state_root = private_state_root(worktree_path, state_root)
    state_root.mkdir(mode=0o700, parents=True, exist_ok=True)
    state_root.chmod(0o700)
    atomic_json(state_path(worktree_path, state_root), {
        'schema_version': 'sage.native_session.v1', 'agent_id': agent_id,
        'cwd': str(Path(worktree_path).resolve()), 'session_id': checked_id(session_id)})


class ResumableDeepSeekRuntime:
    instruction_filename = 'AGENTS.md'
    shared_dir_name = '.dsh'

    def extract_session_id(self, log_path):
        return session_from_log(log_path)

    def classify_exit(self, log_path, exit_code, uptime_seconds, min_clean_runtime_seconds=60):
        # The native final event makes short, successful tasks distinguishable
        # from startup crashes; no stdout-duration guess is needed.
        try:
            events = [json.loads(line) for line in Path(log_path).read_text(encoding='utf-8').splitlines()
                      if line.startswith('{')]
        except (OSError, ValueError):
            return 'no_result'
        if any(isinstance(e, dict) and e.get('type') == 'sage_runtime_error' for e in events):
            return 'session_error'
        return 'clean' if exit_code == 0 and any(isinstance(e, dict) and e.get('type') == 'final' for e in events) else 'no_result'

    def start(self, worktree_path, coral_md_path, model='deepseek-flash', runtime_options=None,
              max_turns=0, log_dir=None, verbose=False, resume_session_id=None, prompt=None,
              prompt_source=None, task_name=None, task_description=None, gateway_url=None,
              gateway_api_key=None, run_as_user=None, sandbox=None):
        # Optional CORAL dependency stays lazy so offline SAGE needs no install.
        from coral.agent.runtime import (AgentHandle, apply_run_as_user, apply_sandbox,
                                         apply_sandbox_env, write_coral_log_entry)
        from coral.agent.process import open_agent_stderr_for_log_dir
        from coral.venv_paths import venv_bin_dir
        from coral.workspace.repo import _clean_env

        worktree_path = Path(worktree_path).resolve()
        agent_id = (worktree_path / '.coral_agent_id').read_text(encoding='utf-8').strip()
        opts = dict(runtime_options or {})
        if set(opts) - _OPTIONS or not opts.get('session_state_dir'):
            raise ValueError('Resumable DSH needs an explicit private session_state_dir and supported options')
        state_root = private_state_root(worktree_path, opts['session_state_dir'])
        previous = saved_session(worktree_path, agent_id, state_root=state_root)
        if resume_session_id is not None:
            checked_id(resume_session_id)
            if previous is not None and previous != resume_session_id:
                raise ValueError('Requested session differs from the exact recorded native session')
        elif previous is not None:
            # CORAL's generic whole-manager validator recognizes Claude files
            # only. Recover our exact private pointer, never a guessed latest log.
            resume_session_id = previous
            logger.info('Restoring recorded native DSH session %s for %s', previous, agent_id)
        elif prompt_source in {'resume', 'restart', 'reflect', 'pivot'}:
            raise ValueError('Continuation has no native session identity; refusing to start fresh')
        if prompt is None:
            prompt = ('Continue the existing research session and address the current feedback.'
                      if resume_session_id else 'Begin working on your task and iterating on the seed solution.')

        dsh_home = worktree_path / '.dsh'
        dsh_home.mkdir(exist_ok=True)
        # Never write as root into .dsh: CORAL makes that tree agent-owned.
        # A hostile symlink there must not redirect a later manager write.
        config_root = state_root.parent / 'runtime-config'
        if config_root.is_symlink():
            raise ValueError('Runtime configuration directory cannot be a symlink')
        config_root.mkdir(mode=0o755, exist_ok=True)
        if os.name == 'posix' and (config_root.stat().st_uid != os.geteuid() or config_root.stat().st_mode & 0o022):
            raise ValueError('Runtime configuration directory is not manager-owned')
        config_root.chmod(0o755)
        model_patch = config_root / ('model-' + uuid.uuid4().hex + '.patch.yml')
        atomic_text(model_patch, '- id: agent-default-model\n  config:\n'
            f'    provider: {json.dumps(opts.get("provider", "deepseek-official"))}\n'
            f'    model: {json.dumps(model)}\n')
        model_patch.chmod(0o644)
        patches = opts.get('patch', [])
        if isinstance(patches, (str, Path)):
            patches = [patches]
        argv = native_argv(opts.get('command', 'dsh'), profile=opts.get('profile', 'headless'),
                           patches=[*patches, model_patch], prompt=prompt,
                           resume_session_id=resume_session_id)
        env = _clean_env()
        env.update(DSH_HOME=str(dsh_home), UV_PROJECT_ENVIRONMENT=str(worktree_path / '.venv'),
                   VIRTUAL_ENV=str(worktree_path / '.venv'))
        env['PATH'] = str(venv_bin_dir(worktree_path / '.venv')) + os.pathsep + env.get('PATH', '')
        for option, variable in [('permission_mode', 'DSH_PERMISSION_MODE'), ('tools_mode', 'DSH_TOOLS_MODE')]:
            if opts.get(option):
                env[variable] = str(opts[option])
        if gateway_url:
            env['DEEPSEEK_BASE_URL'] = gateway_url
        if gateway_api_key:
            env['DEEPSEEK_API_KEY'] = gateway_api_key
        apply_sandbox_env(env, sandbox)
        user_kwargs = apply_run_as_user(env, run_as_user)
        if user_kwargs:
            user_kwargs['extra_groups'] = []
        log_dir = Path(log_dir) if log_dir else dsh_home / 'logs'
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / f'{agent_id}.{len(list(log_dir.glob(f"{agent_id}*.log")))}.log'
        log_file = log_path.open('w', encoding='utf-8', buffering=1)
        write_coral_log_entry(log_file, prompt=prompt, source=prompt_source or ('resume' if resume_session_id else 'start'),
                             agent_id=agent_id, session_id=resume_session_id,
                             task_name=task_name, task_description=task_description)
        opened = open_agent_stderr_for_log_dir(log_dir, agent_id)
        err_path, err_file = opened if opened is not None else (log_path.with_suffix('.err'), None)
        if err_file is None:
            err_file = err_path.open('w', encoding='utf-8')
        process = subprocess.Popen(apply_sandbox(argv, sandbox), cwd=worktree_path, env=env,
            stdout=subprocess.PIPE, stderr=err_file, start_new_session=True, **user_kwargs)
        handle = AgentHandle(agent_id=agent_id, process=process, worktree_path=worktree_path,
                             log_path=log_path, err_file=err_file, err_path=err_path)
        ready = threading.Event()
        state = {'session_id': None, 'error': None}

        def pump():
            try:
                for raw in process.stdout:
                    try:
                        event = json.loads(raw)
                    except ValueError:
                        # Startup diagnostics cannot attest session identity.
                        # Retain their existence, never their arbitrary content.
                        log_file.write(json.dumps({'type': 'sage_native_diagnostic', 'bytes': len(raw)}) + '\n')
                        continue
                    projected = public_event(event)
                    if projected is None:
                        continue
                    if projected['type'] == 'session':
                        native_id = projected['sessionId']
                        if (Path(projected['cwd']).resolve() != worktree_path or
                                (resume_session_id and native_id != resume_session_id) or
                                (state['session_id'] and state['session_id'] != native_id)):
                            raise ValueError('Native DSH resumed an unexpected session or worktree')
                        save_session(worktree_path, agent_id, native_id, state_root=state_root)
                        state['session_id'] = handle.session_id = native_id
                    elif state['session_id'] is None:
                        raise ValueError('Native DSH output arrived before its session identity')
                    log_file.write(json.dumps(projected, ensure_ascii=False) + '\n')
                    log_file.flush()
                    if state['session_id']:
                        ready.set()
            except Exception:
                # Keep error data and hidden reasoning out of the public log.
                state['error'] = 'Native session protocol failed; refusing a fresh fallback'
                log_file.write(json.dumps({'type': 'sage_runtime_error', 'error': state['error']}) + '\n')
                if process.poll() is None:
                    try:
                        os.killpg(process.pid, signal.SIGTERM)
                    except (ProcessLookupError, PermissionError):
                        process.terminate()
            finally:
                ready.set()
                log_file.close()

        threading.Thread(target=pump, daemon=True, name=f'dsh-{agent_id}-metadata').start()
        if not ready.wait(timeout=60) or state['error'] or not state['session_id']:
            handle.stop()
            raise RuntimeError('Native DSH did not acknowledge the expected persisted session; inspect private stderr')
        logger.info('Native DSH %s session %s for %s', 'resumed' if resume_session_id else 'created',
                    state['session_id'], agent_id)
        return handle
