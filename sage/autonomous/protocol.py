"""A single structured experimental protocol, not a scientific truth oracle."""
from __future__ import annotations

import math

VERSION = 'sage.scientific-protocol.v1'


def protocol_descriptor():
    return {'schema_version': VERSION,
        'scope': 'Structural consistency only; scientific assumptions require evidence and actual experiments.',
        'candidate_field': 'protocol',
        'template': {'schema_version': VERSION,
            'variables': [{'id': 'X', 'definition': 'measured quantity',
                           'encoding': 'explicit sign, class labels and transformation', 'unit': 'unit'}],
            'hypothesis': {'contrast': 'explicit comparison with baseline',
                           'expected_direction': 'increase|decrease|different', 'variable_ids': ['X']},
            'endpoints': [{'id': 'E1', 'role': 'primary|secondary', 'definition': 'exact estimand',
                           'metric': 'formula or operational definition', 'unit': 'unit',
                           'direction': 'higher|lower|two_sided', 'variable_ids': ['X']}],
            'primary_endpoint_ids': ['E1'],
            'decision_rule': {'type': 'superiority|equivalence|noninferiority|falsification',
                'endpoint_ids': ['E1'], 'combination': 'all|any',
                'multiplicity': 'none (single endpoint), or explicit correction for multiple endpoints',
                'support_when': 'precise condition', 'refute_when': 'precise condition',
                'inconclusive_when': 'uncertainty crossing the boundary is not itself falsification',
                'low_power_action': 'inconclusive|collect_more_data'},
            'analysis': {'method': 'estimator and comparison', 'uncertainty_method': 'CI construction',
                'confidence_level': 0.95, 'unit_of_analysis': 'independent sampling unit',
                'sample_size': None, 'controls': ['baseline and negative control'],
                'power': {'status': 'not_established|estimated',
                          'assumptions': 'DGP, effect size, repetitions and uncertainty; unknown allowed'}},
            'resources': {'status': 'unresolved|estimated|frozen', 'compute_budget': 'explicit or unresolved',
                          'estimate_basis': 'measurement, estimate or missing',
                          'stopping_rule': 'maximum compute, samples and stopping criterion'}},
        'instructions': [
            'Use exactly one canonical protocol per candidate; prose explains it and cannot redefine endpoints.',
            'For co-primary endpoints list all IDs, the all/any combination, and multiplicity policy explicitly.',
            'Specify binary class encodings/signs before deriving expected directions.',
            'Do not equate a CI containing zero with equivalence, noninferiority, or falsification.',
            'Report power as not_established unless independently repeated design evidence supports it.',
            'Unresolved budget, sample size and power remain visible; structure passing is not experimental readiness.']}


