"""Zero-model lifecycle supervision for native CORAL team workers.

CORAL's public runtime contract restarts every exited process, including clean
completions. Keep a real, cancellable supervisor process alive while a worker has
no assigned action. This is SAGE-owned glue; neither CORAL nor DSH is modified.
Only authenticated team status can wake a parked worker, in its exact session.
"""
from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import threading
import time
from urllib.request import Request, urlopen

from .dsh_runtime import checked_id
from ..artifacts import atomic_json


_WAITING = {'wait', 'finished'}
_WORK = {'propose', 'review', 'revise'}


def process_identity(pid, proc_root=Path('/proc')):
    """Read identity without cwd/command permissions or exporting arguments."""
    directory = Path(proc_root) / str(pid)
    fields = (directory / 'stat').read_text().rsplit(') ', 1)[1].split()
    uid = next(line.split()[1] for line in (directory / 'status').read_text().splitlines()
               if line.startswith('Uid:'))
    return {'pid': int(pid), 'ppid': int(fields[1]), 'pgid': int(fields[2]),
            'sid': int(fields[3]), 'start_ticks': int(fields[19]),
            'uid': int(uid), 'state': fields[0]}


def track_native_processes(manager_pid, destination, known, agent_uid, *, proc_root=Path('/proc')):
    """Retain verified identities across manager registry deletion/restarts.

    A PID alone is not authority to signal it. Only a matching start time, an
    observed descendant, or a live member's existing group extends this run.
    Unrelated processes using the same OS account are reported, never adopted.
    """
    records, unreadable = {}, []
    for directory in Path(proc_root).iterdir():
        if not directory.name.isdigit():
            continue
        pid = int(directory.name)
        try:
            records[pid] = process_identity(pid, proc_root)
        except FileNotFoundError:
            continue  # Process exited during this scan.
        except (OSError, ValueError, IndexError, StopIteration) as exc:
            unreadable.append({'pid': pid, 'error': type(exc).__name__})
    manager = records.get(manager_pid)
    if manager and (manager_pid not in known or
                    known[manager_pid]['start_ticks'] == manager['start_ticks']):
        known.setdefault(manager_pid, {**manager, 'role': 'manager'})
    live = {pid: record for pid, record in records.items() if pid in known
            and known[pid]['start_ticks'] == record['start_ticks']}
    # The manager writes this registry; cross-check actual ancestry/OS identity
    # before accepting a PID, even when the registry survives a crash.
    registry = Path(destination) / 'native-run' / '.coral' / 'public' / 'agent_pids.json'
    registry_state = 'missing'
    if registry.exists():
        try:
            if registry.is_symlink() or registry.stat().st_size > 65536:
                raise ValueError('Invalid process registry')
            entries = json.loads(registry.read_text(encoding='utf-8'))
            if not isinstance(entries, dict):
                raise ValueError('Invalid process registry')
            registry_state = 'read'
            for pid in entries.values():
                record = records.get(pid) if type(pid) is int else None
                if record and record['uid'] == agent_uid and record['ppid'] in live:
                    if pid in known and known[pid]['start_ticks'] != record['start_ticks']:
                        continue
                    known.setdefault(pid, {**record, 'role': 'agent'})
                    live[pid] = record
        except (OSError, ValueError):
            registry_state = 'unreadable_or_invalid'
    # These existing manager-private session pointers outlive CORAL's public
    # PID registry, which normal shutdown removes before the parent returns.
    session_root = Path(destination) / 'session-state'
    if session_root.is_dir() and not session_root.is_symlink():
        for path in session_root.glob('*.json'):
            try:
                if path.is_symlink() or path.stat().st_size > 65536:
                    continue
                saved = json.loads(path.read_text(encoding='utf-8')).get('native_process', {})
                current = records.get(saved.get('pid'))
                if (current and current['uid'] == agent_uid
                        and all(current[k] == saved.get(k) for k in ('pid', 'start_ticks', 'pgid', 'sid', 'uid'))):
                    if current['pid'] in known and known[current['pid']]['start_ticks'] != current['start_ticks']:
                        continue
                    known.setdefault(current['pid'], {**current, 'role': 'agent'})
                    live[current['pid']] = current
            except (OSError, ValueError, TypeError, AttributeError):
                continue
    while True:
        groups = {(x['pgid'], x['sid']) for x in live.values()}
        additions = {pid: r for pid, r in records.items() if pid not in live
                     and (r['ppid'] in live or (r['pgid'], r['sid']) in groups)}
        if not additions:
            break
        for pid, record in additions.items():
            # Do not replace a reused PID with a new process identity.
            if pid in known and known[pid]['start_ticks'] != record['start_ticks']:
                continue
            known.setdefault(pid, {**record, 'role': 'agent' if record['uid'] == agent_uid else 'descendant'})
            live[pid] = record
        if not any(pid in live for pid in additions):
            break
    return {'active': [r for r in live.values() if r['state'] != 'Z'],
            'zombies': [r for r in live.values() if r['state'] == 'Z'],
            'unreadable': unreadable, 'registry': registry_state,
            'unscoped_agent_pids': [pid for pid, r in records.items()
                                   if r['uid'] == agent_uid and pid not in live]}


