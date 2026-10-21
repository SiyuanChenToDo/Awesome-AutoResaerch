"""A finite research loop: grounded proposal -> frozen task -> feedback -> holdout -> report.

The supported task is deliberately specific. A successful closed loop means the
declared bounded experiment and evidence chain completed, never global novelty
or acceptance of a generated hypothesis.
"""
import asyncio
import json
from pathlib import Path
import platform
import statistics
import threading
import time
from ..artifacts import atomic_json, atomic_text
from ..checkpoints import digest, code_version
from ..errors import BudgetExceeded, ConfigurationError, SageError
from ..execution.research import native_evaluate, validate_protocol
from ..execution.sr_benchmark import ARMS, POLICY_SPACE, validate_policy, dev_score, analyze
from ..writing import generate_report
from . import run


def compact_measurements(value):
    # Development feedback never contains test metrics or heldout semantic audits.
    return {arm:{'mean_validation_r2':statistics.mean(r['validation_r2'] for r in value['records'] if r['arm']==arm),
                 'mean_size':statistics.mean(r['final_size'] for r in value['records'] if r['arm']==arm),
                 'accepted':sum(r['accepted'] for r in value['records'] if r['arm']==arm),
                 'gate_rejections':sum(r['gate_rejections'] for r in value['records'] if r['arm']==arm)} for arm in ARMS}


def policy_response(values, previous=None):
    try:
        policy=validate_policy(json.loads(values['policy']))
        if policy==previous: raise ValueError('Feedback revision must try a different permitted policy')
        return policy
    except (ValueError,TypeError) as error:
        from ..errors import InvalidResponse
        raise InvalidResponse(str(error)) from None


