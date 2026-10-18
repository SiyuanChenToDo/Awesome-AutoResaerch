"""Native CORAL TaskGrader for a trusted owned SR training/evaluation program.

Model output is policy data only. The child is non-root, has no API environment,
and receives no ability to replace the evaluator. Resource limits are not a
network sandbox; this runner does not execute arbitrary model-generated code.
"""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
from coral.grader.task_grader import TaskGrader
from coral.types import Score, ScoreBundle

BOOTSTRAP = '''import resource,runpy,sys
resource.setrlimit(resource.RLIMIT_CPU,(1200,1200))
resource.setrlimit(resource.RLIMIT_AS,(2147483648,2147483648))
resource.setrlimit(resource.RLIMIT_FSIZE,(67108864,67108864))
resource.setrlimit(resource.RLIMIT_NOFILE,(32,32))
resource.setrlimit(resource.RLIMIT_CORE,(0,0))
runpy.run_path(sys.argv[1],run_name='__main__')
'''


class Grader(TaskGrader):
    def evaluate(self):
        import pwd
        if os.getuid()!=0: raise RuntimeError('Requires trusted root manager and non-root child')
        user=pwd.getpwnam('nobody')
        if user.pw_uid==0: raise RuntimeError('Invalid child identity')
        program=Path(self.args['program_path']); python=Path(self.args['candidate_python'])
        for path,key in ((program,'program_sha256'),(python,'candidate_python_sha256')):
            if hashlib.sha256(path.read_bytes()).hexdigest()!=self.args[key]:
                raise ValueError('Frozen executable changed')
        with tempfile.TemporaryDirectory(prefix='sage-sr-training-') as directory:
            work=Path(directory);work.chmod(0o755)
            script=work/'benchmark.py';script.write_bytes(program.read_bytes());script.chmod(0o444)
            with tempfile.TemporaryFile() as stdout,tempfile.TemporaryFile() as stderr:
                process=subprocess.Popen([str(python),'-I','-c',BOOTSTRAP,str(script)],
                    stdin=subprocess.PIPE,stdout=stdout,stderr=stderr,cwd=work,
                    user=user.pw_uid,group=user.pw_gid,extra_groups=[],
                    env={'PATH':'/usr/bin:/bin','LANG':'C.UTF-8','OPENBLAS_NUM_THREADS':'1','OMP_NUM_THREADS':'1'})
                try:
                    process.communicate(json.dumps(self.args['request']).encode(),timeout=self.args['timeout'])
                except subprocess.TimeoutExpired:
                    process.kill();process.communicate()
                stdout.seek(0);raw=stdout.read(67_108_865)
                stderr.seek(0);diagnostic=stderr.read(8000).decode(errors='replace')
        self.eval_logs_dir.mkdir(parents=True,exist_ok=True)
        (self.eval_logs_dir/'measurements.json').write_bytes(raw[:67_108_864])
        (self.eval_logs_dir/'candidate.stderr').write_text(diagnostic,encoding='utf-8')
        metadata={'candidate_uid':user.pw_uid,'candidate_exit_code':process.returncode,
                  'api_credentials_in_child_environment':False,'network_isolation':False,
                  'execution_scope':'owned_trusted_program_with_model_policy_data_only'}
        if process.returncode or len(raw)>67_108_864:
            return ScoreBundle(scores={},aggregated=None,metadata={**metadata,'candidate_status':'training_failed'})
        value=json.loads(raw)
        selected=[r for r in value['records'] if r['arm']=='probe_verified']
        # Development and confirmation grades have explicitly different metrics.
        metric='test_r2' if value['phase']=='confirmation' else 'validation_r2'
        score=sum(r[metric] for r in selected)/len(selected)
        return ScoreBundle(scores={metric:Score(score,metric)},aggregated=score,
            metadata={**metadata,'candidate_status':'measured','measurements':value})