def stop_tracked_processes(manager_pid, destination, known, agent_uid, *,
                           term_seconds=10, kill_seconds=5, keep_current_manager=False):
    """Boundedly stop only verified run groups, including reparented children."""
    if keep_current_manager and manager_pid != os.getpid():
        raise ValueError('Only the current manager can be excluded from its own cleanup')
    sent = []
    def scan():
        snapshot = track_native_processes(manager_pid, destination, known, agent_uid)
        if keep_current_manager:
            snapshot['active'] = [r for r in snapshot['active'] if r['pid'] != manager_pid]
        return snapshot
    snapshot = scan()
    for sig, seconds in ((signal.SIGTERM, term_seconds), (signal.SIGKILL, kill_seconds)):
        signaled = set()
        end = time.monotonic() + seconds
        while snapshot['active']:
            for record in snapshot['active']:
                group = record['pgid']
                individual = keep_current_manager and group == os.getpgrp()
                target = ('pid', record['pid']) if individual else ('pgid', group)
                if (group <= 1 or (group == os.getpgrp() and not individual)
                        or target in signaled):
                    continue
                try:
                    current = process_identity(record['pid'])
                    if any(current[k] != record[k] for k in ('start_ticks', 'pgid', 'sid', 'uid')):
                        continue
                    if individual:
                        os.kill(record['pid'], sig)
                    else:
                        os.killpg(group, sig)
                    signaled.add(target)
                    sent.append({'pgid': group, 'signal': sig.name,
                                 'witness_pid': record['pid'], 'start_ticks': record['start_ticks'],
                                 'target_kind': target[0]})
                except ProcessLookupError:
                    continue
                except OSError as exc:
                    sent.append({'pgid': group, 'signal': sig.name, 'error': type(exc).__name__})
            if time.monotonic() >= end:
                break
            time.sleep(min(0.05, max(0, end - time.monotonic())))
            snapshot = scan()
        snapshot = scan()
        if not snapshot['active']:
            break
    verified = not snapshot['active'] and not any(x['pid'] in known for x in snapshot['unreadable'])
    return {'signals': sent, 'remaining': snapshot,
            'verified_no_active_tracked_processes': verified and not keep_current_manager,
            **({'verified_no_active_tracked_dependents': verified,
                'excluded_manager_pid': manager_pid} if keep_current_manager else {})}


