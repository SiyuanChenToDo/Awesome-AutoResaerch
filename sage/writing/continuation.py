"""Read-only handoff from a sealed experiment run to a fresh writing run.

Local hashes establish consistency, not authorship, approval or independent
science. Writing never reruns the final test or imports saved candidate code.
"""
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
from ..checkpoints import digest
from ..errors import ConfigurationError


def prepare_report_inputs(directory):
    root=Path(directory).absolute()
    if not root.is_dir() or any(p.is_symlink() for p in (root,*root.parents)):
        raise ConfigurationError('Writing input must be an existing non-symlink run directory')
    def read(name):
        p=root/name
        if p.stat().st_size>64_000_000: raise ConfigurationError('Saved report input exceeds size bound')
        return json.loads(p.read_text(encoding='utf-8'))
    try:
        manifest=read('manifest.json')
        if not isinstance(manifest,dict) or not 1<=len(manifest)<=256: raise ValueError
        total=0
        for name,row in manifest.items():
            rel=PurePosixPath(name)
            if rel.is_absolute() or '..' in rel.parts or '\\' in name or not isinstance(row,dict): raise ValueError
            path=root.joinpath(*rel.parts)
            if not path.resolve().is_relative_to(root.resolve()): raise ValueError
            if any(p.is_symlink() for p in (path,*path.parents)) or not path.is_file(): raise ValueError
            if type(row['bytes']) is not int or not 0<=row['bytes']<=64_000_000 or path.stat().st_size!=row['bytes']: raise ValueError
            total+=row['bytes']
            if total>512_000_000: raise ValueError
            if not re.fullmatch('[a-f0-9]{64}',row['sha256']) or hashlib.sha256(path.read_bytes()).hexdigest()!=row['sha256']: raise ValueError
        required={'result.json','proposal.json','protocol.json','selection.json','analysis.json',
                  'confirmation/receipt.json','confirmation/measurements.json'}
        if not required<=set(manifest): raise ValueError
        parent=read('result.json');contract=read('protocol.json');selection=read('selection.json')
        proposal=read('proposal.json');analysis=read('analysis.json');measurements=read('confirmation/measurements.json')
        receipt=read('confirmation/receipt.json')
        if parent['schema_version']!='sage.closed_loop.v1' or parent['status']!='completed_closed_loop': raise ValueError
        if not parent.get('closure_checks') or not all(v is True for v in parent['closure_checks'].values()): raise ValueError
        if parent['proposal']!=proposal or parent['analysis']!=analysis or parent['selection']!=selection: raise ValueError
        if selection['proposal_digest']!=digest(proposal) or selection['protocol_digest']!=digest(contract): raise ValueError
        if selection['policy_digest']!=digest(measurements['policy']) or receipt['measurements_digest']!=digest(measurements): raise ValueError
        from ..execution.sr_benchmark import validate_policy
        policy=validate_policy(selection['policy'])
        if policy!=measurements['policy'] or receipt['policy_digest']!=digest(policy) or receipt['protocol_digest']!=digest(contract): raise ValueError
        if not isinstance(parent['development_attempts'],list) or not 1<=len(parent['development_attempts'])<=2: raise ValueError
        import math
        for attempt in parent['development_attempts']:
            if (not isinstance(attempt['attempt_id'],str) or attempt['status']!='measured' or
                type(attempt['selection_score']) not in (int,float) or not math.isfinite(attempt['selection_score'])): raise ValueError
        # Recompute saved statistics only. No new training, test selection or inference.
        from ..execution.sr_benchmark import analyze
        program=Path(__file__).parents[1]/'execution'/'sr_benchmark.py'
        if hashlib.sha256(program.read_bytes()).hexdigest()!=contract['program_sha256']: raise ValueError
        if analyze(measurements,bootstrap_repeats=contract['bootstrap_repeats'])!=analysis: raise ValueError
    except (KeyError,TypeError,ValueError,OSError):
        raise ConfigurationError('Saved experiment integrity or supported-evaluator check failed; no model calls made') from None
    details={'writing_scope':'full_manuscript_from_recorded_research',
        'authority':'Frozen execution contract and saved measurements describe what ran; free-text proposals describe unexecuted ambitions.',
        'selected_policy':policy,
        'functions':{'polynomial':'x + x*x + x*x*x','trigonometric':'sin(x) + sin(x*x+x)',
                     'interaction':'x*x+x*y+y*y'},
        'inputs':'Two inputs uniform in [-1,1] for train/validation/test and input-only probes; independent uniform [-2,2] OOD diagnostic.',
        'split_sizes':{'train':48,'validation':48,'test':192,'ood':192,'available_probes':64},
        'operators':['add','sub','mul','sin','cos'],
        'search':'Uniform fixed constants and variables; bounded random-tree initialization; tournament size 3; elitism; crossover probability 0.6 otherwise subtree mutation; size cap 63 and path depth cap 10. No PTC2 or LM optimization.',
        'hash':'Owned random-hyperplane sign-vector LSH on training-input subtree outputs plus round(log1p(L2 norm),1) bucket. Not the cited source implementation.',
        'gate':'For a strictly smaller same-bucket candidate, max |before-after|/(1+|before|) across input-only probes must be <= selected epsilon. Equality is a retrieval condition, not a necessary or sufficient condition for global semantic equivalence.',
        'exact_probe':'array_equal on the same finite probe outputs. With selected epsilon=0, probe_verified and exact_probe have identical acceptance predicates on finite values; identical outcomes are expected, not an independent ablation.',
        'semantic_audit':'Post-hoc on saved accepted substitutions and independent test inputs, count max normalized residual > selected epsilon. With zero tolerance a floating-point residual can count as a violation; it is not calibrated formal equivalence.',
        'penalties':{'size_penalty_small':.001,'size_penalty_large':.01},
        'selection':'Within each run, choose a generation champion using validation MSE. Between two policy attempts, choose highest mean development validation R2 for probe_verified before the sole confirmation grid.',
        'unexecuted_controls':['calibration false-positive sweeps','matched random-rejection control','collision-floor go/no-go program','external-dataset paper-scale reproduction'],
        'claim_boundary':'Write a complete research manuscript. Distinguish executed evidence from proposed controls. Establish each contribution with its evidence; do not assert unsupported novelty, causal attribution, global equivalence, adequate power or independent replication.'}
    execution={'status':'completed_bounded_experiment','fixture':False,'dry_run':False,
        'contract':contract,'contract_digest':digest(contract),'selected_attempt_id':selection['selected_attempt_id'],
        'research_analysis':analysis,'research_details':details,
        'attempts':[{'attempt_id':a['attempt_id'],'status':a['status'],'code_sha256':contract['program_sha256'],
                     'metrics':{'development_validation_r2':a['selection_score']}} for a in parent['development_attempts']]+
            [{'attempt_id':'confirmation','status':'measured','code_sha256':contract['program_sha256'],
              'metrics':{'confirmation_mean_test_r2':analysis['summaries']['probe_verified']['test_r2']}}]}
    lineage={'parent_manifest_digest':digest(manifest),'parent_result_digest':digest(parent),
        'experiment_sage_code_sha256':contract['sage_code_sha256'],'program_sha256':contract['program_sha256'],
        'proposal_digest':digest(proposal),'analysis_digest':digest(analysis),
        'new_training_runs':0,'new_final_test_accesses':0,
        'scope':'read_only_statistics_recomputation_and_new_writing_not_new_experiment'}
    return proposal,execution,lineage
