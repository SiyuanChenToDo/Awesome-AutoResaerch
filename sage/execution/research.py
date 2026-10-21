"""Frozen research task contract and real CORAL execution capability."""
import hashlib
import json
import math
import os
from pathlib import Path
import signal
import subprocess
import time
from ..artifacts import atomic_json, atomic_text
from ..checkpoints import code_version, digest
from ..errors import BudgetExceeded, ConfigurationError
from .sr_benchmark import ARMS, BENCHMARKS, PRIMARY_MINIMUM_EFFECT, PRIMARY_HOLM_ALPHA, validate_policy


def protocol(*, development_seeds=(101,102,103), confirmation_seeds=tuple(range(1001,1009)),
             population=40, generations=20):
    return {'schema_version':'sage.sr_protocol.v1','protocol_id':'sevh-bounded-v1',
        'benchmarks':list(BENCHMARKS),'arms':list(ARMS),
        'development_seeds':list(development_seeds),'confirmation_seeds':list(confirmation_seeds),
        'population':population,'generations':generations,'max_policy_attempts':2,
        'primary_metric':'mean_paired_test_r2_delta_probe_verified_minus_lsh_only',
        'minimum_effect':PRIMARY_MINIMUM_EFFECT,'bootstrap_repeats':2000,'holm_alpha':PRIMARY_HOLM_ALPHA,'complexity_match_max_ks':.25,
        'selection':'highest_mean_development_validation_r2_probe_verified_first_on_tie',
        'confirmation_accesses':1,'stopping':'fixed_grid_or_fail_closed_on_timeout_integrity_failure',
        'budget_basis':'same_population_generations_and_fitness_calls_extra_probe_cost_reported',
        'scope':'owned_analytic_benchmarks_owned_LSH_proxy_no_LM_no_PTC2_not_paper_reproduction',
        'limitations':['fixed_function_set_add_sub_mul_sin_cos','no_external_dataset',
                      'no_independent_reviewer_or_holdout_custodian','small_seed_count_no_power_claim',
                      'complexity_controls_are_fixed_penalty_ladder_matching_not_guaranteed'],
        'suite_timeout_seconds':1200,'max_total_execution_seconds':3600,
        'program_sha256':hashlib.sha256(Path(__file__).with_name('sr_benchmark.py').read_bytes()).hexdigest(),
        'sage_code_sha256':code_version()}


def validate_protocol(value):
    if not isinstance(value,dict): raise ConfigurationError('Research protocol must be an object')
    try:
        dev=value['development_seeds'];confirm=value['confirmation_seeds']
        if not isinstance(dev,list) or not isinstance(confirm,list) or not 2<=len(dev)<=5 or not 4<=len(confirm)<=12:
            raise ValueError
        if any(type(s) is not int or not 0<=s<1000000 for s in dev+confirm) or len(set(dev+confirm))!=len(dev+confirm):
            raise ValueError
        if type(value['population']) is not int or not 20<=value['population']<=80: raise ValueError
        if type(value['generations']) is not int or not 5<=value['generations']<=60: raise ValueError
        expected=protocol(development_seeds=dev,confirmation_seeds=confirm,
                          population=value['population'],generations=value['generations'])
        if value!=expected: raise ValueError
    except (KeyError,TypeError,ValueError):
        raise ConfigurationError('Protocol differs from supported frozen research contract') from None
    return value


def _kill_group(process):
    """The trusted CORAL worker and evaluator inherit this owned POSIX group."""
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