class NativeOwnerGuard:
    """One manager-local fail-closed guard; no models, new process or retries.

    The launcher owns the research service. If it disappears, this existing
    manager remains able to stop its native groups and retain a crash receipt.
    A receipt cannot attest the guard-host manager's own eventual exit.
    """
    def __init__(self, destination, owner, manager, agent_uid, *, poll_seconds=1,
                 manager_exit_grace=120):
        if not 0 < poll_seconds <= 1 or not 0 < manager_exit_grace <= 120:
            raise ValueError('Owner guard timing must be positive and bounded')
        self.destination, self.owner, self.manager = Path(destination), dict(owner), dict(manager)
        self.agent_uid = agent_uid
        self.poll_seconds, self.manager_exit_grace = poll_seconds, manager_exit_grace
        self.lock, self.wake, self.done = threading.RLock(), threading.Event(), threading.Event()
        self.known = {manager['pid']: dict(manager, role='manager')}
        self.reason = None
        self.thread = None

    def owner_status(self):
        try:
            current = process_identity(self.owner['pid'])
        except FileNotFoundError:
            return 'owner_missing'
        except (OSError, ValueError, IndexError, StopIteration):
            return 'owner_unverifiable'
        if any(current[k] != self.owner[k] for k in ('pid', 'start_ticks', 'uid')):
            return 'owner_reused'
        return 'owner_zombie' if current['state'] == 'Z' else 'alive'

    def _close(self, reason):
        if self.reason is None:
            self.reason = reason
        self.wake.set()

    def check(self):
        with self.lock:
            status = self.owner_status()
            if status != 'alive':
                self._close(status)
            if self.reason is not None:
                raise ValueError('Native runtime owner unavailable; refusing new model work')

    def start(self):
        with self.lock:
            if self.thread is None:
                self.thread = threading.Thread(target=self._watch, daemon=True, name='sage-native-owner')
                self.thread.start()
        return self

    def launch(self, argv, **kwargs):
        """Keep spawn and identity registration atomic with guard shutdown."""
        with self.lock:
            self.check()
            process = subprocess.Popen(argv, **kwargs)
            try:
                identity = process_identity(process.pid)
                if (identity['ppid'] != self.manager['pid'] or identity['pgid'] != process.pid
                        or identity['sid'] != process.pid or identity['uid'] != self.agent_uid):
                    raise ValueError('Native process does not belong to this manager')
                self.known[process.pid] = dict(identity, role='agent')
                self.check()
            except BaseException:
                self._close('native_identity_unverifiable')
                # This direct Popen handle has not been reaped or released, so
                # its PID cannot have been reused. Never guess a foreign group.
                if process.poll() is None:
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                process.wait(timeout=5)
                if process.stdout:
                    process.stdout.close()
                raise
            return process, identity

    def _write(self, receipt):
        try:
            atomic_json(self.destination / 'runtime-crash.json', receipt)
        except (OSError, ValueError) as error:
            # Losing the receipt must not skip cleanup; never log raw paths.
            print(json.dumps({'type': 'sage_owner_guard', 'error_type': type(error).__name__,
                              'stage': 'crash_receipt_write'}), file=sys.stderr, flush=True)

    def _write_result_if_absent(self, receipt):
        if self.reason not in {'owner_missing', 'owner_reused', 'owner_zombie'}:
            return  # An unverifiable launcher may still own finalization.
        result = {'status': 'native_runtime_failed', 'stop_reason': 'launcher_lost',
            'workflow_status': 'incomplete', 'finished': receipt['observed_at'],
            'scientific_score': None, 'graded_attempts': None, 'formal_attempts_used': None,
            'grade_count_status': 'unknown_not_reconstructed', 'selected_grade': None,
            'export_policy': 'withheld_after_launcher_loss', 'runtime_crash': receipt,
            'scientific_validation': 'not_performed', 'independent_acceptance': False,
            'shutdown': {'cleanup_complete': False, 'service_idle': False,
                         **receipt.get('cleanup', {})}}
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=self.destination,
                                             prefix='.crash-result-', delete=False) as stream:
                temporary = Path(stream.name)
                json.dump(result, stream, ensure_ascii=False, allow_nan=False)
                stream.flush()
                os.fsync(stream.fileno())
            # Atomic create, never overwrite an existing terminal result.
            os.link(temporary, self.destination / 'result.json')
        except FileExistsError:
            pass
        except (OSError, ValueError) as error:
            print(json.dumps({'type': 'sage_owner_guard', 'error_type': type(error).__name__,
                              'stage': 'crash_result_write'}), file=sys.stderr, flush=True)
        finally:
            if temporary is not None:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    pass  # A leftover temporary receipt cannot prevent shutdown.

    def _watch(self):
        while True:
            with self.lock:
                if self.reason is None:
                    status = self.owner_status()
                    if status != 'alive':
                        self._close(status)
                if self.reason is not None:
                    break
                try:
                    track_native_processes(self.manager['pid'], self.destination, self.known, self.agent_uid)
                except (OSError, ValueError, IndexError, StopIteration):
                    self._close('process_tracking_unavailable')
                    break
            self.wake.wait(self.poll_seconds)
        receipt = {'schema_version': 'sage.native_owner_failure.v1',
            'phase': 'stopping', 'reason': self.reason, 'launcher_exit_cause': 'unknown',
            'observed_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
            'launcher_identity': self.owner, 'manager_identity': self.manager,
            'restart_admission_closed': True, 'manager_self_exit_requested': False,
            'manager_exit_observed': False, 'remote_request_outcome': 'unknown',
            'workflow_status': 'incomplete', 'scientific_validation': 'not_performed'}
        self._write(receipt)
        try:
            receipt['cleanup'] = stop_tracked_processes(self.manager['pid'], self.destination,
                self.known, self.agent_uid, keep_current_manager=True)
        except Exception as error:
            receipt['cleanup'] = {'verified_no_active_tracked_dependents': False,
                                  'error_type': type(error).__name__}
        receipt.update(phase='manager_exit_requested', manager_self_exit_requested=True,
                       manager_signal='SIGTERM', manager_force_exit_after_seconds=self.manager_exit_grace)
        self._write(receipt)
        self._write_result_if_absent(receipt)
        self.done.set()
        # Use CORAL's existing stop_all handler when installed. During startup
        # the default signal action exits, after our cleanup/receipt is complete.
        os.kill(self.manager['pid'], signal.SIGTERM)
        time.sleep(self.manager_exit_grace)
        os._exit(1)  # Bounded last resort if manager shutdown itself is stuck.


