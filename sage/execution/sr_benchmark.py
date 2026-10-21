"""Owned, bounded symbolic-regression experiment (not an upstream reproduction).

Only a typed simplification policy is model controlled. This trusted evaluator
implements all arms, data splits and metrics; no generated Python is executed.
NumPy is optional and imported only in the separately installed task runtime.
"""
import hashlib
import itertools
import json
import math
import random
import statistics
import time

ARMS = ('no_simplify', 'lsh_only', 'probe_verified', 'exact_probe',
        'size_penalty_small', 'size_penalty_large')
BENCHMARKS = ('polynomial', 'trigonometric', 'interaction')
PRIMARY_MINIMUM_EFFECT = .02
PRIMARY_HOLM_ALPHA = .05
POLICY_SPACE = {'hash_bits': (64, 256), 'probe_count': (16, 32, 64),
                'epsilon': (0.0, 1e-8, 1e-4)}


def validate_policy(value):
    if not isinstance(value, dict) or set(value) != set(POLICY_SPACE):
        raise ValueError('Policy must contain exactly hash_bits, probe_count, epsilon')
    for key, choices in POLICY_SPACE.items():
        if type(value[key]) not in (int, float) or value[key] not in choices:
            raise ValueError('Policy value outside the frozen search space: ' + key)
    if type(value['hash_bits']) is not int or type(value['probe_count']) is not int:
        raise ValueError('Hash bits and probe count must be integers')
    return dict(value)


def size(tree):
    return 1 if not isinstance(tree, tuple) else 1 + sum(size(t) for t in tree[1:])


def evaluate(tree, x):
    import numpy as np
    if tree == 'x': return x[:, 0]
    if tree == 'y': return x[:, 1]
    if not isinstance(tree, tuple): return np.full(len(x), float(tree))
    op = tree[0]; a = evaluate(tree[1], x)
    if op == 'sin': return np.sin(a)
    if op == 'cos': return np.cos(a)
    b = evaluate(tree[2], x)
    with np.errstate(over='ignore', invalid='ignore', divide='ignore'):
        if op == 'add': out = a + b
        elif op == 'sub': out = a - b
        elif op == 'mul': out = a * b
        else: raise ValueError('Unknown operator')
    return np.clip(np.nan_to_num(out, nan=1e6, posinf=1e6, neginf=-1e6), -1e6, 1e6)


def target(name, x):
    import numpy as np
    a, b = x[:, 0], x[:, 1]
    if name == 'polynomial': return a + a*a + a*a*a
    if name == 'trigonometric': return np.sin(a) + np.sin(a*a + a)
    if name == 'interaction': return a*a + a*b + b*b
    raise ValueError('Unknown benchmark')


def dataset(name, seed):
    import numpy as np
    # Independent, domain-separated RNGs; confirmation seeds never enter development.
    arrays = {}
    for split, n, domain in [('train', 48, 1), ('validation', 48, 1),
                              ('test', 192, 1), ('ood', 192, 2), ('probes', 64, 1)]:
        key = int(hashlib.sha256(f'{name}:{seed}:{split}:v1'.encode()).hexdigest()[:16], 16)
        x = np.random.default_rng(key).uniform(-domain, domain, (n, 2))
        arrays[split] = (x, target(name, x))
    return arrays


def random_tree(rng, depth=3):
    if depth <= 0 or rng.random() < .3:
        return rng.choice(('x', 'y', -1.0, 0.0, .5, 1.0, 2.0))
    op = rng.choice(('add', 'sub', 'mul', 'sin', 'cos'))
    return (op, random_tree(rng, depth-1)) if op in ('sin', 'cos') else (
        op, random_tree(rng, depth-1), random_tree(rng, depth-1))


def paths(tree):
    out = [()]
    if isinstance(tree, tuple):
        for i in range(1, len(tree)):
            out.extend((i,) + p for p in paths(tree[i]))
    return out


def subtree(tree, path):
    for i in path: tree = tree[i]
    return tree


def replace(tree, path, value):
    if not path: return value
    parts = list(tree); parts[path[0]] = replace(parts[path[0]], path[1:], value)
    return tuple(parts)


