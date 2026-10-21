"""Pinned vocabulary installation, with synthetic bytes and no network/code execution."""
import hashlib
import importlib.util
import io
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock
import zipfile


spec = importlib.util.spec_from_file_location('sage_native_setup_test',
    Path(__file__).resolve().parents[1] / 'scripts' / 'setup_autonomous.py')
setup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(setup)


class TokenizerSetupTests(unittest.TestCase):
    def archive(self, vocabulary=b'{"offline_fixture":true}'):
        output = io.BytesIO()
        with zipfile.ZipFile(output, 'w') as archive:
            archive.writestr('deepseek_v4_tokenizer/tokenizer.json', vocabulary)
            archive.writestr('deepseek_v4_tokenizer/deepseek_tokenizer.py', 'raise RuntimeError("Never execute")')
            archive.writestr('../unrequested.txt', 'Never extract unrequested archive members')
        return output.getvalue(), vocabulary

    def test_install_reads_only_verified_json_and_reuses_verified_cache(self):
        raw, vocabulary = self.archive()
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / 'cache' / 'tokenizer.json'
            with mock.patch.dict(os.environ, {'SAGE_DEEPSEEK_V4_TOKENIZER_PATH': str(target)}), \
                 mock.patch.object(setup, 'DEEPSEEK_TOKENIZER_ZIP_SHA256', hashlib.sha256(raw).hexdigest()), \
                 mock.patch.object(setup, 'DEEPSEEK_TOKENIZER_JSON_SHA256', hashlib.sha256(vocabulary).hexdigest()), \
                 mock.patch.object(setup, 'urlopen', return_value=io.BytesIO(raw)) as download:
                self.assertEqual(setup.install_deepseek_tokenizer(), target)
                self.assertEqual(target.read_bytes(), vocabulary)
                self.assertFalse((Path(folder) / 'unrequested.txt').exists())
                self.assertEqual(setup.install_deepseek_tokenizer(), target)
                self.assertEqual(download.call_count, 1)
                self.assertEqual(list(target.parent.iterdir()), [target])

    def test_wrong_archive_is_refused_before_cache_is_written(self):
        raw, _ = self.archive()
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / 'tokenizer.json'
            with mock.patch.dict(os.environ, {'SAGE_DEEPSEEK_V4_TOKENIZER_PATH': str(target)}), \
                 mock.patch.object(setup, 'urlopen', return_value=io.BytesIO(raw)):
                with self.assertRaisesRegex(SystemExit, 'archive checksum'):
                    setup.install_deepseek_tokenizer()
                self.assertFalse(target.exists())

    def test_correct_archive_with_wrong_vocabulary_is_refused(self):
        raw, _ = self.archive()
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / 'tokenizer.json'
            with mock.patch.dict(os.environ, {'SAGE_DEEPSEEK_V4_TOKENIZER_PATH': str(target)}), \
                 mock.patch.object(setup, 'DEEPSEEK_TOKENIZER_ZIP_SHA256', hashlib.sha256(raw).hexdigest()), \
                 mock.patch.object(setup, 'urlopen', return_value=io.BytesIO(raw)):
                with self.assertRaisesRegex(SystemExit, 'vocabulary checksum'):
                    setup.install_deepseek_tokenizer()
                self.assertFalse(target.exists())

    def test_corrupt_cache_is_reported_and_preserved_without_network(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / 'tokenizer.json'
            target.write_bytes(b'corrupt')
            with mock.patch.dict(os.environ, {'SAGE_DEEPSEEK_V4_TOKENIZER_PATH': str(target)}), \
                 mock.patch.object(setup, 'urlopen') as download:
                with self.assertRaisesRegex(SystemExit, 'cache checksum'):
                    setup.install_deepseek_tokenizer()
                self.assertEqual(target.read_bytes(), b'corrupt')
                download.assert_not_called()


if __name__ == '__main__':
    unittest.main()
