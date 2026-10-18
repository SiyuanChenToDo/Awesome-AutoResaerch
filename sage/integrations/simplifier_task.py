"""Deterministic local development data; no downloaded benchmark or hidden test claim."""
import random


def dataset(seed=731,count=96):
    rng=random.Random(seed)
    rows=[]
    for _ in range(count):
        term=rng.choice(['x','y',['mul','x','y'],['add','x',2],['sub','x','y']])
        other=rng.choice(['x','y',2,-1])
        row=rng.choice([['add',term,term],['mul',term,1],['add',term,0],
                        ['sub',term,term],['add',['mul',term,0],other],
                        ['add',['add',term,term],['add',term,term]]])
        rows.append(row)
    probes=[{'x':x,'y':y} for x in (-3,-0.5,0,2.5) for y in (-2,0,0.75,4)]
    return {'schema_version':'sage.synthetic_expressions.v1','seed':seed,
            'scope':'development_integration_smoke_not_a_scientific_benchmark',
            'expressions':rows,'probes':probes}