def _communicate(process, payload, deadline, cancel_event=None):
    """Enforce the same deadline inside the worker thread, not an asyncio timeout.

    Cancelling to_thread alone cannot stop a subprocess. Polling communicate is
    bounded and lets the coroutine request process-group termination on cancel.
    The pinned CORAL grader and owned evaluator do not detach from this group.
    """
    first=True
    reason=None
    try:
        while True:
            remaining=deadline-time.monotonic()
            if cancel_event is not None and cancel_event.is_set():
                reason='cancelled';break
            if remaining <= 0:
                reason='deadline';break
            try:
                stdout,stderr=process.communicate(payload if first else None,
                    timeout=min(.25,remaining))
                return stdout,stderr,None
            except subprocess.TimeoutExpired:
                first=False
        _kill_group(process)
        stdout,stderr=process.communicate(timeout=5)
        return stdout,stderr,reason
    finally:
        # Also remove an orphaned evaluator if the CORAL parent fails early.
        _kill_group(process)
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def native_evaluate(contract, policy, phase, *, destination, coral_python, candidate_python,
                    allow_execution=False, approved_protocol_digest=None,
                    deadline=None, cancel_event=None):
    validate_protocol(contract);validate_policy(policy)
    if not allow_execution or approved_protocol_digest!=digest(contract):
        raise ConfigurationError('Execution requires exact frozen protocol opt-in')
    if deadline is not None and (type(deadline) not in (int,float) or not math.isfinite(deadline)):
        raise ConfigurationError('Execution deadline must be a finite monotonic timestamp')
    if deadline is not None and time.monotonic() >= deadline:
        raise BudgetExceeded('Shared run deadline reached before execution')
    if cancel_event is not None and cancel_event.is_set():
        raise BudgetExceeded('Research execution cancelled before launch')
    if phase not in ('development','confirmation') or os.name!='posix':
        raise ConfigurationError('Research execution requires Linux and a supported phase')
    candidate_python=Path(candidate_python)
    if not candidate_python.is_absolute() or not candidate_python.is_file() or candidate_python.is_symlink():
        raise ConfigurationError('Candidate interpreter must be a reviewed absolute regular file')
    dest=Path(destination);dest.mkdir(mode=0o700,exist_ok=False)
    private=dest/'private';private.mkdir(mode=0o700)
    integration=Path(__file__).parents[1]/'integrations'
    for name in ('coral_research_grader.py',): (private/name).write_bytes((integration/name).read_bytes())
    program=private/'sr_benchmark.py';program.write_bytes(Path(__file__).with_name('sr_benchmark.py').read_bytes())
    request={'contract':contract,'policy':policy,'phase':phase}
    atomic_json(dest/'request.json',request)
    payload={'task_id':contract['protocol_id'],'timeout':contract['suite_timeout_seconds']+30,
        'entrypoint':'coral_research_grader:Grader','private_dir':str(private),'codebase_path':str(private),
        'args':{'program_path':str(program),'program_sha256':contract['program_sha256'],
                'candidate_python':str(candidate_python),'candidate_python_sha256':hashlib.sha256(candidate_python.read_bytes()).hexdigest(),
                'request':request,'timeout':contract['suite_timeout_seconds']}}
    env={k:v for k,v in os.environ.items() if k in ('PATH','LANG','TMP','TEMP')};env['PYTHONPATH']=str(private)
    started=time.monotonic()
    effective_deadline=min(started+contract['suite_timeout_seconds']+45,
                           deadline if deadline is not None else float('inf'))
    receipt={'status':'failed','phase':phase,'protocol_digest':digest(contract),'policy_digest':digest(policy),
             'elapsed_seconds':0.0,'exit_code':None,'deadline_monotonic':effective_deadline}
    # Preparing the immutable program and request is part of the same budget.
    if effective_deadline <= time.monotonic() or (cancel_event is not None and cancel_event.is_set()):
        receipt['termination_reason']='deadline_or_cancellation_before_launch'
        atomic_json(dest/'receipt.json',receipt)
        raise BudgetExceeded('Shared run deadline or cancellation reached before process launch')
    process=subprocess.Popen([str(coral_python),'-c',(integration/'coral_worker.py').read_text(encoding='utf-8')],
        cwd=private,env=env,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,start_new_session=True)
    stdout,stderr,termination=_communicate(process,json.dumps(payload),effective_deadline,cancel_event)
    atomic_text(dest/'coral.stdout',stdout);atomic_text(dest/'coral.stderr',stderr[:8000])
    receipt.update(elapsed_seconds=time.monotonic()-started,exit_code=process.returncode,
                   termination_reason=termination)
    if termination:
        atomic_json(dest/'receipt.json',receipt)
        raise BudgetExceeded('Research execution stopped at its deadline or cancellation; raw attempt retained')
    try:
        value=json.loads(stdout)
        if process.returncode or value['native_api']!='coral.grader.subprocess_grader.SubprocessGrader.grade': raise ValueError
        metadata=value['bundle']['metadata']
        if metadata['candidate_status']!='measured': raise ValueError
        measurements=metadata.pop('measurements')
        atomic_json(dest/'measurements.json',measurements)
        receipt.update(status='measured',native_receipt=value,
                       measurements_digest=digest(measurements))
        validate_protocol(contract)
    except (KeyError,ValueError,TypeError):
        atomic_json(dest/'receipt.json',receipt)
        raise ConfigurationError('Native CORAL research execution failed; raw attempt retained') from None
    atomic_json(dest/'receipt.json',receipt)
    return measurements,receipt
