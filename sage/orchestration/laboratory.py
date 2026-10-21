"""One bounded runtime composes CoI proposals and Agent Laboratory engineering/writing."""
from ..runtime import Runtime
from ..config import RunConfig
from ..errors import SageError
from ..execution import ExperimentRunner
from ..writing import generate_report
from . import run


async def run_laboratory(topic, model, source, *, contract, cheap_model=None, config=None,
                         mode='offline', articles=None, backend=None, allow_execution=False,
                         approved_contract_digest=None, runtime=None, on_progress=None):
    config = config or RunConfig()
    runtime = runtime or Runtime(model, cheap_model or model, source, config)
    runner = ExperimentRunner(runtime, contract, backend=backend, allow_execution=allow_execution,
                              approved_contract_digest=approved_contract_digest)
    result = {'schema_version': 'sage.laboratory.v1', 'proposal': None,
              'execution': None, 'report': None, 'status': 'proposal_running',
              'scientific_validation': 'not_performed', 'errors': []}

    def publish(section=None, value=None):
        if section is not None:
            result[section] = value
        result['audit'] = list(runtime.audit)
        result['usage'] = dict(runtime.usage)
        result['usage']['elapsed_seconds'] = round(runtime.elapsed_before + runtime.clock() - runtime.started, 6)
        if on_progress:
            on_progress(result)

    publish()
    proposal = await run(topic, model, source, cheap_model=cheap_model, config=config,
                         mode=mode, articles=articles, runtime=runtime)
    result['proposal'] = proposal.to_dict()
    result['status'] = 'proposal_failed'
    if proposal.status.startswith('completed') and proposal.experiment is not None:
        result['status'] = 'execution_running'
        publish()
        result['execution'] = await runner.run(proposal.experiment,
            on_progress=lambda value: publish('execution', value))
        result['status'] = 'writing_running'
        publish()
        try:
            result['report'] = await generate_report(runtime, result['proposal'], result['execution'],
                on_progress=lambda value: publish('report', value))
            if not result['report']['status'].startswith('completed'):
                result['status'] = 'report_incomplete'
                result['errors'].extend(result['report']['errors'])
            else:
                result['status'] = result['execution']['status']
        except SageError as error:
            result['errors'].append({'stage': 'writing', 'code': error.code})
            result['status'] = 'report_incomplete'
    else:
        result['errors'].extend({'stage': 'proposal', **error} for error in proposal.errors)
    publish()
    return result
