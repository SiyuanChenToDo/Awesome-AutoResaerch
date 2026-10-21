"""Optional task-level CORAL runner, separate from the legacy scalar backend.

Calls the real pinned CORAL SubprocessGrader. This first adapter only enables
reviewed integration smoke scripts; it does not start autonomous coding agents.
"""
import json
import math
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import time
from ..artifacts import atomic_json, atomic_text
from ..checkpoints import digest
from ..errors import ConfigurationError
import hashlib


def parse_candidate_script(raw):
    """Explicit code-format adapter; never changes an API failure into success.

    The caller retains the raw response and records any recovery from a rejected
    completion. Syntax validation does not approve execution or prove safety.
    """
    import ast
    if not isinstance(raw,str) or not 1<=len(raw)<=20000:
        raise ConfigurationError('Candidate script response exceeds size/type limit')
    value=raw.strip();kind='plain_python'
    if value.startswith('<code>'):
        match=re.fullmatch(r'<code>(.*?)</code>',value,re.S)
        if not match:raise ConfigurationError('Ambiguous code-tag response')
        value=match.group(1).strip();kind='code_tag'
    elif value.startswith('```'):
        match=re.fullmatch(r'```(?:python|py)?\s*\n(.*?)\n```',value,re.S)
        if not match:raise ConfigurationError('Expected exactly one Python code block')
        value=match.group(1).strip();kind='python_fence'
    try:ast.parse(value)
    except (SyntaxError,ValueError):raise ConfigurationError('Candidate response is not a complete Python script') from None
    code=value+'\n'
    return {'code':code,'input_format':kind,'raw_response_sha256':hashlib.sha256(raw.encode()).hexdigest(),
            'script_sha256':hashlib.sha256(code.encode()).hexdigest()}


def file_digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def validate_contract(value):
    required={'schema_version','purpose','task_id','proposal_sha256','dataset_path','dataset_sha256',
              'grader_sha256','candidate_python','candidate_python_sha256','candidates','max_attempts','attempt_timeout_seconds','max_wall_seconds'}
    if not isinstance(value,dict) or set(value)!=required or value['schema_version']!='sage.coral_task.v1' or value['purpose']!='reviewed_integration_smoke':
        raise ConfigurationError('Only the reviewed CORAL integration smoke contract is currently supported')
    if not re.fullmatch(r'[a-zA-Z0-9_-]{1,64}',value['task_id']):
        raise ConfigurationError('Invalid task ID')
    for k in ('proposal_sha256','dataset_sha256','grader_sha256','candidate_python_sha256'):
        if not isinstance(value[k],str) or not re.fullmatch(r'[a-f0-9]{64}',value[k]):
            raise ConfigurationError('Frozen task digests required')
    for k,low,high in [('max_attempts',1,10),('attempt_timeout_seconds',8,60),('max_wall_seconds',8,600)]:
        if type(value[k]) is not int or not low<=value[k]<=high:
            raise ConfigurationError('Invalid CORAL task budget')
    candidates=value['candidates']
    if not isinstance(candidates,list) or not 1<=len(candidates)<=value['max_attempts']:
        raise ConfigurationError('Candidate count exceeds contract')
    seen=set()
    for row in candidates:
        if not isinstance(row,dict) or set(row)!={'attempt_id','parent_attempt_id','script_path','script_sha256'} or not re.fullmatch(r'[a-zA-Z0-9_-]{1,64}',row['attempt_id']) or row['attempt_id'] in seen:
            raise ConfigurationError('Invalid candidate identity')
        if row['parent_attempt_id'] is not None and row['parent_attempt_id'] not in seen:
            raise ConfigurationError('Unknown parent attempt')
        if not isinstance(row['script_sha256'],str) or not re.fullmatch(r'[a-f0-9]{64}',row['script_sha256']):
            raise ConfigurationError('Frozen candidate digest required')
        seen.add(row['attempt_id'])
    paths=[value['dataset_path']]+[r['script_path'] for r in candidates]
    for path in paths:
        p=Path(path)
        if not p.is_absolute() or not p.is_file() or any(q.is_symlink() for q in (p,*p.parents)) or p.stat().st_size>2_000_000:
            raise ConfigurationError('Task inputs must be bounded existing absolute files without symlinks')
    if file_digest(value['dataset_path'])!=value['dataset_sha256']:
        raise ConfigurationError('Dataset digest mismatch')
    interpreter=Path(value['candidate_python'])
    if not interpreter.is_absolute() or not interpreter.is_file() or interpreter.is_symlink() or file_digest(interpreter)!=value['candidate_python_sha256']:
        raise ConfigurationError('Reviewed candidate interpreter digest mismatch')
    grader=Path(__file__).with_name('coral_simplifier_grader.py')
    if file_digest(grader)!=value['grader_sha256']:
        raise ConfigurationError('Reviewed grader digest mismatch')
    for row in candidates:
        if file_digest(row['script_path'])!=row['script_sha256']:
            raise ConfigurationError('Candidate digest mismatch')
    return value