_OWNER_GUARDS = {}
_OWNER_GUARDS_LOCK = threading.Lock()


def acquire_owner_guard(destination, agent_uid, *, environ=None):
    """Bind manager-local protection to root-owned launcher metadata once."""
    environ = os.environ if environ is None else environ
    root = Path(destination).absolute()
    try:
        configured = Path(environ['SAGE_RUN_ROOT']).absolute()
        pid, ticks = int(environ['SAGE_LAUNCHER_PID']), int(environ['SAGE_LAUNCHER_START_TICKS'])
        metadata = root / 'launch.json'
        if (root != configured or root.is_symlink() or root.parent.is_symlink()
                or metadata.is_symlink() or metadata.stat().st_size > 1_000_000
                or root.stat().st_uid != os.geteuid() or root.stat().st_mode & 0o022
                or metadata.stat().st_uid != os.geteuid() or metadata.stat().st_mode & 0o022):
            raise ValueError
        launch = json.loads(metadata.read_text(encoding='utf-8'))
        saved = launch['launcher_identity']
        identity_keys = ('pid', 'ppid', 'pgid', 'sid', 'start_ticks', 'uid')
        if (not isinstance(saved, dict) or any(type(saved.get(k)) is not int for k in identity_keys)
                or type(agent_uid) is not int or agent_uid < 0):
            raise ValueError
        owner = {k: saved[k] for k in identity_keys}
        owner['state'] = saved.get('state') if saved.get('state') in {'R', 'S', 'D', 'Z', 'T', 't', 'X', 'I'} else 'unknown'
        manager = process_identity(os.getpid())
        if (type(pid) is not int or pid <= 1 or ticks <= 0 or owner['pid'] != pid
                or owner['start_ticks'] != ticks or owner['uid'] != os.geteuid()
                or launch['agent_uid'] != agent_uid or manager['pgid'] != os.getpid()
                or manager['sid'] != os.getpid()):
            raise ValueError
    except (KeyError, OSError, ValueError, TypeError, IndexError, StopIteration):
        raise ValueError('Native owner contract is missing, unsafe or inconsistent') from None
    key = (manager['pid'], manager['start_ticks'])
    with _OWNER_GUARDS_LOCK:
        guard = _OWNER_GUARDS.get(key)
        if guard is None:
            guard = NativeOwnerGuard(root, owner, manager, agent_uid)
            if guard.owner_status() == 'alive' and manager['ppid'] != owner['pid']:
                raise ValueError('Native manager does not belong to the recorded launcher')
            _OWNER_GUARDS[key] = guard.start()
        elif guard.destination != root or guard.owner != owner or guard.agent_uid != agent_uid:
            raise ValueError('Native owner contract changed within one manager')
    guard.check()
    return guard