class Simplifier:
    def __init__(self, arm, policy, x, probes, seed):
        import numpy as np
        self.arm, self.policy, self.x, self.probes = arm, policy, x, probes
        self.planes = np.random.default_rng(seed + 917).normal(size=(policy['hash_bits'], len(x)))
        self.bank = {}; self.cache = {}; self.probe_cache = {}
        self.counts = {'hash_matches': 0, 'accepted': 0, 'probe_evaluations': 0,
                       'hash_evaluations': 0, 'gate_rejections': 0}
        self.events = []

    def vector(self, t, probe=False):
        cache = self.probe_cache if probe else self.cache
        if t not in cache:
            cache[t] = evaluate(t, self.probes if probe else self.x)
            self.counts['probe_evaluations' if probe else 'hash_evaluations'] += 1
        return cache[t]

    def key(self, tree):
        import numpy as np
        v = self.vector(tree)
        # Random-hyperplane LSH plus a coarse norm bucket. This owned proxy is
        # deliberately documented; it is NOT the paper's exact LHS algorithm.
        bits = np.packbits(self.planes @ v >= 0).tobytes()
        scale = round(math.log1p(float(np.linalg.norm(v))), 1)
        return bits, scale

    def simplify(self, tree):
        import numpy as np
        if isinstance(tree, tuple):
            tree = (tree[0], *(self.simplify(t) for t in tree[1:]))
        key = self.key(tree); other = self.bank.get(key)
        if other is not None and size(other) < size(tree):
            self.counts['hash_matches'] += 1
            # Gate uses input-only probe points, never validation/test labels.
            a, b = self.vector(tree, True), self.vector(other, True)
            residual = float(np.max(np.abs(a-b)/(1+np.abs(a))))
            accept = (self.arm == 'lsh_only' or
                      (self.arm == 'probe_verified' and residual <= self.policy['epsilon']) or
                      (self.arm == 'exact_probe' and bool(np.array_equal(a, b))))
            if accept:
                self.counts['accepted'] += 1
                self.events.append((tree, other, residual))
                tree = other
            else: self.counts['gate_rejections'] += 1
        if key not in self.bank or size(tree) < size(self.bank[key]): self.bank[key] = tree
        return tree


def r2(pred, truth):
    import numpy as np
    return float(1 - np.sum((pred-truth)**2)/np.sum((truth-np.mean(truth))**2))