def run_coral_task(contract, *, python, destination, allow_execution=False, approved_digest=None):
    validate_contract(contract)
    if allow_execution is not True or approved_digest!=digest(contract):
        raise ConfigurationError('CORAL requires explicit execution opt-in and the exact reviewed contract digest')
    if os.name!='posix':
        raise ConfigurationError('The reviewed CORAL task adapter currently requires Linux')
    destination=Path(destination)
    result={'schema_version':'sage.coral_result.v1','status':'running','contract_digest':digest(contract),
        'proposal_sha256':contract['proposal_sha256'],'purpose':contract['purpose'],'attempts':[],
        'selected_attempt_id':None,'scientific_validation':'not_performed',
        'execution_scope':'reviewed_scripts_via_native_CORAL_grader_no_agent_pool',
        'usage':{'attempts_started':0,'elapsed_seconds':0},'errors':[]}
    from ..checkpoints import code_version
    result['sage_code_sha256']=code_version()
    private=destination/'private';private.mkdir(mode=0o700)
    grader=Path(__file__).with_name('coral_simplifier_grader.py')
    # Freeze the reviewed grader and data; private paths are not supplied to candidate code.
    shutil.copyfile(grader,private/grader.name)
    shutil.copyfile(contract['dataset_path'],private/'dataset.json')
    atomic_json(destination/'contract.json',contract)
    started=time.monotonic();best=None
    for item in contract['candidates']:
        remaining=contract['max_wall_seconds']-(time.monotonic()-started)
        if remaining<1:
            result['status']='budget_exhausted';break
        attempt={**item,'status':'started','metrics':{},'errors':[],'parent_attempt_id':item['parent_attempt_id']}
        result['attempts'].append(attempt);result['usage']['attempts_started']+=1
        atomic_json(destination/'result.partial.json',result)
        path=destination/item['attempt_id'];path.mkdir(mode=0o700)
        shutil.copyfile(item['script_path'],path/'solution.py')
        payload={'task_id':contract['task_id'],'timeout':contract['attempt_timeout_seconds']-1,
            'private_dir':str(private),'codebase_path':str(path),
            'args':{'dataset_path':str(private/'dataset.json'),'dataset_sha256':contract['dataset_sha256'],
                    'script_sha256':item['script_sha256'],'candidate_python':contract['candidate_python'],
                    'candidate_python_sha256':contract['candidate_python_sha256']}}
        env={k:v for k,v in os.environ.items() if k in ('PATH','LANG','SYSTEMROOT','TMP','TEMP')}
        env['PYTHONPATH']=str(private)
        # Dedicated group allows termination of the CORAL worker and its children together.
        try:
            # -c keeps this adapter's coral.py off sys.path[0], so import coral
            # resolves the installed upstream package rather than this file.
            process=subprocess.Popen([str(python),'-c',Path(__file__).with_name('coral_worker.py').read_text(encoding='utf-8')],
                cwd=private,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
                text=True,env=env,start_new_session=True)
        except OSError:
            attempt.update(status='grader_error',errors=[{'code':'coral_runtime_unavailable'}])
            result['usage']['elapsed_seconds']=round(time.monotonic()-started,6)
            atomic_json(destination/'result.partial.json',result)
            continue
        try:
            stdout,stderr=process.communicate(json.dumps(payload),timeout=min(remaining,contract['attempt_timeout_seconds']))
            atomic_text(path/'coral.stdout',stdout[:1_048_576]);atomic_text(path/'coral.stderr',stderr[:8000])
            if process.returncode or len(stdout)>1_048_576:
                raise ValueError
            response=json.loads(stdout)
            if response.get('native_api')!='coral.grader.subprocess_grader.SubprocessGrader.grade':
                raise ValueError
            bundle=response['bundle'];score=bundle['aggregated'];metadata=bundle.get('metadata',{})
            if score is not None and (isinstance(score,bool) or not isinstance(score,(int,float)) or not math.isfinite(score)):
                raise ValueError
            status=metadata.get('candidate_status')
            attempt.update(status=status if status in ('measured','semantic_failure','invalid_output','script_rejected','candidate_timeout','candidate_process_failed') else 'grader_error',
                metrics=bundle['scores'],aggregate=score,metadata=metadata,
                upstream={k:v for k,v in response.items() if k!='bundle'})
            if attempt['status']=='measured' and score is not None and (best is None or score>best):
                best=score;result['selected_attempt_id']=item['attempt_id']
        except subprocess.TimeoutExpired:
            os.killpg(process.pid,signal.SIGKILL);stdout,stderr=process.communicate()
            attempt.update(status='grader_timeout',errors=[{'code':'outer_timeout'}])
            atomic_text(path/'coral.stdout',stdout[:1_048_576]);atomic_text(path/'coral.stderr',stderr[:8000])
        except (ValueError,TypeError,KeyError):
            attempt.update(status='grader_error',errors=[{'code':'native_grader_failed'}])
        finally:
            if process.poll() is None:
                os.killpg(process.pid,signal.SIGKILL);process.communicate()
        # Source inputs, grader and private data must remain frozen after every attempt.
        validate_contract(contract)
        if file_digest(private/grader.name)!=contract['grader_sha256'] or file_digest(private/'dataset.json')!=contract['dataset_sha256']:
            raise ConfigurationError('Frozen CORAL grader/data changed during evaluation')
        result['usage']['elapsed_seconds']=round(time.monotonic()-started,6)
        atomic_json(destination/'result.partial.json',result)
    if result['status']=='running':
        result['status']='completed_development' if result['selected_attempt_id'] else 'no_valid_candidate'
    result['usage']['elapsed_seconds']=round(time.monotonic()-started,6)
    atomic_json(destination/'result.json',result)
    return result
