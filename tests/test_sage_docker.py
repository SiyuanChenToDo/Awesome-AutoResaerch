"""Docker adapter regression tests; every subprocess is a fake, no Docker runs."""
import asyncio
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from sage.errors import ConfigurationError
from sage.execution.contracts import BackendExecutionError, EvaluationContract
from sage.execution.docker import DockerBackend, DockerExecutionError


IMAGE = 'python@sha256:' + 'a' * 64


class FakeStream:
    def __init__(self, data=b'', *, eof=True):
        self.data = data
        self.eof = asyncio.Event()
        if eof:
            self.eof.set()
        self.requests = []
        self.sent = 0

    async def read(self, count):
        self.requests.append(count)
        if self.data:
            value, self.data = self.data[:count], self.data[count:]
            self.sent += len(value)
            return value
        await self.eof.wait()
        return b''


class FakeProcess:
    def __init__(self, stdout=b'', stderr=b'', status=0, *, running=False):
        self.stdout = FakeStream(stdout, eof=not running)
        self.stderr = FakeStream(stderr, eof=not running)
        self.returncode = None if running else status
        self.exited = asyncio.Event()
        if not running:
            self.exited.set()
        self.killed = False

    async def wait(self):
        await self.exited.wait()
        return self.returncode

    def kill(self):
        self.killed = True
        self.returncode = -9
        self.exited.set()
        self.stdout.eof.set()
        self.stderr.eof.set()


class FakeDocker:
    def __init__(self, *, run=None, inspect=None, remove=None, run_gate=None, remove_gate=None):
        self.run = run or FakeProcess(b'[0, 2, 4]')
        self.inspect = inspect or FakeProcess(b'null\n')
        self.remove = remove or FakeProcess()
        self.run_gate = run_gate
        self.remove_gate = remove_gate
        self.run_started = asyncio.Event()
        self.remove_started = asyncio.Event()
        self.calls = []
        self.root = None
        self.features = None
        self.candidate = None
        self.mounted_paths = None

    async def __call__(self, *argv, **kwargs):
        self.calls.append((argv, kwargs))
        self.root = Path(argv[argv.index('--config') + 1]).parent
        if 'inspect' in argv:
            return self.inspect
        if 'run' in argv:
            self.features = json.loads((self.root / 'features.json').read_text())
            self.candidate = (self.root / 'candidate' / 'candidate.py').read_text()
            self.mounted_paths = sorted(path.relative_to(self.root / 'candidate').as_posix()
                                        for path in (self.root / 'candidate').rglob('*'))
            self.run_started.set()
            if self.run_gate is not None:
                await self.run_gate.wait()
            return self.run
        if 'rm' in argv:
            self.remove_started.set()
            if self.remove_gate is not None:
                await self.remove_gate.wait()
            return self.remove
        raise AssertionError('Unexpected subprocess command')

    def commands(self, command):
        return [argv for argv, _ in self.calls if command in argv]