def trial(name, seed, arm, policy, *, population=40, generations=20, phase='development'):
    import numpy as np
    data = dataset(name, seed); x, y = data['train']
    probe_x = data['probes'][0][:policy['probe_count']]
    rng = random.Random(seed + 8123)
    pop = [random_tree(rng) for _ in range(population)]
    simplifier = Simplifier(arm, policy, x, probe_x, seed)
    penalty = {'size_penalty_small': .001, 'size_penalty_large': .01}.get(arm, 0)
    start = time.monotonic(); evaluations = 0; archive = []
    max_nodes = 63
    for generation in range(generations+1):
        if arm in ('lsh_only', 'probe_verified', 'exact_probe'):
            # Rebuild per generation, bounded memory; include terminals first.
            simplifier.bank.clear(); simplifier.cache.clear(); simplifier.probe_cache.clear()
            for leaf in ('x', 'y', -1.0, 0.0, .5, 1.0, 2.0): simplifier.simplify(leaf)
            pop = [simplifier.simplify(t) for t in pop]
        losses = [float(np.mean((evaluate(t, x)-y)**2)) + penalty*size(t) for t in pop]
        evaluations += len(pop)
        best = min(range(len(pop)), key=lambda i: (losses[i], size(pop[i])))
        archive.append(pop[best])
        if generation == generations: break
        def tournament():
            indices = [rng.randrange(population) for _ in range(3)]
            return pop[min(indices, key=lambda i: (losses[i], size(pop[i])))]
        nxt = [pop[best]]
        while len(nxt) < population:
            a = tournament(); path = rng.choice(paths(a))
            b = tournament()
            value = subtree(b, rng.choice(paths(b))) if rng.random() < .6 else random_tree(rng, 2)
            child = replace(a, path, value)
            nxt.append(child if size(child) <= max_nodes and len(max(paths(child), key=len)) <= 10 else a)
        pop = nxt
    vx, vy = data['validation']
    champion = min(archive, key=lambda t: (float(np.mean((evaluate(t, vx)-vy)**2)), size(t)))
    row = {'benchmark': name, 'seed': seed, 'arm': arm, 'phase': phase,
           'validation_r2': r2(evaluate(champion, vx), vy), 'final_size': size(champion),
           'fitness_evaluations': evaluations, 'wall_seconds': time.monotonic()-start,
           'champion': champion, **simplifier.counts}
    # Holdout metrics do not exist at all on development output.
    if phase == 'confirmation':
        tx, ty = data['test']; ox, oy = data['ood']
        row['test_r2'] = r2(evaluate(champion, tx), ty)
        row['ood_r2'] = r2(evaluate(champion, ox), oy)
        # Post-hoc heldout semantic audit never affects optimization/selection.
        violations = 0; max_residual = 0.0
        for before, after, _ in simplifier.events:
            a, b = evaluate(before, tx), evaluate(after, tx)
            residual = float(np.max(np.abs(a-b)/(1+np.abs(a))))
            max_residual = max(max_residual, residual)
            violations += int(residual > policy['epsilon'])
        row.update(heldout_semantic_violations=violations, heldout_max_residual=max_residual,
                   semantic_preservation_rate=(1-violations/len(simplifier.events)) if simplifier.events else None)
    # Full trees for bounded representative events; all event identities/residuals
    # are retained, not passed to the model as scientific conclusions.
    row['replacement_events'] = [{'before_sha256': hashlib.sha256(repr(a).encode()).hexdigest(),
        'after_sha256': hashlib.sha256(repr(b).encode()).hexdigest(), 'pre_size': size(a),
        'post_size': size(b), 'probe_residual': e} for a,b,e in simplifier.events]
    return row


def run_suite(contract, policy, phase):
    validate_policy(policy)
    if phase not in ('development', 'confirmation'): raise ValueError('Invalid phase')
    rows = []
    for name in contract['benchmarks']:
        for seed in contract[phase+'_seeds']:
            for arm in ARMS:
                rows.append(trial(name, seed, arm, policy, population=contract['population'],
                    generations=contract['generations'], phase=phase))
    return {'schema_version': 'sage.sr_measurements.v1', 'phase': phase, 'policy': policy,
            'records': rows, 'numpy_version': __import__('numpy').__version__,
            'scope': 'real_GP_training_on_owned_analytic_functions_not_paper_reproduction'}


def dev_score(result):
    rows = [r for r in result['records'] if r['arm'] == 'probe_verified']
    return statistics.mean(r['validation_r2'] for r in rows)


