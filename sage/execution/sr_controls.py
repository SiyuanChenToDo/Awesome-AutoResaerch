"""Supplementary simplification controls, separate from the sealed v1 study.

The protocol is written before launching new seed clusters. A profile-yoked
random gate matches reference rejection probabilities, not exact trajectories.
Matching failures are measured and retained; they invalidate a matched causal
interpretation. Calibration uses heldout numerical agreement, not proof.
"""
import hashlib
import json
import math
import random
import statistics
import time
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from . import sr_benchmark as base

PROTOCOL = {'schema_version':'sage.sr_controls.v1', 'benchmarks':list(base.BENCHMARKS),
    'seeds':list(range(3001,3025)), 'population':80, 'generations':80,
    'policy':{'hash_bits':64,'probe_count':32,'epsilon':1e-8},
    'arms':['no_simplify','lsh_only','probe_verified','random_rejection'],
    'primary_contrast':'probe_verified minus random_rejection test R2',
    'minimum_effect':.02, 'bootstrap_repeats':10000,
    'matching_max_bin_acceptance_rate_difference':.1,
    'matching_total_variation_max':.1,
    'calibration_hash_bits':[64,256], 'calibration_probe_counts':[16,32,64],
    'calibration_epsilons':[0.,1e-8,1e-4], 'calibration_seeds':list(range(7001,7025)),
    'calibration_random_trees':320,'calibration_label_points':1024,
    'calibration_audit_points':1024,'audit_tolerance':1e-8,
    'interpretation':'new internally frozen follow-up after observing v1; not independent replication or external registration'}


class ControlledSimplifier(base.Simplifier):
    def __init__(self, arm, policy, x, probes, seed, profile=None):
        super().__init__(arm,policy,x,probes,seed)
        self.rng=random.Random(seed+918271)
        self.profile=profile or {}
        self.generation=0
        self.bins=Counter()
    def simplify(self, tree, depth=0):
        import numpy as np
        if isinstance(tree,tuple):
            tree=(tree[0],*(self.simplify(t,depth+1) for t in tree[1:]))
        key=self.key(tree);other=self.bank.get(key)
        if other is not None and base.size(other)<base.size(tree):
            self.counts['hash_matches']+=1
            identity=f'{self.generation}:{min(depth,3)}'
            self.bins[identity+':proposed']+=1
            if self.arm=='random_rejection':
                # A reference bin without eligible proposals supplies no
                # rejection evidence. It defaults to no rejection, not a
                # tuned rate pooled from observed test performance.
                proposal=self.profile.get(identity+':proposed',0)
                rate=self.profile.get(identity+':rejected',0)/proposal if proposal else 0.
                accept=self.rng.random()>=rate
                residual=None
            else:
                a,b=self.vector(tree,True),self.vector(other,True)
                residual=float(np.max(np.abs(a-b)/(1+np.abs(a))))
                accept=self.arm=='lsh_only' or residual<=self.policy['epsilon']
            if accept:
                self.counts['accepted']+=1
                self.bins[identity+':accepted']+=1
                self.events.append((tree,other,residual))
                tree=other
            else:
                self.counts['gate_rejections']+=1
                self.bins[identity+':rejected']+=1
        if key not in self.bank or base.size(tree)<base.size(self.bank[key]):self.bank[key]=tree
        return tree


