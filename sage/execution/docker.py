"""Explicit, local-only Docker capability for untrusted prediction programs.

The operator must supply an audited, already-present image pinned by digest. It
must contain ``python3`` and must not declare volumes. No image is pulled, no
package is installed, and generated Python is never interpreted on the host.
Docker is an isolation layer, not a proof against kernel/daemon vulnerabilities.
The frozen evaluator and its hidden targets remain in the calling host process.
"""
from __future__ import annotations

import asyncio
import json
import math
import os
from pathlib import Path
import re
import tempfile
import uuid
import warnings

from ..errors import ConfigurationError, SageError
from .contracts import BackendExecutionError


class DockerExecutionError(SageError):
    """Sanitized failure; never contains candidate stdout or stderr."""

    code = 'execution_error'


# This is trusted source text, passed only to the container's interpreter. The
# candidate has no ability to select the host command, entrypoint, or mounts.
_DRIVER = "import runpy; runpy.run_path('/candidate/candidate.py', run_name='__main__')"
_IMAGE = re.compile(r'[a-z0-9][a-z0-9._:/-]*@sha256:[0-9a-f]{64}\Z')
_MAX_CODE_BYTES = 262144
_READ_CHUNK = 8192


def _finite_number(value):
    try:
        return type(value) in (int, float) and math.isfinite(value)
    except (ValueError, OverflowError):
        return False


class _Process:
    def __init__(self):
        self.spawn = None
        self.process = None