def analyze(result, *, bootstrap_repeats=2000):
    """Paired seed-cluster bootstrap; fixed functions are not random task samples."""
    import numpy as np
    rows = result['records']
    if result['phase'] != 'confirmation': raise ValueError('Analysis requires heldout confirmation')
    seeds = sorted({r['seed'] for r in rows}); names = sorted({r['benchmark'] for r in rows})
    index = {(r['benchmark'],r['seed'],r['arm']): r for r in rows}
    if len(index) != len(rows) or len(rows) != len(names)*len(seeds)*len(ARMS):
        raise ValueError('Incomplete/duplicate confirmation grid')
    summaries = {}
    for arm in ARMS:
        selected = [r for r in rows if r['arm'] == arm]
        summaries[arm] = {k: statistics.mean(r[k] for r in selected) for k in
            ('test_r2','ood_r2','final_size','wall_seconds','fitness_evaluations')}
        summaries[arm]['accepted'] = sum(r['accepted'] for r in selected)
        summaries[arm]['heldout_semantic_violations'] = sum(r['heldout_semantic_violations'] for r in selected)
    contrasts=[]
    for arm in ('lsh_only','no_simplify','exact_probe','size_penalty_small','size_penalty_large'):
        delta = np.array([statistics.mean(index[n,s,'probe_verified']['test_r2']-index[n,s,arm]['test_r2']
                    for n in names) for s in seeds])
        rng = np.random.default_rng(29071)
        samples = np.mean(rng.choice(delta, size=(bootstrap_repeats, len(delta)), replace=True), axis=1)
        lo, hi = np.quantile(samples,[.025,.975])
        null = [abs(float(np.mean(delta*np.array(signs)))) for signs in itertools.product((-1,1),repeat=len(delta))]
        observed = abs(float(np.mean(delta)))
        p = sum(v >= observed-1e-14 for v in null)/len(null)
        contrasts.append({'control':arm,'mean_delta_test_r2':float(np.mean(delta)),
                          'ci95':[float(lo),float(hi)],'paired_signflip_p':p,'seed_deltas':delta.tolist()})
    # Holm adjustment across all five preregistered contrasts.
    previous=0
    for rank,item in enumerate(sorted(contrasts,key=lambda r:r['paired_signflip_p'])):
        previous=max(previous,min(1,(len(contrasts)-rank)*item['paired_signflip_p']))
        item['holm_p']=previous
    primary=contrasts[0]
    # H1 promises at least the minimum effect, not merely a nonzero effect.
    # The zero-null sign-flip/Holm tests remain separate diagnostics. A positive
    # point estimate above the threshold cannot resolve an interval crossing it.
    if primary['ci95'][0] >= PRIMARY_MINIMUM_EFFECT and primary['holm_p'] < PRIMARY_HOLM_ALPHA:
        claim='supported_in_this_bounded_experiment'
        reason='interval_supports_minimum_effect_and_zero_null_family_gate_passed'
    elif primary['ci95'][1] < PRIMARY_MINIMUM_EFFECT:
        claim='not_supported'
        reason='interval_upper_bound_below_minimum_effect'
    else:
        claim='inconclusive'
        reason=('interval_crosses_minimum_effect' if primary['ci95'][0] < PRIMARY_MINIMUM_EFFECT
                else 'zero_null_family_gate_not_passed')
    matches=[]
    for control in ('size_penalty_small','size_penalty_large'):
        # Report each function separately; pooling can conceal opposite mismatches.
        for name in names:
            a=[index[name,s,'probe_verified']['final_size'] for s in seeds]
            b=[index[name,s,control]['final_size'] for s in seeds]
            ks=max(abs(sum(v<=t for v in a)/len(a)-sum(v<=t for v in b)/len(b)) for t in set(a+b))
            matches.append({'benchmark':name,'control':control,'empirical_ks_distance':ks,
                            'preregistered_match_criterion_met':ks<=.25})
    return {'schema_version':'sage.sr_analysis.v1','summaries':summaries,'contrasts':contrasts,
            'primary_claim_status':claim,
            'primary_decision':{'version':'sage.sr_primary_decision.v2',
                'minimum_effect':PRIMARY_MINIMUM_EFFECT,'status':claim,'reason':reason,
                'support_rule':'primary_ci95_lower_bound >= minimum_effect and zero_null_holm_p < alpha',
                'not_supported_rule':'primary_ci95_upper_bound < minimum_effect',
                'otherwise':'inconclusive','holm_alpha':PRIMARY_HOLM_ALPHA,
                'interval_scope':'unadjusted_95_percent_paired_seed_cluster_bootstrap_for_prespecified_primary_contrast',
                'signflip_null':'zero_paired_effect_under_sign_symmetry',
                'signflip_scope':'two_sided_zero_effect_test_with_Holm_adjustment_across_five_contrasts; not_a_test_of_minimum_effect',
                'limitation':'small_seed_bootstrap_intervals_are_not_power_or_coverage_certification'},
            'complexity_matching':matches,
            'all_complexity_matches_met':all(r['preregistered_match_criterion_met'] for r in matches),
            'bootstrap_repeats':bootstrap_repeats,'independent_unit':'paired_training_seed_cluster',
            'scope':'fixed_analytic_functions_and_listed_seeds_only',
            'scientific_validation':'bounded_internal_experiment_not_independent_replication'}


if __name__ == '__main__':
    import sys
    request=json.load(sys.stdin)
    print(json.dumps(run_suite(request['contract'],request['policy'],request['phase']),allow_nan=False))