class DockerBackendTests(unittest.IsolatedAsyncioTestCase):
    def backend(self, docker=None, **kwargs):
        return DockerBackend(IMAGE, allow_execution=True, spawn=docker or FakeDocker(),
                             cleanup_timeout=0.1, **kwargs)

    async def test_requires_explicit_opt_in_and_pinned_image(self):
        for flag in (False, None, 1, 'true'):
            with self.subTest(flag=flag), self.assertRaises(ConfigurationError):
                DockerBackend(IMAGE, allow_execution=flag)
        for image in ('python:latest', 'sha256:' + 'a' * 64, '--privileged@sha256:' + 'a' * 64,
                      IMAGE + '\n', IMAGE[:-1], 'python@sha256:' + 'g' * 64):
            with self.subTest(image=image), self.assertRaises(ConfigurationError):
                DockerBackend(image, allow_execution=True)
        self.assertFalse(self.backend().fixture)

    async def test_validates_limits_and_inputs_before_spawning(self):
        for kwargs in ({'max_output_bytes': 0}, {'max_output_bytes': 1048577},
                       {'max_error_bytes': True}, {'cleanup_timeout': float('inf')}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ConfigurationError):
                DockerBackend(IMAGE, allow_execution=True, **kwargs)
        docker = FakeDocker()
        backend = self.backend(docker)
        for code, features, timeout in (('', (1,), 1), ('x' * 262145, (1,), 1), ('\ud800', (1,), 1),
                                        ('print([])', [], 1), ('print([])', (), 1),
                                        ('print([])', (True,), 1), ('print([])', (float('inf'),), 1),
                                        ('print([])', (10 ** 1000,), 1), ('print([])', (1,), 0),
                                        ('print([])', (1,), float('nan'))):
            with self.subTest(features=features, timeout=timeout), self.assertRaises(ConfigurationError):
                await backend.predict(code, features, timeout=timeout)
        self.assertEqual(docker.calls, [])

    async def test_hardened_argv_and_feature_only_private_mounts(self):
        docker = FakeDocker()
        code = 'import json\nprint(json.dumps([0,2,4]))'
        with patch.dict(os.environ, {'OPENAI_API_KEY': 'host-secret', 'DOCKER_HOST': 'tcp://remote:2375',
                                     'DOCKER_CONTEXT': 'remote', 'HTTP_PROXY': 'http://secret'}):
            result = await self.backend(docker).predict(code, (0, 1, 2), timeout=1)
        self.assertEqual(result, [0, 2, 4])
        self.assertEqual(docker.features, {'features': [0, 1, 2]})
        self.assertEqual(docker.candidate, code)
        self.assertEqual(docker.mounted_paths, ['candidate.py'])
        argv = docker.commands('run')[0]
        for option, value in (('--pull', 'never'), ('--network', 'none'), ('--user', '65534:65534'),
                              ('--cap-drop', 'ALL'), ('--security-opt', 'no-new-privileges:true'),
                              ('--pids-limit', '64'), ('--memory', '256m'), ('--memory-swap', '256m'),
                              ('--cpus', '1'), ('--ipc', 'none'), ('--log-driver', 'none'),
                              ('--entrypoint', 'python3')):
            self.assertEqual(argv[argv.index(option) + 1], value)
        self.assertIn('--read-only', argv)
        self.assertIn('--no-healthcheck', argv)
        self.assertIn('/tmp:rw,noexec,nosuid,nodev,size=64m,mode=1777', argv)
        mounts = [argv[i + 1] for i, value in enumerate(argv) if value == '--mount']
        self.assertEqual(len(mounts), 2)
        self.assertTrue(all(',readonly,' in value for value in mounts))
        self.assertIn('dst=/candidate,', mounts[0])
        self.assertIn('dst=/input/features.json,', mounts[1])
        self.assertTrue(all('/var/run/docker.sock' not in value for value in mounts))
        self.assertEqual(argv[argv.index(IMAGE) + 1:argv.index(IMAGE) + 4], ('-I', '-B', '-c'))
        self.assertNotIn(code, argv)
        for command, kwargs in docker.calls:
            self.assertEqual(command[0], 'docker')
            self.assertEqual(command[command.index('--host') + 1], 'unix:///var/run/docker.sock')
            self.assertNotIn('shell', kwargs)
            self.assertEqual(kwargs['stdin'], asyncio.subprocess.DEVNULL)
            self.assertEqual(kwargs['stdout'], asyncio.subprocess.PIPE)
            self.assertEqual(kwargs['stderr'], asyncio.subprocess.PIPE)
            self.assertEqual(kwargs['limit'], 8192)
            self.assertEqual(set(kwargs['env']), {'PATH', 'HOME', 'LANG', 'LC_ALL'})
            self.assertNotIn('host-secret', repr(kwargs))
            self.assertNotIn('pull', command[:command.index('--config')])
        remove = docker.commands('rm')[0]
        self.assertIn('--force', remove)
        self.assertIn('--volumes', remove)
        self.assertEqual(remove[-1], argv[argv.index('--name') + 1])
        self.assertFalse(docker.root.exists())

    async def test_host_never_executes_candidate_and_evaluator_owns_metric(self):
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / 'would-be-host-execution'
            code = f'open({str(marker)!r}, "w").write("unsafe")'
            docker = FakeDocker()
            predictions = await self.backend(docker).predict(code, (0, 1, 2), timeout=1)
            self.assertFalse(marker.exists())
        contract = EvaluationContract('p', 'd', 'development', (0, 1, 2), (0, 2, 4))
        self.assertEqual(contract.evaluate(predictions), {'mse': 0})
        self.assertEqual(docker.features, {'features': [0, 1, 2]})

    async def test_rejects_image_volumes_without_running_candidate(self):
        for response in (b'{"/data": {}}', b'[]', b'not-json'):
            docker = FakeDocker(inspect=FakeProcess(response))
            with self.subTest(response=response), self.assertRaises(DockerExecutionError):
                await self.backend(docker).predict('pass', (1,), timeout=1)
            self.assertEqual(docker.commands('run'), [])
            self.assertFalse(docker.root.exists())

    async def test_missing_image_does_not_pull_or_execute(self):
        docker = FakeDocker(inspect=FakeProcess(stderr=b'private daemon details', status=1))
        with self.assertRaisesRegex(DockerExecutionError, 'unavailable') as caught:
            await self.backend(docker).predict('pass', (1,), timeout=1)
        self.assertNotIn('private daemon details', str(caught.exception))
        self.assertEqual(len(docker.calls), 1)

    async def test_missing_docker_is_configuration_error(self):
        async def missing(*args, **kwargs):
            raise FileNotFoundError('sensitive path')
        with self.assertRaisesRegex(ConfigurationError, 'unavailable') as caught:
            await self.backend(missing).predict('pass', (1,), timeout=1)
        self.assertNotIn('sensitive path', str(caught.exception))

    async def test_only_strict_finite_numeric_json_list_is_accepted(self):
        for output in (b'{"accuracy": 1}', b'[1]\nextra', b'[NaN]', b'[Infinity]', b'[1e999]',
                       b'[true]', b'["1"]', b'[[1]]', b'\xff', b''):
            docker = FakeDocker(run=FakeProcess(output))
            with self.subTest(output=output), self.assertRaises(DockerExecutionError):
                await self.backend(docker).predict('pass', (1,), timeout=1)
            self.assertEqual(len(docker.commands('rm')), 1)

    async def test_candidate_error_retains_only_bounded_untrusted_diagnostic(self):
        stderr = b'Traceback:\n  File "/candidate/candidate.py", line 2\nNameError\x00' + b'x' * 5000
        docker = FakeDocker(run=FakeProcess(stderr=stderr, status=1))
        with self.assertRaises(BackendExecutionError) as caught:
            await self.backend(docker).predict('pass', (1,), timeout=1)
        self.assertIn('line 2', caught.exception.diagnostic)
        self.assertNotIn('\x00', caught.exception.diagnostic)
        self.assertEqual(len(caught.exception.diagnostic), 4000)
        self.assertNotIn('Traceback', str(caught.exception))
        self.assertEqual(len(docker.commands('rm')), 1)

    async def test_docker_launch_errors_do_not_disclose_host_diagnostics(self):
        for status in (125, 126, 127):
            docker = FakeDocker(run=FakeProcess(stderr=b'private host diagnostic', status=status))
            with self.subTest(status=status), self.assertRaises(DockerExecutionError) as caught:
                await self.backend(docker).predict('pass', (1,), timeout=1)
            self.assertFalse(hasattr(caught.exception, 'diagnostic'))
            self.assertNotIn('private host', str(caught.exception))

    async def test_output_caps_abort_and_remove_even_when_other_pipe_hangs(self):
        for stream in ('stdout', 'stderr'):
            process = FakeProcess(**{stream: b'x' * 100000}, running=True)
            docker = FakeDocker(run=process)
            with self.subTest(stream=stream), self.assertRaisesRegex(DockerExecutionError, 'byte limit'):
                await self.backend(docker, max_output_bytes=16, max_error_bytes=16).predict('pass', (1,), timeout=1)
            self.assertLessEqual(getattr(process, stream).sent, 17)
            self.assertTrue(process.killed)
            self.assertEqual(len(docker.commands('rm')), 1)
            self.assertFalse(docker.root.exists())

    async def test_timeout_kills_cli_and_force_removes_container(self):
        process = FakeProcess(running=True)
        docker = FakeDocker(run=process)
        with self.assertRaisesRegex(DockerExecutionError, 'wall timeout'):
            # Leave enough time for mocked inspect/run startup on Windows;
            # this case tests cleanup of an already launched process.
            await self.backend(docker).predict('pass', (1,), timeout=0.2)
        self.assertTrue(process.killed)
        self.assertEqual(len(docker.commands('rm')), 1)
        self.assertFalse(docker.root.exists())

    async def test_timeout_also_covers_image_inspection(self):
        process = FakeProcess(running=True)
        docker = FakeDocker(inspect=process)
        with self.assertRaisesRegex(DockerExecutionError, 'wall timeout'):
            await self.backend(docker).predict('pass', (1,), timeout=0.01)
        self.assertTrue(process.killed)
        self.assertEqual(docker.commands('run'), [])

    async def test_cancellation_during_second_spawn_recovers_process_before_removal(self):
        gate = asyncio.Event()
        process = FakeProcess(running=True)
        docker = FakeDocker(run=process, run_gate=gate)
        task = asyncio.create_task(self.backend(docker).predict('pass', (1,), timeout=1))
        await docker.run_started.wait()
        task.cancel()
        await asyncio.sleep(0)
        self.assertFalse(task.done())
        gate.set()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertTrue(process.killed)
        self.assertEqual(len(docker.commands('rm')), 1)
        self.assertFalse(docker.root.exists())

    async def test_repeated_cancellation_cannot_skip_container_removal(self):
        gate = asyncio.Event()
        process = FakeProcess(running=True)
        docker = FakeDocker(run=process, remove_gate=gate)
        task = asyncio.create_task(self.backend(docker).predict('pass', (1,), timeout=1))
        await docker.run_started.wait()
        task.cancel()
        await docker.remove_started.wait()
        task.cancel()
        gate.set()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertTrue(process.killed)
        self.assertEqual(len(docker.commands('rm')), 1)
        self.assertFalse(docker.root.exists())

    async def test_cleanup_failure_cannot_be_reported_as_success(self):
        docker = FakeDocker(remove=FakeProcess(stderr=b'daemon unreachable', status=1))
        with self.assertRaisesRegex(DockerExecutionError, 'cleanup could not be confirmed'):
            await self.backend(docker).predict('pass', (1,), timeout=1)

    async def test_cleanup_itself_has_timeout_and_kills_its_cli(self):
        removal = FakeProcess(running=True)
        docker = FakeDocker(remove=removal)
        with self.assertRaisesRegex(DockerExecutionError, 'cleanup could not be confirmed'):
            await self.backend(docker).predict('pass', (1,), timeout=1)
        self.assertTrue(removal.killed)

    async def test_cleanup_failure_on_cancellation_is_reported_without_swallowing_cancel(self):
        docker = FakeDocker(run=FakeProcess(running=True), remove=FakeProcess(status=1))
        task = asyncio.create_task(self.backend(docker).predict('pass', (1,), timeout=1))
        await docker.run_started.wait()
        with self.assertWarnsRegex(RuntimeWarning, 'cleanup could not be confirmed'):
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task


if __name__ == '__main__':
    unittest.main()
