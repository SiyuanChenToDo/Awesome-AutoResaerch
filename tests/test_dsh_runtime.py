"""Offline contracts for native DSH resume and its public event boundary."""

import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

from sage.autonomous import dsh_runtime
from sage.autonomous.dsh_runtime import (
    native_argv,
    private_state_root,
    public_event,
    save_session,
    saved_session,
    session_from_log,
    state_path,
)


SESSION_A = 'session-54b62236-a4ad-4f77-881f-217eeac651f2'
SESSION_B = 'session-1e476eda-9b9d-4fd9-95ac-3020381d7148'


class NativeArgvTests(unittest.TestCase):
    def test_fresh_launch_uses_native_json_stream_and_literal_prompt(self):
        prompt = '--session-id attacker\n$(do-not-execute)'
        self.assertEqual(
            native_argv('/opt/native/dsh', prompt=prompt),
            ['/opt/native/dsh', '--profile', 'headless', '--json', '--', prompt],
        )

    def test_resume_passes_the_exact_validated_native_id(self):
        argv = native_argv('/opt/native/dsh', profile='research',
                           prompt='Continue from evaluation.',
                           resume_session_id=SESSION_A)
        self.assertEqual(argv, ['/opt/native/dsh', '--profile', 'research', '--json',
                                '--session-id', SESSION_A, '--',
                                'Continue from evaluation.'])
        self.assertNotIn('--resume', argv)

    def test_patch_order_and_path_command_are_preserved_without_a_shell(self):
        command = Path('native tools') / 'dsh'
        patches = ('research config.yml', 'private settings.yml')
        self.assertEqual(
            native_argv(command, patches=patches, prompt='Continue',
                        resume_session_id=SESSION_B),
            [str(command), '--profile', 'headless',
             '--patch', patches[0], '--patch', patches[1], '--json',
             '--session-id', SESSION_B, '--', 'Continue'],
        )

    def test_invalid_ids_are_refused_instead_of_silently_starting_fresh(self):
        for invalid in ('not-a-session', '', SESSION_A + '\n',
                        '54b62236-a4ad-4f77-881f-217eeac651f2',
                        '../' + SESSION_A, '--session-id=' + SESSION_A,
                        'session-54b62236-a4ad-4f77-881f-217eeac651f2-trailing'):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                native_argv('/opt/native/dsh', resume_session_id=invalid)


class PublicEventTests(unittest.TestCase):
    def test_session_event_exposes_only_resume_metadata(self):
        event = {'type': 'session', 'sessionId': SESSION_A, 'cwd': '/work/research',
                 'text': 'private transcript', 'arguments': {'key': 'private arguments'},
                 'content': [{'thinking': 'private thought'}],
                 'reasoning': 'private reasoning', 'apiKey': 'private credential'}
        result = public_event(event)
        self.assertEqual(result,
                         {'type': 'session', 'sessionId': SESSION_A,
                          'cwd': '/work/research'})
        self.assertNotIn('private', json.dumps(result))
        self.assertIn('text', event, 'Filtering must not destroy the native input event')

    def test_thinking_event_is_omitted_entirely(self):
        self.assertIsNone(public_event({'type': 'thinking', 'sessionId': SESSION_A,
                                        'text': 'private chain of thought',
                                        'content': 'private reasoning'}))

    def test_no_event_can_copy_private_payload_keys(self):
        forbidden = {'text', 'arguments', 'content', 'reasoning', 'thinking'}
        for kind in ('message', 'assistant', 'tool_call', 'tool_result', 'error',
                     'response', 'usage', 'unknown_future_event'):
            event = {'type': kind, 'sessionId': SESSION_A,
                     'text': 'PRIVATE-TEXT', 'arguments': {'a': 'PRIVATE-ARGS'},
                     'content': [{'text': 'PRIVATE-CONTENT'}],
                     'reasoning': 'PRIVATE-REASONING', 'thinking': 'PRIVATE-THINKING',
                     'metadata': {'content': 'PRIVATE-NESTED'}}
            with self.subTest(kind=kind):
                result = public_event(event)
                if result is not None:
                    self.assertIsInstance(result, dict)
                    self.assertTrue(forbidden.isdisjoint(result))
                    self.assertNotIn('PRIVATE-', json.dumps(result))