def protocol_errors(candidate):
    protocol = candidate.get('protocol')
    errors = []
    if not isinstance(protocol, dict):
        return ['Selected candidate needs the canonical protocol; request protocol_schema']
    if protocol.get('schema_version') != VERSION:
        errors.append('Unknown scientific protocol version')

    def text(obj, key, path):
        if not isinstance(obj, dict) or not isinstance(obj.get(key), str) or not obj[key].strip():
            errors.append(path + '.' + key + ' must be nonempty text')

    variables = protocol.get('variables')
    variable_ids = set()
    if not isinstance(variables, list) or not variables:
        errors.append('protocol.variables must name measured quantities and encodings')
    else:
        for variable in variables:
            for key in ('id', 'definition', 'encoding', 'unit'):
                text(variable, key, 'protocol.variables')
            ident = variable.get('id') if isinstance(variable, dict) else None
            if isinstance(ident, str):
                if ident in variable_ids:
                    errors.append('Duplicate protocol variable ID')
                variable_ids.add(ident)

    def refs(obj, key, allowed, path):
        values = obj.get(key) if isinstance(obj, dict) else None
        if (not isinstance(values, list) or not values or
                any(not isinstance(x, str) or x not in allowed for x in values) or
                len(values) != len(set(values))):
            errors.append(path + '.' + key + ' must contain unique declared IDs')
            return []
        return values

    hypothesis = protocol.get('hypothesis', {})
    text(hypothesis, 'contrast', 'protocol.hypothesis')
    if not isinstance(hypothesis, dict) or hypothesis.get('expected_direction') not in ('increase', 'decrease', 'different'):
        errors.append('protocol.hypothesis expected_direction is invalid')
    refs(hypothesis, 'variable_ids', variable_ids, 'protocol.hypothesis')
    endpoints = protocol.get('endpoints')
    endpoint_ids, primary_ids = set(), set()
    if not isinstance(endpoints, list) or not endpoints:
        errors.append('protocol.endpoints must be nonempty')
    else:
        for endpoint in endpoints:
            for key in ('id', 'definition', 'metric', 'unit'):
                text(endpoint, key, 'protocol.endpoints')
            if not isinstance(endpoint, dict):
                continue
            ident = endpoint.get('id')
            if isinstance(ident, str):
                if ident in endpoint_ids:
                    errors.append('Duplicate endpoint ID')
                endpoint_ids.add(ident)
                if endpoint.get('role') == 'primary':
                    primary_ids.add(ident)
            if endpoint.get('role') not in ('primary', 'secondary'):
                errors.append('Endpoint role must be primary or secondary')
            if endpoint.get('direction') not in ('higher', 'lower', 'two_sided'):
                errors.append('Endpoint direction must be explicit')
            refs(endpoint, 'variable_ids', variable_ids, 'protocol.endpoints')
    declared_primary = refs(protocol, 'primary_endpoint_ids', endpoint_ids, 'protocol')
    if set(declared_primary) != primary_ids:
        errors.append('Primary endpoint IDs disagree with endpoint roles')
    rule = protocol.get('decision_rule', {})
    if not isinstance(rule, dict):
        rule = {}
    if rule.get('type') not in ('superiority', 'equivalence', 'noninferiority', 'falsification'):
        errors.append('Decision rule type is invalid')
    if set(refs(rule, 'endpoint_ids', endpoint_ids, 'protocol.decision_rule')) != primary_ids:
        errors.append('Decision rule must cover exactly the primary endpoints')
    if rule.get('combination') not in ('all', 'any'):
        errors.append('Multiple endpoint combination must be all or any')
    for key in ('multiplicity', 'support_when', 'refute_when', 'inconclusive_when'):
        text(rule, key, 'protocol.decision_rule')
    if len(primary_ids) > 1 and str(rule.get('multiplicity', '')).strip().lower() in ('none', 'no', 'n/a'):
        errors.append('Co-primary endpoints require an explicit multiplicity policy')
    if rule.get('low_power_action') not in ('inconclusive', 'collect_more_data'):
        errors.append('Low power must remain inconclusive or request more data')
    if rule.get('type') in ('equivalence', 'noninferiority'):
        margin = rule.get('margin')
        if type(margin) not in (int, float) or not math.isfinite(margin) or margin <= 0:
            errors.append('Equivalence/noninferiority requires a positive numeric margin in endpoint units')
        if len(primary_ids) != 1:
            errors.append('Different co-primary margins need separate registered decision rules')
    analysis = protocol.get('analysis', {})
    if not isinstance(analysis, dict):
        analysis = {}
    for key in ('method', 'uncertainty_method', 'unit_of_analysis'):
        text(analysis, key, 'protocol.analysis')
    level = analysis.get('confidence_level')
    if type(level) not in (int, float) or not 0 < level < 1:
        errors.append('Confidence level must be between zero and one')
    sample = analysis.get('sample_size')
    if sample is not None and (type(sample) is not int or sample < 2):
        errors.append('Sample size must be null (unresolved) or an integer >=2')
    controls = analysis.get('controls')
    if not isinstance(controls, list) or not controls or any(not isinstance(x, str) or not x.strip() for x in controls):
        errors.append('Analysis must identify controls')
    power = analysis.get('power', {})
    if not isinstance(power, dict) or power.get('status') not in ('not_established', 'estimated', 'validated'):
        errors.append('Power status must be explicit')
    text(power, 'assumptions', 'protocol.analysis.power')
    if isinstance(power, dict) and power.get('status') == 'validated':
        errors.append('Model-authored power cannot be validated; manager-authenticated experimental evidence is required')
        for key in ('validation_artifact_sha256', 'independent_replicates', 'uncertainty'):
            if not power.get(key):
                errors.append('Validated power requires ' + key + ' (not repeated splits of one dataset)')
    resources = protocol.get('resources', {})
    if not isinstance(resources, dict) or resources.get('status') not in ('unresolved', 'estimated', 'frozen'):
        errors.append('Resource status must be explicit')
    for key in ('compute_budget', 'estimate_basis', 'stopping_rule'):
        text(resources, key, 'protocol.resources')
    return errors


def interval_decision(lower, upper, *, kind='superiority', margin=0.0, power_sufficient=True):
    """Classify a CI for a signed effect (positive favors the hypothesis).

    This helper is an explicit convention for future executors, not a claim
    that any natural-language candidate has been mathematically verified.
    """
    if (any(type(x) not in (int, float) or not math.isfinite(x) for x in (lower, upper, margin))
            or lower > upper or type(power_sufficient) is not bool):
        raise ValueError('Expected a finite ordered interval and explicit power flag')
    if kind not in ('superiority', 'noninferiority', 'equivalence'):
        raise ValueError('Unknown interval decision type')
    if kind != 'superiority' and margin <= 0:
        raise ValueError('An equivalence/noninferiority margin must be positive')
    if not power_sufficient:
        return 'inconclusive'
    if kind == 'equivalence':
        return 'supported' if lower > -margin and upper < margin else (
            'refuted' if lower >= margin or upper <= -margin else 'inconclusive')
    boundary = 0 if kind == 'superiority' else -margin
    return 'supported' if lower > boundary else ('refuted' if upper < boundary else 'inconclusive')