async def run_closed_loop(topic, runtime, *, contract, destination, coral_python,
                          candidate_python, allow_execution=False, approved_protocol_digest=None):
    validate_protocol(contract)
    if not allow_execution or approved_protocol_digest!=digest(contract):
        raise ConfigurationError('Closed loop requires execution authorization for exact protocol')
    destination=Path(destination)
    result={'schema_version':'sage.closed_loop.v1','status':'running','stage':'proposal',
            'protocol_digest':digest(contract),'proposal':None,'development_attempts':[],
            'confirmation':None,'analysis':None,'report':None,'errors':[],
            'scientific_validation':'bounded_internal_experiment_pending'}
    started=time.monotonic()
    # Reuse the existing Runtime wall allowance. The frozen execution cap is
    # another ceiling on this same clock, starting at the first execution and
    # never resetting between development, selection and confirmation.
    run_deadline=started+max(0,runtime.remaining())
    execution_deadline=None
    cancelled=False
    atomic_json(destination/'protocol.json',contract)
    atomic_json(destination/'environment.json',{'platform':platform.platform(),'python':platform.python_version(),
        'coral_python':str(coral_python),'candidate_python':str(candidate_python),
        'credential_storage':'transient_parent_environment_only','generated_python_executed':False})

    def publish(stage):
        result['stage']=stage;result['usage']=dict(runtime.usage)
        result['usage']['elapsed_seconds']=time.monotonic()-started
        atomic_json(destination/'result.partial.json',result)
        runtime.event('closed_loop',stage)

    async def evaluate(policy,phase,path):
        nonlocal execution_deadline
        now=time.monotonic()
        if execution_deadline is None:
            execution_deadline=now+contract['max_total_execution_seconds']
        deadline=min(run_deadline,execution_deadline,now+runtime.remaining())
        if deadline <= now:
            raise BudgetExceeded('Shared run or frozen total-execution deadline reached; no experiment started')
        cancel_event=threading.Event()
        task=asyncio.create_task(asyncio.to_thread(native_evaluate,contract,policy,phase,
            destination=path,coral_python=coral_python,candidate_python=candidate_python,
            allow_execution=True,approved_protocol_digest=digest(contract),
            deadline=deadline,cancel_event=cancel_event))
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            # Await native cleanup: cancelling the coroutine does not terminate
            # a thread, its CORAL child or the child evaluator.
            cancel_event.set()
            try:
                await asyncio.shield(task)
            except (SageError,OSError,ValueError):
                pass
            raise

    try:
        proposal=await run(topic,runtime.main_model,runtime.source,cheap_model=runtime.cheap_model,
                           config=runtime.config,mode='live',runtime=runtime)
        result['proposal']=proposal.to_dict();atomic_json(destination/'proposal.json',result['proposal'])
        if not proposal.status.startswith('completed') or proposal.experiment is None:
            result['errors'].extend({'stage':'proposal',**e} for e in proposal.errors)
            raise ConfigurationError('Proposal did not complete; experiment not started')
        publish('design_review')
        context={'selected_idea':proposal.candidates[proposal.selected_index].idea,
                 'proposed_plan':proposal.experiment.proposal,'frozen_bounded_protocol':contract}
        prompt=('Review this already operator-scoped bounded experimental protocol against the proposed idea. '
            'Identify implementation differences, unresolved mechanism claims, comparison fairness and evidence limits. '
            'The proposed plan may be infeasible; do not invent power, replication or independent approval. '
            'Return <review> a JSON object with keys issues (up to 8 short strings) and scope_summary (string) </review>. '
            'You cannot change the frozen protocol. Context: '+json.dumps(context,ensure_ascii=False))
        def validate_review(values):
            from ..errors import InvalidResponse
            try: value=json.loads(values['review'])
            except (ValueError,TypeError): raise InvalidResponse('Review must be JSON') from None
            if (not isinstance(value,dict) or set(value)!={'issues','scope_summary'} or
                not isinstance(value['issues'],list) or len(value['issues'])>8 or
                any(not isinstance(s,str) or len(s)>1200 for s in value['issues']) or
                not isinstance(value['scope_summary'],str) or len(value['scope_summary'])>2400):
                raise InvalidResponse('Invalid bounded protocol review')
        values=await runtime.ask('closed_loop.design_review',prompt,('review',),validate=validate_review,reviewer=True)
        result['design_review']={'model_opinion':json.loads(values['review']),
                                 'independence':'not_established_same_configured_model_family'}
        atomic_json(destination/'design-review.json',result['design_review'])
        previous=None;feedback=None;measurements=[]
        for index in range(contract['max_policy_attempts']):
            publish('policy_generation_'+str(index+1))
            prompt=('Implement the proposed simplification strategy by choosing a typed policy for the owned fixed GP kernel. '
                'No Python, evaluator edits or extra keys. Return <policy>{"hash_bits":64,"probe_count":32,"epsilon":0.0}</policy> '
                'with exactly these keys; allowed values: '+json.dumps(POLICY_SPACE)+'. '
                'Hash matching is an owned random-hyperplane LSH proxy with a norm bucket, not the paper implementation. '
                'probe_verified accepts smaller hash-matched subtrees only if max relative residual on input-only probes <= epsilon. '
                'Iteration two must choose a DIFFERENT permitted policy using only the development feedback. '
                'The primary selection metric is mean development validation R2 for probe_verified. '
                'This is not evidence of novelty. Context: '+json.dumps(context,ensure_ascii=False)+
                '\nPrevious policy: '+json.dumps(previous)+'\nDevelopment feedback: '+json.dumps(feedback))
            values=await runtime.ask('closed_loop.policy',prompt,('policy',),
                                      validate=lambda v:policy_response(v,previous))
            policy=policy_response(values,previous)
            publish('development_'+str(index+1))
            attempt={'attempt_id':'policy-'+str(index+1),'parent_attempt_id':None if index==0 else 'policy-'+str(index),
                     'policy':policy,'policy_digest':digest(policy),'status':'started'}
            result['development_attempts'].append(attempt)
            atomic_json(destination/f'policy-{index+1}.json',policy)
            data,receipt=await evaluate(policy,'development',destination/f'development-{index+1}')
            measurements.append(data)
            feedback=compact_measurements(data)
            attempt.update(status='measured',selection_score=dev_score(data),feedback=feedback,receipt=receipt)
            previous=policy
            atomic_json(destination/f'development-feedback-{index+1}.json',feedback)
            publish('development_feedback_'+str(index+1))
        selected=max(result['development_attempts'],key=lambda a:a['selection_score'])
        selection={'selected_attempt_id':selected['attempt_id'],'policy':selected['policy'],
                   'policy_digest':selected['policy_digest'],'selection_score':selected['selection_score'],
                   'basis':contract['selection'],'protocol_digest':digest(contract),
                   'proposal_digest':digest(result['proposal']),'test_accesses_before_selection':0}
        result['selection']=selection;atomic_json(destination/'selection.json',selection)
        publish('confirmation')
        data,receipt=await evaluate(selected['policy'],'confirmation',destination/'confirmation')
        result['confirmation']=receipt
        analysis=analyze(data,bootstrap_repeats=contract['bootstrap_repeats'])
        result['analysis']=analysis;atomic_json(destination/'analysis.json',analysis)
        claims=[{'claim_id':'H1','wording':'Probe verification improves mean test R2 over the owned LSH-only proxy by at least 0.02.',
                 'status':analysis['primary_claim_status'],'evidence':'analysis.json:contrasts[0]',
                 'scope':analysis['scope']},
                {'claim_id':'H2','wording':'An advantage persists at matched final-size distributions.',
                 'status':'not_established','evidence':'analysis.json:complexity_matching',
                 'reason':'Fixed penalty ladder and KS distances alone do not establish a controlled matched-size causal comparison.'},
                {'claim_id':'H3','wording':'The method is globally novel or reproduces the published method.',
                 'status':'not_established','reason':'Fixed literature corpus and an owned LSH proxy; no independent replication.'}]
        atomic_json(destination/'claims.json',claims)
        publish('writing')
        execution={'status':'completed_bounded_experiment','dry_run':False,'fixture':False,
            'contract':contract,'contract_digest':digest(contract),'selected_attempt_id':selected['attempt_id'],
            'attempts':[{'attempt_id':a['attempt_id'],'status':a['status'],'code_sha256':contract['program_sha256'],
                         'metrics':{'development_validation_r2':a['selection_score']}} for a in result['development_attempts']]+
                       [{'attempt_id':'confirmation','status':'measured','code_sha256':contract['program_sha256'],
                         'metrics':{'confirmation_mean_test_r2':analysis['summaries']['probe_verified']['test_r2']}}],
            'research_analysis':analysis}
        result['report']=await generate_report(runtime,result['proposal'],execution)
        atomic_json(destination/'report.json',result['report'])
        atomic_text(destination/'report.md',result['report']['markdown'])
        atomic_text(destination/'draft.md',result['report'].get('draft_markdown',''))
        publish('closure_audit')
        expected=len(contract['benchmarks'])*len(contract['confirmation_seeds'])*len(ARMS)
        checks={'proposal_completed':proposal.status.startswith('completed'),
            'shared_discussion_completed':isinstance(result['proposal'].get('discussion'),dict) and result['proposal']['discussion'].get('status','').startswith('completed'),
            'claim_reviews_and_native_ARIS_completed':bool(result['proposal']['candidates']) and all(
                c['novelty'].get('review_receipt',{}).get('screening_status')=='completed' and
                c['novelty']['review_receipt'].get('native_aris_gate',{}).get('executed') is True
                for c in result['proposal']['candidates']),
            'all_development_attempts_measured':len(measurements)==contract['max_policy_attempts'],
            'no_heldout_metrics_in_development':all(not any(k in r for k in ('test_r2','ood_r2','heldout_semantic_violations')) for m in measurements for r in m['records']),
            'development_confirmation_seeds_disjoint':not set(contract['development_seeds'])&set(contract['confirmation_seeds']),
            'selection_frozen_before_single_confirmation':json.loads((destination/'selection.json').read_text())==selection and selection['policy_digest']==receipt['policy_digest'],
            'complete_confirmation_grid':len(data['records'])==expected,
            'equal_fitness_evaluation_budget':len({r['fitness_evaluations'] for r in data['records']})==1,
            'native_CORAL_nonroot_without_credentials':receipt['native_receipt']['bundle']['metadata']['candidate_uid']!=0 and not receipt['native_receipt']['bundle']['metadata']['api_credentials_in_child_environment'],
            'protocol_and_source_unchanged':digest(json.loads((destination/'protocol.json').read_text()))==digest(contract) and contract['sage_code_sha256']==code_version(),
            'writing_and_review_completed':result['report']['status'].startswith('completed'),
            'analysis_bound_to_raw_measurements':receipt['measurements_digest']==digest(data),
            'same_policy_for_every_confirmation_arm':data['policy']==selection['policy']}
        result['closure_checks']=checks;result['claims']=claims
        atomic_json(destination/'closure-checks.json',checks)
        result['status']='completed_closed_loop' if all(checks.values()) else 'closure_failed'
        result['scientific_validation']='bounded_internal_experiment_not_independent_replication'
        atomic_text(destination/'reflection.md',
            '# Bounded research loop reflection\n\n'+
            f"H1: {analysis['primary_claim_status']}. Negative and uncertain results are retained.\n\n"+
            'Alternative explanations: probe-gate behavior may be unnecessary when all hash matches are already equivalent; '
            'different search trajectories or unmatched complexity may explain any score gap. '
            'Next independent study: exact upstream implementation, broader external datasets, independently held test sets, '
            'more seeds and a planned power calculation. This run does not admit a general method recommendation into memory.\n')
    except asyncio.CancelledError:
        cancelled=True
        result['status']='cancelled'
        result['errors'].append({'stage':result['stage'],'code':'cancelled'})
    except (SageError,ValueError,OSError) as error:
        result['status']='stopped' if isinstance(error,BudgetExceeded) else 'failed'
        result['errors'].append({'stage':result['stage'],'code':getattr(error,'code',type(error).__name__)})
    if result['errors']:
        for attempt in result['development_attempts']:
            if attempt['status']=='started':
                attempt.update(status='cancelled' if cancelled else 'failed',error=result['errors'][-1]['code'])
    publish('finished')
    result['audit']=list(runtime.audit)
    atomic_json(destination/'result.json',result)
    manifest={str(p.relative_to(destination)):{'bytes':p.stat().st_size,
              'sha256':__import__('hashlib').sha256(p.read_bytes()).hexdigest()}
              for p in sorted(destination.rglob('*')) if p.is_file() and p.name!='manifest.json'}
    atomic_json(destination/'manifest.json',manifest)
    if cancelled:
        raise asyncio.CancelledError
    return result
