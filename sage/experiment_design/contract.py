"""Machine-readable planning questions, not an evaluator or approval contract."""
from ..discussion import strict_object
from ..errors import InvalidResponse

INSTRUCTIONS = '''
Return a concise, complete <experiment>proposal</experiment>, then
<plan_contract>{JSON}</plan_contract>. This is a proposal, never a result.
Required JSON keys (no others):
{"budget":{"unit":"text or UNRESOLVED","cap":"text or UNRESOLVED","accounting":"count retrieval, input/output tokens, verification and retries exactly once","status":"proposed or unresolved"},
"metrics":[{"name":"text","numerator":"text","denominator":"text","direction":"maximize or minimize","status":"proposed or unresolved"}],
"sample_size":{"unit":"independent sampling unit","n":null,"justification":"power/effect assumptions or UNRESOLVED","status":"proposed or unresolved"},
"stopping":{"rule":"bounded stopping/failure rule or UNRESOLVED","status":"proposed or unresolved"},
"evidence_limits":"actual source scope and unresolved novelty",
"scientific_validation":"not_performed","execution_ready":false}.
An n may be a positive integer proposal or null, never an invented measured sample.
Mark missing decisions unresolved. No claim that this schema validates scientific
correctness or freezes an executable evaluator. Distinguish false-verification
fraction from verification precision. Do not count verification twice in a retry.
'''


def parse_contract(text):
    value = strict_object(text)
    expected = {'budget', 'metrics', 'sample_size', 'stopping', 'evidence_limits',
                'scientific_validation', 'execution_ready'}
    if set(value) != expected or value['scientific_validation'] != 'not_performed' or value['execution_ready'] is not False:
        raise InvalidResponse('Plan contract cannot assert execution approval or scientific validation')
    def record(obj, keys):
        if not isinstance(obj, dict) or set(obj) != set(keys) | {'status'} or obj['status'] not in ('proposed', 'unresolved'):
            raise InvalidResponse('Invalid plan contract fields/status')
        if any(not isinstance(obj[k], str) or not obj[k].strip() for k in keys):
            raise InvalidResponse('Plan contract requires explicit text or unresolved decisions')
    record(value['budget'], ('unit', 'cap', 'accounting'))
    record(value['stopping'], ('rule',))
    sample = value['sample_size']
    if not isinstance(sample, dict) or set(sample) != {'unit', 'n', 'justification', 'status'}:
        raise InvalidResponse('Invalid sample-size contract')
    record({k: v for k, v in sample.items() if k != 'n'}, ('unit', 'justification'))
    if sample['n'] is not None and (type(sample['n']) is not int or sample['n'] <= 0):
        raise InvalidResponse('Sample size must be a proposed positive integer or null')
    if sample['n'] is None and sample['status'] != 'unresolved':
        raise InvalidResponse('Missing sample size must remain unresolved')
    if not isinstance(value['metrics'], list) or not value['metrics']:
        raise InvalidResponse('Plan must explicitly define metrics')
    for metric in value['metrics']:
        record(metric, ('name', 'numerator', 'denominator', 'direction'))
        if metric['direction'] not in ('maximize', 'minimize'):
            raise InvalidResponse('Invalid metric direction')
    if not isinstance(value['evidence_limits'], str) or not value['evidence_limits'].strip():
        raise InvalidResponse('Missing evidence limitations')
    return value


def fixture_contract():
    return {'budget': {'unit': 'synthetic units', 'cap': 'UNRESOLVED', 'accounting': 'Count each call and retry once', 'status': 'unresolved'},
            'metrics': [{'name': 'synthetic support fraction', 'numerator': 'supported synthetic items',
                         'denominator': 'all synthetic items', 'direction': 'maximize', 'status': 'proposed'}],
            'sample_size': {'unit': 'synthetic item', 'n': None, 'justification': 'UNRESOLVED power analysis', 'status': 'unresolved'},
            'stopping': {'rule': 'UNRESOLVED; no execution authorized', 'status': 'unresolved'},
            'evidence_limits': 'Synthetic fixture only', 'scientific_validation': 'not_performed', 'execution_ready': False}