def trial(name,seed,arm,protocol,profile=None):
    import numpy as np
    policy=protocol['policy'];popsize=protocol['population'];ngen=protocol['generations']
    data=base.dataset(name,seed);x,y=data['train'];rng=random.Random(seed+8123)
    pop=[base.random_tree(rng) for _ in range(popsize)]
    simp=ControlledSimplifier(arm,policy,x,data['probes'][0][:policy['probe_count']],seed,profile)
    archive=[];start=time.monotonic()
    for gen in range(ngen+1):
        simp.generation=gen
        if arm!='no_simplify':
            simp.bank.clear();simp.cache.clear();simp.probe_cache.clear()
            for leaf in ('x','y',-1.,0.,.5,1.,2.):simp.simplify(leaf)
            pop=[simp.simplify(t) for t in pop]
        losses=[float(np.mean((base.evaluate(t,x)-y)**2)) for t in pop]
        best=min(range(popsize),key=lambda i:(losses[i],base.size(pop[i])))
        archive.append(pop[best])
        if gen==ngen:break
        def select():
            ids=[rng.randrange(popsize) for _ in range(3)]
            return pop[min(ids,key=lambda i:(losses[i],base.size(pop[i])))]
        nxt=[pop[best]]
        while len(nxt)<popsize:
            a=select();path=rng.choice(base.paths(a));b=select()
            sub=base.subtree(b,rng.choice(base.paths(b))) if rng.random()<.6 else base.random_tree(rng,2)
            child=base.replace(a,path,sub)
            nxt.append(child if base.size(child)<=63 and max(map(len,base.paths(child)))<=10 else a)
        pop=nxt
    vx,vy=data['validation'];best=min(archive,key=lambda t:(float(np.mean((base.evaluate(t,vx)-vy)**2)),base.size(t)))
    row={'benchmark':name,'seed':seed,'arm':arm,'test_r2':base.r2(base.evaluate(best,data['test'][0]),data['test'][1]),
        'ood_r2':base.r2(base.evaluate(best,data['ood'][0]),data['ood'][1]),
        'validation_r2':base.r2(base.evaluate(best,vx),vy),'final_size':base.size(best),
        'fitness_evaluations':popsize*(ngen+1),'wall_seconds':time.monotonic()-start,
        'champion':best,'profile':dict(simp.bins),**simp.counts}
    residuals=[]
    for before,after,_ in simp.events:
        a,b=base.evaluate(before,data['test'][0]),base.evaluate(after,data['test'][0])
        residuals.append(float(np.max(np.abs(a-b)/(1+np.abs(a)))))
    row['heldout_semantic_violations']=sum(v>protocol['audit_tolerance'] for v in residuals)
    row['heldout_max_residual']=max(residuals,default=0.)
    return row


def matched_job(request):
    name,seed,protocol=request
    gate=trial(name,seed,'probe_verified',protocol)
    return [trial(name,seed,'no_simplify',protocol),trial(name,seed,'lsh_only',protocol),
            gate,trial(name,seed,'random_rejection',protocol,gate['profile'])]


def calibration_job(request):
    """Evaluate all candidate collisions with disjoint probe/label/audit grids."""
    import numpy as np
    seed,protocol=request;rng=random.Random(seed)
    x=np.random.default_rng(seed).uniform(-1,1,(48,2))
    probes=np.random.default_rng(seed+100000).uniform(-1,1,(64,2))
    labels=np.random.default_rng(seed+200000).uniform(-1,1,(protocol['calibration_label_points'],2))
    audit=np.random.default_rng(seed+300000).uniform(-2,2,(protocol['calibration_audit_points'],2))
    trees=[base.random_tree(rng,3) for _ in range(protocol['calibration_random_trees'])]
    # Add known identities as a separate positive-control stratum, not as
    # evidence about the natural frequency of equivalent random trees.
    identities=[(('add',t,0.),t) for t in trees[:80]]
    rows=[]
    for bits in protocol['calibration_hash_bits']:
        simp=base.Simplifier('lsh_only',{'hash_bits':bits,'probe_count':64,'epsilon':0.},x,probes,seed)
        bank={};collisions=[]
        for t in trees:
            key=simp.key(t);other=bank.get(key)
            if other is not None and base.size(other)<base.size(t):collisions.append((t,other))
            if other is None or base.size(t)<base.size(other):bank[key]=t
        for stratum,pairs in [('retrieved',collisions),('known_identity',identities)]:
            for n in protocol['calibration_probe_counts']:
                for epsilon in protocol['calibration_epsilons']:
                    counts=Counter()
                    for a,b in pairs:
                        def residual(grid):
                            av,bv=base.evaluate(a,grid),base.evaluate(b,grid)
                            return float(np.max(np.abs(av-bv)/(1+np.abs(av))))
                        pr=residual(probes[:n]);lr=residual(labels);ar=residual(audit)
                        accepted=pr<=epsilon
                        equivalent=lr<=protocol['audit_tolerance'] and ar<=protocol['audit_tolerance']
                        counts['pairs']+=1;counts['accepted']+=int(accepted)
                        counts['agreement_positive']+=int(equivalent)
                        counts['false_accept']+=int(accepted and not equivalent)
                        counts['false_reject']+=int(not accepted and equivalent)
                    rows.append({'seed':seed,'hash_bits':bits,'probe_count':n,'epsilon':epsilon,'stratum':stratum,**{k:counts[k] for k in ('pairs','accepted','agreement_positive','false_accept','false_reject')}})
    return rows


