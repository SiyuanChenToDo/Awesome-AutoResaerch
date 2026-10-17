import hashlib
import json
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]


class Provenance(unittest.TestCase):
    def test_snapshot_bytes_match_pinned_git_blobs(self):
        base=ROOT/'third_party/agent_laboratory'
        manifest=json.loads((base/'manifest.json').read_text())
        self.assertEqual(manifest['commit'],'d9017d90e329112d2a80b7712f37ee9094d2cd27')
        for entry in manifest['files']:
            with self.subTest(path=entry['path']):
                data=(base/'upstream'/entry['path']).read_bytes()
                self.assertEqual(len(data),entry['bytes'])
                self.assertEqual(hashlib.sha256(data).hexdigest(),entry['sha256'])
                self.assertEqual(hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest(),entry['git_blob_sha'])
        self.assertEqual((ROOT/'LICENSES/Agent-Laboratory-MIT.txt').read_bytes(),(base/'upstream/LICENSE').read_bytes())

if __name__=='__main__':unittest.main()