def stop_native_tree(child, *, owns_supervisor_group=False):
    """Honor CORAL's process-group ownership, including native tool children.

    The manager starts this supervisor in its own session. On a deadline, signal
    that entire group rather than leave a DSH-launched shell alive. Direct helper
    callers which do not own a group cannot signal their parent/test runner.
    """
    owned_group = (owns_supervisor_group and os.name == 'posix'
                   and os.getpgrp() == os.getpid())
    if owned_group:
        os.killpg(os.getpgrp(), signal.SIGTERM)
    elif child.poll() is None:
        child.terminate()
    try:
        child.wait(timeout=5)
    except subprocess.TimeoutExpired:
        if owned_group:
            os.killpg(os.getpgrp(), signal.SIGKILL)
        else:
            child.kill()
            child.wait(timeout=5)


def team_status():
    """Use the existing slot-scoped channel; never read private team files."""
    request = Request('http://127.0.0.1:' + os.environ['SAGE_RESEARCH_PORT'] + '/tool',
        data=b'{"tool":"team","arguments":{"action":"status"}}',
        headers={'Authorization': 'Bearer ' + os.environ['SAGE_RESEARCH_TOKEN'],
                 'Content-Type': 'application/json'})
    with urlopen(request, timeout=5) as response:
        value = json.load(response)
    if not isinstance(value, dict) or value.get('error'):
        raise ValueError('Authenticated team status unavailable')
    return value


def resumed_argv(argv, session_id, slot):
    """Replace only headless continuation arguments; do not invoke a shell."""
    checked_id(session_id)
    boundary = argv.index('--json')
    return [*argv[:boundary + 1], '--session-id', session_id, '--',
        f'Your authenticated research team slot is {slot}. A new assigned action '
        'is available after runtime waiting. Call the research team tool with '
        'action=status and perform its current required action in this existing '
        'session. Only slot 0 may submit coral eval.']


