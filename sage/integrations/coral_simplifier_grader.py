"""Owned CORAL TaskGrader for a reviewed synthetic expression-simplification task.

No model scores. Correctness at frozen probe points and structural compression
are development measurements, not a proof of symbolic equivalence or novelty.
"""
import ast
import hashlib
import json
import math
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
from coral.grader.task_grader import TaskGrader
from coral.types import Score, ScoreBundle


def audit_script(text):
    tree = ast.parse(text)
    forbidden = {'eval','exec','compile','open','__import__','getattr','setattr','globals','locals','vars','input','breakpoint'}
    attributes = {'load','loads','dump','dumps','stdin','stdout','append','sort'}
    for node in ast.walk(tree):
        if isinstance(node, (ast.ImportFrom, ast.ClassDef, ast.With, ast.AsyncWith)):
            raise ValueError('Unsupported script construct')
        if isinstance(node, ast.Import) and any(n.name not in ('json','sys') for n in node.names):
            raise ValueError('Only json/sys imports permitted for this reviewed smoke task')
        if isinstance(node, ast.Attribute) and node.attr not in attributes:
            raise ValueError('Unsupported attribute access')
        if isinstance(node, ast.Name) and (node.id in forbidden or (node.id.startswith('__') and node.id != '__name__')):
            raise ValueError('Unsupported name')
    return tree


def expression(value, point, depth=0):
    if depth > 20:
        raise ValueError('Expression depth exceeded')
    if type(value) in (int,float) and math.isfinite(value) and abs(value) <= 1e6:
        return float(value), 1
    if isinstance(value,str) and value in ('x','y'):
        return float(point[value]), 1
    if not isinstance(value,list) or len(value) != 3 or value[0] not in ('add','sub','mul'):
        raise ValueError('Invalid expression tree')
    left, ln = expression(value[1],point,depth+1)
    right, rn = expression(value[2],point,depth+1)
    result = left+right if value[0] == 'add' else (left-right if value[0] == 'sub' else left*right)
    if not math.isfinite(result) or ln+rn+1 > 2000:
        raise ValueError('Non-finite or oversized expression')
    return result, ln+rn+1


BOOTSTRAP = '''import resource,runpy,sys
resource.setrlimit(resource.RLIMIT_CPU,(2,2))
resource.setrlimit(resource.RLIMIT_AS,(268435456,268435456))
resource.setrlimit(resource.RLIMIT_FSIZE,(1048576,1048576))
resource.setrlimit(resource.RLIMIT_NOFILE,(32,32))
resource.setrlimit(resource.RLIMIT_CORE,(0,0))
runpy.run_path(sys.argv[1],run_name='__main__')
'''


class Grader(TaskGrader):
    def evaluate(self):
        if os.name != 'posix' or not hasattr(os,'getuid') or os.getuid() != 0:
            raise RuntimeError('Reviewed integration grader requires Linux root manager and a non-root child')
        import pwd
        user = pwd.getpwnam('nobody')
        if user.pw_uid == 0:
            raise RuntimeError('Candidate user must be non-root')
        interpreter=Path(self.args['candidate_python'])
        if hashlib.sha256(interpreter.read_bytes()).hexdigest()!=self.args['candidate_python_sha256']:
            raise RuntimeError('Frozen candidate interpreter changed')
        dataset_path = Path(self.args['dataset_path'])
        data = dataset_path.read_bytes()
        if hashlib.sha256(data).hexdigest() != self.args['dataset_sha256']:
            raise RuntimeError('Frozen dataset digest changed')
        dataset = json.loads(data)
        originals, probes = dataset['expressions'], dataset['probes']
        if not 1 <= len(originals) <= 256 or not 1 <= len(probes) <= 64:
            raise ValueError('Task size outside reviewed limits')
        code = (Path(self.codebase_path)/'solution.py').read_text(encoding='utf-8')
        if hashlib.sha256(code.encode()).hexdigest() != self.args['script_sha256']:
            raise RuntimeError('Frozen candidate digest changed')
        try:
            audit_script(code)
        except (SyntaxError,ValueError):
            return ScoreBundle(scores={},aggregated=None,metadata={'candidate_status':'script_rejected'})
        # Code runs from a readable temporary copy, without access through /root.
        with tempfile.TemporaryDirectory(prefix='sage-reviewed-candidate-') as directory:
            work = Path(directory)
            work.chmod(0o755)
            script = work/'solution.py';script.write_text(code,encoding='utf-8');script.chmod(0o444)
            with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
                process = subprocess.Popen([str(interpreter),'-I','-c',BOOTSTRAP,str(script)],
                    cwd=directory,stdin=subprocess.PIPE,stdout=stdout,stderr=stderr,
                    user=user.pw_uid,group=user.pw_gid,extra_groups=[],
                    env={'PATH':'/usr/bin:/bin','LANG':'C.UTF-8'})
                try:
                    process.communicate(json.dumps({'expressions':originals}).encode(), timeout=4)
                    status = 'completed' if process.returncode == 0 else 'candidate_process_failed'
                except subprocess.TimeoutExpired:
                    process.kill();process.communicate();status='candidate_timeout'
                stdout.seek(0);raw=stdout.read(1_048_577)
                stderr.seek(0);diagnostic=stderr.read(4000).decode(errors='replace')
        self.eval_logs_dir.mkdir(parents=True,exist_ok=True)
        (self.eval_logs_dir/'candidate.stdout').write_bytes(raw[:1_048_576])
        (self.eval_logs_dir/'candidate.stderr').write_text(diagnostic,encoding='utf-8')
        metadata={'candidate_status':status,'candidate_exit_code':process.returncode,'candidate_uid':user.pw_uid,'probe_count':len(probes),
                  'expression_count':len(originals),'stdout_sha256':hashlib.sha256(raw).hexdigest(),
                  'scope':'synthetic_development_measurement_not_formal_equivalence',
                  'network_isolation':False,'api_credentials_in_child_environment':False}
        if status != 'completed' or len(raw)>1_048_576:
            return ScoreBundle(scores={},aggregated=None,metadata=metadata)
        try:
            outputs=json.loads(raw)
            if not isinstance(outputs,list) or len(outputs)!=len(originals):
                raise ValueError
            changes=[];violations=0
            for before,after in zip(originals,outputs):
                bn=an=None
                for point in probes:
                    a,bn=expression(before,point);b,an=expression(after,point)
                    violations += int(not math.isclose(a,b,rel_tol=1e-9,abs_tol=1e-9))
                changes.append((bn-an)/bn)
        except (ValueError,TypeError,KeyError,RecursionError,OverflowError):
            metadata['candidate_status']='invalid_output'
            return ScoreBundle(scores={},aggregated=None,metadata=metadata)
        metadata['semantic_violations']=violations
        metadata['candidate_status']='measured' if not violations else 'semantic_failure'
        score=sum(changes)/len(changes) if not violations else None
        return ScoreBundle(scores={'compression':Score(score,'compression'),
            'semantic_violations':Score(violations,'semantic_violations')},aggregated=score,metadata=metadata)