def analyze(records,protocol):
    import numpy as np
    summaries={}
    for arm in protocol['arms']:
        rows=[r for r in records if r['arm']==arm]
        summaries[arm]={k:statistics.mean(r[k] for r in rows) for k in ('test_r2','ood_r2','final_size','wall_seconds','fitness_evaluations')}
        for k in ('accepted','heldout_semantic_violations','gate_rejections'):summaries[arm][k]=sum(r[k] for r in rows)
    index={(r['benchmark'],r['seed'],r['arm']):r for r in records};contrasts=[]
    for control in ('random_rejection','lsh_only','no_simplify'):
        d=np.array([statistics.mean(index[n,s,'probe_verified']['test_r2']-index[n,s,control]['test_r2'] for n in protocol['benchmarks']) for s in protocol['seeds']])
        rng=np.random.default_rng(57123)
        boot=rng.choice(d,size=(protocol['bootstrap_repeats'],len(d)),replace=True).mean(axis=1)
        # Preset Monte Carlo sign-flip test with the plus-one correction.
        signs=rng.choice([-1,1],size=(100000,len(d)))
        p=(1+int(np.sum(np.abs((signs*d).mean(axis=1))>=abs(d.mean())-1e-14)))/100001
        contrasts.append({'control':control,'mean_delta_test_r2':float(d.mean()),'ci95':np.quantile(boot,[.025,.975]).tolist(),'signflip_p':p,'seed_deltas':d.tolist()})
    prev=0.
    for rank,c in enumerate(sorted(contrasts,key=lambda c:c['signflip_p'])):
        prev=max(prev,min(1.,(len(contrasts)-rank)*c['signflip_p']));c['holm_p']=prev
    matching=[]
    for name in protocol['benchmarks']:
        for seed in protocol['seeds']:
            a=index[name,seed,'probe_verified']['profile'];b=index[name,seed,'random_rejection']['profile']
            bins={k.rsplit(':',1)[0] for k in set(a)|set(b)}
            na=sum(a.get(k+':rejected',0) for k in bins);nb=sum(b.get(k+':rejected',0) for k in bins)
            tv=.5*sum(abs(a.get(k+':rejected',0)/max(na,1)-b.get(k+':rejected',0)/max(nb,1)) for k in bins)
            common=[k for k in bins if a.get(k+':proposed',0)>=5 and b.get(k+':proposed',0)>=5]
            gap=max((abs(a.get(k+':rejected',0)/a[k+':proposed']-b.get(k+':rejected',0)/b[k+':proposed']) for k in common),default=1.)
            matching.append({'benchmark':name,'seed':seed,'rejection_profile_tv':tv,'max_rate_gap_min5':gap,
                'criterion_met':tv<=protocol['matching_total_variation_max'] and gap<=protocol['matching_max_bin_acceptance_rate_difference']})
    return {'summaries':summaries,'contrasts':contrasts,'matching':matching,
            'matched_trials':sum(m['criterion_met'] for m in matching),'total_pairs':len(matching),
            'causal_attribution':'not_established' if not all(m['criterion_met'] for m in matching) else 'requires_further_review'}


def main():
    import argparse
    from pathlib import Path
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--workers',type=int,default=16);args=parser.parse_args()
    args.output.mkdir(parents=True,exist_ok=False)
    protocol={**PROTOCOL,'program_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              'base_program_sha256':hashlib.sha256(Path(base.__file__).read_bytes()).hexdigest(),
              'frozen_at_utc':__import__('datetime').datetime.now(__import__('datetime').timezone.utc).isoformat()}
    def save(name,value):(args.output/name).write_text(json.dumps(value,indent=2,allow_nan=False),encoding='utf-8')
    save('protocol.json',protocol)
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        records=[]
        for rows in pool.map(matched_job,[(n,s,protocol) for n in protocol['benchmarks'] for s in protocol['seeds']]):
            records.extend(rows);save('measurements.partial.json',records)
        save('measurements.json',records);save('analysis.json',analyze(records,protocol))
        calibration=[]
        for rows in pool.map(calibration_job,[(s,protocol) for s in protocol['calibration_seeds']]):calibration.extend(rows)
        save('calibration.json',calibration)
    save('manifest.json',{p.name:{'bytes':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}
        for p in sorted(args.output.iterdir()) if p.is_file()})
    print(json.dumps({'status':'completed','trials':len(records),'calibration_cells':len(calibration)}))


if __name__=='__main__':main()