class SessionLogTests(unittest.TestCase):
    def test_missing_or_non_native_log_has_no_resumable_id(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'agent.log'
            self.assertIsNone(session_from_log(path))
            path.write_text('\n'.join((
                'CORAL session: ' + SESSION_A,
                json.dumps({'type': 'log', 'sessionId': SESSION_A}),
                json.dumps({'type': 'coral', 'message': {'type': 'session',
                                                        'sessionId': SESSION_A}}),
                'not valid JSON',
                json.dumps({'type': 'assistant', 'text': SESSION_A}),
            )), encoding='utf-8')
            self.assertIsNone(session_from_log(path))

    def test_repeated_same_native_marker_is_valid(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'agent.log'
            marker = json.dumps({'type': 'session', 'sessionId': SESSION_A,
                                 'cwd': '/work/research'})
            path.write_text('CORAL: starting\n' + marker + '\n' +
                            json.dumps({'type': 'thinking', 'text': 'private'}) +
                            '\n' + marker + '\n', encoding='utf-8')
            self.assertEqual(session_from_log(path), SESSION_A)

    def test_conflicting_native_markers_refuse_to_guess(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'agent.log'
            path.write_text('\n'.join(json.dumps({'type': 'session', 'sessionId': sid})
                                      for sid in (SESSION_A, SESSION_B)),
                            encoding='utf-8')
            with self.assertRaises(ValueError):
                session_from_log(path)

    def test_malformed_native_marker_is_refused_even_after_valid_marker(self):
        for invalid in (None, '', 'session-invalid', SESSION_A + '\n'):
            with self.subTest(invalid=invalid), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / 'agent.log'
                path.write_text('\n'.join(json.dumps({'type': 'session', 'sessionId': sid})
                                          for sid in (SESSION_A, invalid)), encoding='utf-8')
                with self.assertRaises(ValueError):
                    session_from_log(path)


class PrivateSessionPointerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.worktree = self.base / 'agent-worktree'
        self.worktree.mkdir()
        self.state_root = self.base / 'manager-private'

    def save(self, session_id=SESSION_A):
        save_session(self.worktree, 'captain-nemo', session_id,
                     state_root=self.state_root)

    def read(self, agent_id='captain-nemo'):
        return saved_session(self.worktree, agent_id, state_root=self.state_root)

    def test_missing_pointer_does_not_invent_session(self):
        self.assertIsNone(self.read())

    def test_pointer_round_trip_is_manager_private_and_bound_to_agent(self):
        self.save()
        self.assertEqual(self.read(), SESSION_A)
        path = state_path(self.worktree, self.state_root)
        self.assertTrue(path.is_file())
        self.assertTrue(path.resolve().is_relative_to(self.state_root.resolve()))
        self.assertFalse(path.resolve().is_relative_to(self.worktree.resolve()))
        self.assertFalse((self.worktree / '.dsh').exists())
        with self.assertRaises(ValueError):
            self.read('another-agent')

    def test_foreign_worktree_pointer_is_rejected(self):
        self.save()
        other = self.base / 'different-worktree'
        other.mkdir()
        destination = state_path(other, self.state_root)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(state_path(self.worktree, self.state_root).read_bytes())
        with self.assertRaises(ValueError):
            saved_session(other, 'captain-nemo', state_root=self.state_root)

    def test_corrupt_json_or_id_is_refused_instead_of_discarding_resume_state(self):
        for corrupt in ('{not-json', '{}', '[]', 'null'):
            with self.subTest(corrupt=corrupt):
                self.save()
                state_path(self.worktree, self.state_root).write_text(corrupt,
                                                                     encoding='utf-8')
                with self.assertRaises(ValueError):
                    self.read()
        self.save()
        path = state_path(self.worktree, self.state_root)
        original = path.read_text(encoding='utf-8')
        self.assertIn(SESSION_A, original)
        path.write_text(original.replace(SESSION_A, 'session-invalid'), encoding='utf-8')
        with self.assertRaises(ValueError):
            self.read()

    def test_invalid_save_cannot_overwrite_existing_valid_pointer(self):
        self.save()
        before = state_path(self.worktree, self.state_root).read_bytes()
        with self.assertRaises(ValueError):
            self.save('session-invalid')
        self.assertEqual(state_path(self.worktree, self.state_root).read_bytes(), before)
        self.assertEqual(self.read(), SESSION_A)

    def test_agent_owned_worktree_cannot_hold_manager_resume_state(self):
        for unsafe in (self.worktree, self.worktree / '.dsh' / 'session-state'):
            with self.subTest(unsafe=str(unsafe)), self.assertRaises(ValueError):
                private_state_root(self.worktree, unsafe)

    def test_symlink_state_root_is_rejected_before_reading_pointer(self):
        target = self.base / 'actual-private-state'
        target.mkdir()
        try:
            self.state_root.symlink_to(target, target_is_directory=True)
        except OSError as error:
            self.skipTest('Creating a directory symlink is unavailable: ' + str(error))
        with self.assertRaises(ValueError):
            private_state_root(self.worktree, self.state_root)
        with self.assertRaises(ValueError):
            self.read()
        self.assertFalse(list(target.iterdir()))

    def test_symlink_state_parent_is_rejected(self):
        actual_parent = self.base / 'actual-manager'
        actual_parent.mkdir()
        link_parent = self.base / 'manager-link'
        try:
            link_parent.symlink_to(actual_parent, target_is_directory=True)
        except OSError as error:
            self.skipTest('Creating a directory symlink is unavailable: ' + str(error))
        with self.assertRaises(ValueError):
            private_state_root(self.worktree, link_parent / 'session-state')

    def validate_unix_state(self, *, root_uid=24680, root_mode=0o700,
                            parent_uid=24680, parent_mode=0o700):
        """Exercise Unix stat policy on Windows too, without changing host os.name."""
        self.state_root.mkdir(exist_ok=True)
        original_stat = Path.stat
        state_root = self.state_root.absolute()
        parent = state_root.parent

        def ownership_stat(path, *, follow_symlinks=True):
            result = original_stat(path, follow_symlinks=follow_symlinks)
            if path == state_root:
                return SimpleNamespace(st_uid=root_uid,
                                       st_mode=stat.S_IFDIR | root_mode)
            if path == parent:
                return SimpleNamespace(st_uid=parent_uid,
                                       st_mode=stat.S_IFDIR | parent_mode)
            return result

        # Patch only this module's os reference. Mutating the shared os.name
        # would make pathlib choose an unsupported Path class on Windows.
        unix_os = SimpleNamespace(name='posix', geteuid=lambda: 24680)
        with mock.patch.object(dsh_runtime, 'os', unix_os), \
                mock.patch.object(Path, 'stat', ownership_stat):
            return private_state_root(self.worktree, self.state_root)

    def test_unix_policy_accepts_only_manager_owned_private_state(self):
        self.assertEqual(self.validate_unix_state(), self.state_root.absolute())

    def test_unix_policy_rejects_foreign_owned_state(self):
        with self.assertRaises(ValueError):
            self.validate_unix_state(root_uid=24681)

    def test_unix_policy_rejects_group_or_world_readable_state(self):
        for mode in (0o740, 0o704, 0o750, 0o705, 0o777):
            with self.subTest(mode=oct(mode)), self.assertRaises(ValueError):
                self.validate_unix_state(root_mode=mode)

    def test_unix_policy_rejects_parent_writable_by_other_accounts(self):
        for mode in (0o770, 0o702, 0o1777):
            with self.subTest(mode=oct(mode)), self.assertRaises(ValueError):
                self.validate_unix_state(parent_mode=mode)

    def test_unix_policy_rejects_foreign_owned_parent(self):
        with self.assertRaises(ValueError):
            self.validate_unix_state(parent_uid=24681)

    @unittest.skipUnless(os.name == 'posix', 'Unix privacy mode contract')
    def test_manager_state_is_not_readable_by_the_agent_user(self):
        self.save()
        self.assertEqual(stat.S_IMODE(self.state_root.stat().st_mode), 0o700)
        path = state_path(self.worktree, self.state_root)
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)


class ImportBoundaryTests(unittest.TestCase):
    def test_runtime_import_does_not_require_or_import_coral(self):
        code = '''
import importlib.abc
import sys
class BlockCoral(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'coral' or fullname.startswith('coral.'):
            raise AssertionError('Native DSH helpers must not import CORAL')
sys.meta_path.insert(0, BlockCoral())
import sage.autonomous.dsh_runtime
'''
        result = subprocess.run([sys.executable, '-c', code], capture_output=True,
                                text=True, cwd=Path(__file__).resolve().parents[1],
                                timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == '__main__':
    unittest.main()
