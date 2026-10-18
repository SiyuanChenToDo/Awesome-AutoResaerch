"""Trusted bridge executed by a dedicated CORAL interpreter, not a fake grader."""
import asyncio
import hashlib
import importlib.metadata
import json
from pathlib import Path
import sys

CORAL_COMMIT='0123dfb939b35228cf2c1fde224cd0561e727408'
PINS={
    'coral/grader/subprocess_grader.py':'6083405d7019f509b6196daec186c9cd6cd07610d52d44e7913e116000e4558c',
    'coral/grader/task_grader.py':'0930c59e8a5d59af3ffbd3313b114f6c724e0230dd3bb7e3859ff7f40e8248cc',
    'coral/types.py':'6910bff1c866072728a74c1ce2747ae8f205f0657f21c981ab25e50c446e09c4'}


def main():
    payload=json.loads(sys.stdin.read())
    import coral
    root=Path(coral.__file__).resolve().parent.parent
    for rel,expected in PINS.items():
        if hashlib.sha256((root/rel).read_bytes().replace(b'\r\n',b'\n')).hexdigest()!=expected:
            raise ValueError('Installed CORAL source pin mismatch')
    from coral.config import GraderConfig
    from coral.grader.subprocess_grader import SubprocessGrader
    from coral.types import Task
    config=GraderConfig(entrypoint='coral_simplifier_grader:Grader',timeout=payload['timeout'],
        direction='maximize',args=payload['args'])
    grader=SubprocessGrader(config.entrypoint,Path(sys.executable),config,payload['private_dir'])
    bundle=asyncio.run(grader.grade(payload['codebase_path'],[Task(payload['task_id'],payload['task_id'],
        'Reviewed synthetic expression simplification development task')]))
    print(json.dumps({'upstream_commit':CORAL_COMMIT,'package_version':importlib.metadata.version('coral'),
        'upstream_file_hashes':PINS,'native_api':'coral.grader.subprocess_grader.SubprocessGrader.grade',
        'bundle':bundle.to_dict()},allow_nan=False))


if __name__=='__main__':
    main()
