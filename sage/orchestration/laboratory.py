"""One bounded runtime composes CoI proposals and Agent Laboratory engineering/writing."""
from ..runtime import Runtime
from ..config import RunConfig
from ..errors import SageError
from ..execution import ExperimentRunner
from ..writing import generate_report
from . import run


async def run_laboratory(topic, model, source, *, contract, cheap_model=None, config=None,
                         mode='offline', articles=None, backend=None, allow_execution=False,
                         approved_contract_digest=None):
    config = config or RunConfig()
    runtime = Runtime(model, cheap_model or model, source, config)
    runner = ExperimentRunner(runtime, contract, backend=backend, allow_execution=allow_execution,
                              approved_contract_digest=approved_contract_digest)
    proposal = await run(topic, model, source, cheap_model=cheap_model, config=config,
                         mode=mode, articles=articles, runtime=runtime)
    result = {'schema_version': 'sage.laboratory.v1', 'proposal': proposal.to_dict(),
              'execution': None, 'report': None, 'status': 'proposal_failed',
              'scientific_validation': 'not_performed', 'errors': []}
    if proposal.status.startswith('completed') and proposal.experiment is not None:
        result['execution'] = await runner.run(proposal.experiment)
        result['status'] = result['execution']['status']
        try:
            result['report'] = await generate_report(runtime, result['proposal'], result['execution'])
            if not result['report']['status'].startswith('completed'):
                result['status'] = 'report_incomplete'
                result['errors'].extend(result['report']['errors'])
        except SageError as error:
            result['errors'].append({'stage': 'writing', 'code': error.code})
            result['status'] = 'report_incomplete'
    result['audit'] = list(runtime.audit)
    result['usage'] = dict(runtime.usage)
    return result