def supervise(argv, slot, *, deadline, poll_seconds=20, status=team_status,
              emit=None, stop=None, clock=time.time, launch=subprocess.Popen,
              terminate=stop_native_tree):
    """Run DSH, then park completed/barrier workers without new model calls.

    ``stop`` is also used by signal handlers. Deadline is absolute and therefore
    cannot be extended by a manager restart. Failures retain a nonzero exit; a
    missing service never grants a new research task. No status text is exported.
    """
    if type(slot) is not int or not 1 <= slot <= 3:
        raise ValueError('Only non-coordinator team slots can be supervised')
    if not 0 < poll_seconds <= 60 or not math.isfinite(deadline):
        raise ValueError('Lifecycle needs a finite deadline and bounded polling')
    stop = stop or threading.Event()
    emit = emit or (lambda event: print(json.dumps(event), flush=True))
    session_id = None
    current = list(argv)

    def receipt(state):
        value = {'type': 'sage_lifecycle', 'state': state, 'slot': slot}
        if session_id:
            value['sessionId'] = session_id
        emit(value)

    while not stop.is_set():
        if clock() >= deadline:
            receipt('deadline')
            return 124
        child = launch(current, stdout=subprocess.PIPE, stderr=None)
        native = {'final': False, 'error': False}

        def forward():
            nonlocal session_id
            for raw in child.stdout:
                try:
                    event = json.loads(raw)
                except (ValueError, TypeError):
                    # Diagnostics are counted by the manager, not interpreted.
                    sys.stdout.buffer.write(raw)
                    sys.stdout.buffer.flush()
                    continue
                if isinstance(event, dict) and event.get('type') == 'session':
                    try:
                        found = checked_id(event.get('sessionId'))
                        if session_id is not None and found != session_id:
                            raise ValueError('Unexpected native session')
                        session_id = found
                    except ValueError:
                        native['error'] = True
                if isinstance(event, dict) and event.get('type') == 'final':
                    native['final'] = True
                emit(event)

        forwarding = threading.Thread(target=forward, daemon=True)
        forwarding.start()
        try:
            while child.poll() is None:
                if stop.wait(timeout=min(0.2, max(0, deadline - clock()))) or clock() >= deadline:
                    cancelled = stop.is_set()
                    receipt('stopped' if cancelled else 'deadline')
                    terminate(child)
                    return 0 if cancelled else 124
            forwarding.join(timeout=5)
            if forwarding.is_alive() or native['error']:
                receipt('native_error')
                terminate(child)
                return 1
            if child.returncode != 0 or not native['final'] or session_id is None:
                return child.returncode if child.returncode else 1
        finally:
            if child.poll() is None:
                child.kill()
                child.wait(timeout=5)
            if child.stdout:
                child.stdout.close()

        parked = False
        while not stop.is_set() and clock() < deadline:
            try:
                snapshot = status()
                if snapshot.get('slot') != slot:
                    raise ValueError('Team status belongs to a different slot')
                action = snapshot.get('next_action')
                if action not in _WAITING | _WORK:
                    raise ValueError('Unknown team action')
            except Exception:
                # No error payloads or server data in public logs. Wait without
                # calling a model while the authenticated service recovers.
                receipt('status_unavailable')
            else:
                if action in _WORK:
                    if not parked:
                        # The worker quit before completing its assignment.
                        # Let CORAL record/recover that exit through its normal
                        # restart path rather than hide a task failure.
                        return 0
                    current = resumed_argv(argv, session_id, slot)
                    receipt('resuming')
                    break
                receipt('waiting' if parked else 'parked')
                parked = True
            stop.wait(timeout=min(poll_seconds, max(0, deadline - clock())))
        else:
            receipt('stopped' if stop.is_set() else 'deadline')
            return 0 if stop.is_set() else 124
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--slot', type=int, required=True)
    parser.add_argument('--deadline', type=float, required=True)
    parser.add_argument('--poll-seconds', type=float, default=20)
    parser.add_argument('argv', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    argv = args.argv[1:] if args.argv[:1] == ['--'] else args.argv
    if not argv:
        parser.error('A native DSH command is required')
    stop = threading.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stop.set())
    return supervise(argv, args.slot, deadline=args.deadline,
                     poll_seconds=args.poll_seconds, stop=stop,
                     terminate=lambda child: stop_native_tree(child, owns_supervisor_group=True))


if __name__ == '__main__':
    raise SystemExit(main())