class DockerBackend:
    """Run one feature-only candidate with fixed, non-model-configurable limits.

    ``spawn`` is an injectable async ``create_subprocess_exec``-compatible
    callable for offline tests. It is a trusted operator capability, never a
    model response. The default local socket is deliberately fixed: remote
    Docker hosts, ambient contexts and Docker credential files are not used.
    The execution timeout covers inspection, launch and output collection;
    bounded cleanup may take additional time. Cleanup failure is never success.
    """

    fixture = False

    def __init__(self, image: str, *, allow_execution: bool = False, spawn=None,
                 max_output_bytes: int = 1048576, max_error_bytes: int = 65536,
                 cleanup_timeout: float = 5.0):
        if allow_execution is not True:
            raise ConfigurationError('Docker execution requires explicit allow_execution=True')
        if not isinstance(image, str) or not _IMAGE.fullmatch(image):
            raise ConfigurationError('Docker image must be explicitly pinned with @sha256 and 64 lowercase hex digits')
        for value, upper in ((max_output_bytes, 1048576), (max_error_bytes, 65536)):
            if type(value) is not int or not 1 <= value <= upper:
                raise ConfigurationError('Invalid Docker output byte limit')
        if not _finite_number(cleanup_timeout) or not 0 < cleanup_timeout <= 10:
            raise ConfigurationError('Invalid Docker cleanup timeout')
        self.image = image
        self._spawn = spawn or asyncio.create_subprocess_exec
        self.max_output_bytes = max_output_bytes
        self.max_error_bytes = max_error_bytes
        self.cleanup_timeout = cleanup_timeout

    async def _read(self, stream, maximum):
        data = bytearray()
        while True:
            # Read at most one byte beyond the cap, never communicate() or an
            # unbounded read. The subprocess StreamReader is bounded as well.
            block = await stream.read(min(_READ_CHUNK, maximum + 1 - len(data)))
            if not block:
                return bytes(data)
            if len(data) + len(block) > maximum:
                raise DockerExecutionError('Docker output exceeded its byte limit')
            data.extend(block)

    async def _execute(self, argv, environment, state):
        state.process = None
        state.spawn = asyncio.create_task(self._spawn(
            *argv, stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            limit=_READ_CHUNK, env=environment))
        # Retain the spawn task if cancellation races subprocess creation, so
        # cleanup can recover and terminate the process instead of orphaning it.
        state.process = await asyncio.shield(state.spawn)
        process = state.process
        readers = [asyncio.create_task(self._read(process.stdout, self.max_output_bytes)),
                   asyncio.create_task(self._read(process.stderr, self.max_error_bytes)),
                   asyncio.create_task(process.wait())]
        try:
            output, error, status = await asyncio.gather(*readers)
            return status, output, error
        finally:
            for task in readers:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*readers, return_exceptions=True)

    async def _stop_cli(self, state):
        if state.spawn is None:
            return True
        if state.process is None:
            try:
                state.process = await asyncio.wait_for(
                    asyncio.shield(state.spawn), self.cleanup_timeout)
            except OSError:
                # A completed failed spawn did not create a usable process.
                return True
            except (Exception, asyncio.CancelledError):
                state.spawn.cancel()
                return False
        process = state.process
        if process.returncode is None:
            try:
                process.kill()
            except ProcessLookupError:
                pass
            except OSError:
                return False
        try:
            await asyncio.wait_for(process.wait(), self.cleanup_timeout)
            return True
        except Exception:
            return False

    async def _cleanup(self, base, environment, state, name, run_requested):
        stopped = await self._stop_cli(state)
        if not run_requested:
            return stopped
        removal = _Process()
        removed = False
        try:
            status, _, error = await asyncio.wait_for(
                self._execute(base + ['rm', '--force', '--volumes', name],
                              environment, removal), self.cleanup_timeout)
            # A failed run may never have created its named container.
            absent = error.strip() == (
                'Error response from daemon: No such container: ' + name).encode()
            removed = status == 0 or absent
        except Exception:
            pass
        finally:
            removal_stopped = await self._stop_cli(removal)
        return stopped and removed and removal_stopped

    async def _finish_cleanup(self, *args):
        task = asyncio.create_task(self._cleanup(*args))
        interrupted = False
        # Caller cancellation, including a second cancel, cannot skip cleanup.
        while not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                interrupted = True
        return task.result(), interrupted

    def _run_argv(self, base, root, name):
        return base + [
            'run', '--pull', 'never', '--name', name,
            '--network', 'none', '--read-only', '--user', '65534:65534',
            '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges:true',
            '--pids-limit', '64', '--memory', '256m', '--memory-swap', '256m',
            '--cpus', '1', '--ipc', 'none', '--log-driver', 'none', '--no-healthcheck',
            '--ulimit', 'nofile=64:64', '--ulimit', 'core=0:0',
            '--ulimit', 'fsize=16777216:16777216',
            '--tmpfs', '/tmp:rw,noexec,nosuid,nodev,size=64m,mode=1777',
            '--workdir', '/tmp', '--env', 'HOME=/tmp',
            '--mount', f'type=bind,src={root / "candidate"},dst=/candidate,readonly,bind-propagation=rprivate',
            '--mount', f'type=bind,src={root / "features.json"},dst=/input/features.json,readonly,bind-propagation=rprivate',
            '--entrypoint', 'python3', self.image, '-I', '-B', '-c', _DRIVER,
        ]

    async def predict(self, code: str, features: tuple, *, timeout: float) -> list:
        if not isinstance(code, str) or not code.strip() or len(code) > _MAX_CODE_BYTES:
            raise ConfigurationError('Candidate code must be nonempty bounded UTF-8 text')
        try:
            encoded_length = len(code.encode('utf-8'))
        except UnicodeError:
            raise ConfigurationError('Candidate code must be valid UTF-8 text') from None
        if encoded_length > _MAX_CODE_BYTES:
            raise ConfigurationError('Candidate code must be nonempty bounded UTF-8 text')
        if (not isinstance(features, tuple) or not 1 <= len(features) <= 10000 or
                not all(_finite_number(value) for value in features)):
            raise ConfigurationError('Features must be a bounded tuple of finite numbers')
        if not _finite_number(timeout) or not 0 < timeout <= 300:
            raise ConfigurationError('Docker execution timeout must be positive and at most 300 seconds')

        # All bind sources are owned temporary files, never caller paths or
        # links. No evaluator, targets, home directory or Docker socket is mounted.
        with tempfile.TemporaryDirectory(prefix='sage-docker-') as directory:
            root = Path(directory).resolve()
            if ',' in str(root):
                raise ConfigurationError('Docker temporary directory cannot contain commas')
            (root / 'candidate').mkdir(mode=0o755)
            (root / 'docker-config').mkdir(mode=0o700)
            candidate = root / 'candidate' / 'candidate.py'
            candidate.write_text(code, encoding='utf-8')
            candidate.chmod(0o444)
            feature_file = root / 'features.json'
            feature_file.write_text(json.dumps({'features': features}, allow_nan=False), encoding='utf-8')
            feature_file.chmod(0o444)
            environment = {'PATH': os.environ.get('PATH', os.defpath),
                           'HOME': str(root), 'LANG': 'C', 'LC_ALL': 'C'}
            base = ['docker', '--host', 'unix:///var/run/docker.sock',
                    '--config', str(root / 'docker-config')]
            name = 'sage-' + uuid.uuid4().hex
            state = _Process()
            run_requested = False

            async def execute():
                nonlocal run_requested
                # Image-declared volumes would otherwise bypass --read-only.
                status, volumes, _ = await self._execute(
                    base + ['image', 'inspect', '--format', '{{json .Config.Volumes}}', self.image],
                    environment, state)
                if status != 0:
                    raise DockerExecutionError('Pinned local Docker image is unavailable or could not be inspected')
                try:
                    declared = json.loads(volumes)
                except (ValueError, UnicodeError):
                    raise DockerExecutionError('Invalid Docker image inspection response') from None
                if declared is not None and declared != {}:
                    raise DockerExecutionError('Docker image must not declare volume mounts')
                run_requested = True
                status, output, error = await self._execute(
                    self._run_argv(base, root, name), environment, state)
                if status != 0:
                    # Docker uses 125/126/127 for daemon/launch failures. Never
                    # expose their host-side diagnostics as candidate feedback.
                    if status in (125, 126, 127):
                        raise DockerExecutionError('Docker candidate could not be launched')
                    diagnostic = ''.join(char for char in error.decode('utf-8', errors='replace')
                                         if char in '\n\t' or char.isprintable())[:4000]
                    raise BackendExecutionError('Docker candidate process failed', diagnostic=diagnostic)
                try:
                    predictions = json.loads(output.decode('utf-8'))
                except (ValueError, UnicodeError, RecursionError):
                    raise DockerExecutionError('Candidate stdout must be one JSON prediction list') from None
                if (not isinstance(predictions, list) or
                        not all(_finite_number(value) for value in predictions)):
                    raise DockerExecutionError('Candidate stdout must be a finite numeric JSON prediction list')
                return predictions

            failure = None
            predictions = None
            try:
                predictions = await asyncio.wait_for(execute(), timeout)
            except asyncio.TimeoutError:
                failure = DockerExecutionError('Docker execution exceeded its wall timeout')
            except FileNotFoundError:
                failure = ConfigurationError('Docker executable is unavailable; no automatic installation is performed')
            except OSError:
                failure = DockerExecutionError('Docker process could not be started')
            except BaseException as error:
                failure = error
            confirmed, interrupted = await self._finish_cleanup(
                base, environment, state, name, run_requested)
            if interrupted:
                failure = asyncio.CancelledError()
            if not confirmed:
                message = 'Docker cleanup could not be confirmed for container ' + name
                if isinstance(failure, asyncio.CancelledError):
                    warnings.warn(message, RuntimeWarning, stacklevel=2)
                else:
                    raise DockerExecutionError(message) from None
            if failure is not None:
                raise failure
            return predictions
