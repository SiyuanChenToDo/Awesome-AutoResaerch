# Adapted from Agent Laboratory MLESolver, MIT (c) 2025 Samuel Schmidgall.
# MODIFIED 2026-10-17: finite generation/repair, immutable evaluation, opt-in backend.
# License: LICENSES/Agent-Laboratory-MIT.txt; docs/agent-laboratory-migration.md.
"""Candidate engineering; no generated code is executed on the host."""
import ast
import asyncio
import hashlib
from typing import Protocol
from ..types import ExperimentPlan
from ..errors import ConfigurationError, SageError
from .contracts import EvaluationContract, ExecutionBackend, digest, BackendExecutionError
from .commands import apply_command, CommandFormatError
from . import prompts


class ExperimentExecutor(Protocol):
    async def execute(self, plan: ExperimentPlan, *, approved_protocol_id: str) -> dict: ...


class ExperimentRunner:
    def __init__(self, runtime, contract: EvaluationContract, *, backend: ExecutionBackend | None = None,
                 allow_execution=False, approved_contract_digest=None):
        if backend is not None and (allow_execution is not True or approved_contract_digest != contract.sha256):
            raise ConfigurationError('Execution requires explicit opt-in and exact approved contract digest')
        if allow_execution and backend is None:
            raise ConfigurationError('Execution requires an explicitly configured backend')
        self.runtime, self.contract, self.backend = runtime, contract, backend

    async def run(self, plan: ExperimentPlan, *, on_progress=None):
        contract_digest = self.contract.sha256
        result = {'schema_version': 'sage.execution.v1', 'status': 'running',
                  'contract': self.contract.public_record(), 'contract_digest': contract_digest,
                  'attempts': [], 'selected_attempt_id': None, 'fixture': bool(self.backend and self.backend.fixture),
                  'scientific_validation': 'not_performed', 'errors': []}
        if on_progress:
            on_progress(result)
        current, reflection, best, repair_count = '', '', None, 0
        repair_error = None
        for number in range(1, self.contract.max_attempts + 1):
            attempt = {'attempt_id': f'attempt-{number}', 'code': '', 'status': 'started', 'metrics': {},
                       'error': None, 'code_sha256': None, 'kind': 'repair' if repair_error else 'candidate'}
            result['attempts'].append(attempt)  # malformed commands and model failures consume budget too
            self.runtime.event('execution.attempt', 'started', attempt_id=attempt['attempt_id'])
            try:
                if self.contract.sha256 != contract_digest:
                    raise ConfigurationError('Frozen contract changed')
                if repair_error:
                    prompt = prompts.repair_prompt(current, repair_error,
                        rejected_command=result['attempts'][-2].get('command', ''),
                        contract=self.contract.public_record())
                    stage = 'execution.repair'
                else:
                    history = [{k:v for k,v in a.items() if k != 'code'} for a in result['attempts'][:-1]]
                    prompt = prompts.generation_prompt(plan.proposal, self.contract.public_record(), current, history, reflection)
                    stage = 'execution.generate'
                answer = await self.runtime.ask(stage, prompt, ('command',))
                attempt['command'] = answer['command']
                candidate = apply_command(answer['command'], current)
                attempt['code'] = candidate
                attempt['code_sha256'] = hashlib.sha256(candidate.encode()).hexdigest()
                current = candidate
                ast.parse(candidate)  # syntax only; not a security check
                if self.backend is None:
                    attempt['status'] = 'syntax_valid_unexecuted'
                    result['status'] = 'dry_run'
                    break
                predictions = await asyncio.wait_for(self.backend.predict(candidate, self.contract.features,
                        timeout=min(self.contract.timeout_seconds, self.runtime.remaining())),
                        timeout=min(self.contract.timeout_seconds + 5, self.runtime.remaining()))
                if self.contract.sha256 != contract_digest:
                    raise ConfigurationError('Frozen contract changed during execution')
                attempt['metrics'] = self.contract.evaluate(predictions)
                attempt['predictions'] = predictions
                attempt['status'] = 'evaluated_fixture' if result['fixture'] else 'evaluated_development'
                attempt['output_digest'] = digest(predictions)
                if best is None or attempt['metrics']['mse'] < best['metrics']['mse']:
                    best = attempt
                    result['selected_attempt_id'] = best['attempt_id']
                repair_error, repair_count = None, 0
                if attempt['metrics']['mse'] == 0:
                    result['status'] = 'completed_fixture' if result['fixture'] else 'completed_development'
                    break
                current = best['code']
                if number < self.contract.max_attempts:
                    reflection = (await self.runtime.ask('execution.reflect', prompts.reflection_prompt(current, best['metrics']), ('reflection',)))['reflection']
                    attempt['reflection'] = reflection
            except SageError as error:
                # Runtime already counted failed API calls. Do not leak arbitrary provider bodies.
                if not attempt['status'].startswith('evaluated_'):
                    attempt['status'] = 'failed'
                    attempt['error'] = error.code
                else:
                    attempt['reflection_error'] = error.code
                result['errors'].append({'code': error.code, 'attempt_id': attempt['attempt_id']})
                result['status'] = 'stopped'
                break
            except (ValueError, SyntaxError, OverflowError, asyncio.TimeoutError, OSError) as error:
                attempt['status'] = 'failed'
                attempt['error'] = type(error).__name__
                diagnostic = None
                if isinstance(error, SyntaxError):
                    diagnostic = f'Syntax error at line {error.lineno}, column {error.offset}: {error.msg}'
                elif isinstance(error, BackendExecutionError):
                    diagnostic = error.diagnostic
                elif isinstance(error, CommandFormatError):
                    diagnostic = str(error)
                elif isinstance(error, ValueError):
                    # Parser/evaluator messages are owned; generic backend ValueError bodies are not exposed.
                    diagnostic = 'Candidate command, output or backend contract rejected; inspect recorded source and required schema.'
                attempt['diagnostic'] = diagnostic
                repair_error = diagnostic or attempt['error']
                repair_count += 1
                if repair_count > self.contract.max_repairs:
                    result['status'] = 'repair_budget_exhausted'
                    break
            except Exception:
                attempt['status'] = 'failed'
                attempt['error'] = 'backend_error'
                repair_error = 'backend_error'
                repair_count += 1
                if repair_count > self.contract.max_repairs:
                    result['status'] = 'repair_budget_exhausted'
                    break
            finally:
                if on_progress:
                    on_progress(result)
                self.runtime.event('execution.attempt', attempt['status'], attempt_id=attempt['attempt_id'], error=attempt['error'])
        if result['status'] == 'running':
            result['status'] = 'attempt_budget_exhausted' if best is not None else 'no_valid_candidate'
        if on_progress:
            on_progress(result)
        return result
