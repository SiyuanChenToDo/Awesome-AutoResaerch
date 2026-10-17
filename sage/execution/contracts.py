"""Frozen development evaluation. Hashes detect changes; they are not approval signatures."""
from dataclasses import dataclass, asdict
import hashlib
import json
import math
from typing import Protocol
from ..errors import ConfigurationError


def finite_number(value):
    try:
        return type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        return False


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


@dataclass(frozen=True)
class EvaluationContract:
    protocol_id: str
    dataset_id: str
    split: str
    features: tuple[float, ...]
    targets: tuple[float, ...]
    metric: str = 'mse'
    max_attempts: int = 3
    max_repairs: int = 1
    timeout_seconds: float = 10
    stopping_rule: str = 'attempt_budget_or_zero_loss'
    evaluator_version: str = 'sage.scalar-mse.v1'

    def __post_init__(self):
        for key in ('protocol_id', 'dataset_id'):
            if not isinstance(getattr(self, key), str) or not getattr(self, key).strip():
                raise ConfigurationError('Contract identity must be nonempty')
        if self.split != 'development' or self.metric != 'mse' or self.evaluator_version != 'sage.scalar-mse.v1':
            raise ConfigurationError('Only fixed development scalar MSE evaluation is implemented')
        if self.stopping_rule != 'attempt_budget_or_zero_loss':
            raise ConfigurationError('Unsupported stopping rule')
        for key in ('features', 'targets'):
            values = getattr(self, key)
            if not isinstance(values, tuple) or not values or len(values) > 10000 or any(not finite_number(v) for v in values):
                raise ConfigurationError('Contract data must be immutable finite numeric tuples')
        if len(self.features) != len(self.targets):
            raise ConfigurationError('Feature and target counts differ')
        for key, lower, upper in (('max_attempts', 1, 20), ('max_repairs', 0, 5)):
            if type(getattr(self, key)) is not int or not lower <= getattr(self, key) <= upper:
                raise ConfigurationError('Invalid attempt/repair budget')
        if not finite_number(self.timeout_seconds) or not 0 < self.timeout_seconds <= 300:
            raise ConfigurationError('Invalid execution timeout')

    @property
    def sha256(self):
        return digest(asdict(self))

    def public_record(self):
        value = asdict(self)
        value.pop('targets')
        value['target_digest'] = digest(self.targets)
        return value

    def evaluate(self, predictions):
        if not isinstance(predictions, list) or len(predictions) != len(self.targets) or any(not finite_number(x) for x in predictions):
            raise ValueError('Predictions must match the frozen finite numeric output contract')
        score = sum((a-b)**2 for a,b in zip(predictions, self.targets))/len(self.targets)
        if not math.isfinite(score):
            raise ValueError('Metric overflow')
        return {'mse': score}


class ExecutionBackend(Protocol):
    """Trusted operator-supplied capability, not created by model output."""
    fixture: bool
    async def predict(self, code: str, features: tuple, *, timeout: float) -> list: ...


class BackendExecutionError(ValueError):
    """Backend-authored message; diagnostic is bounded untrusted candidate output only.

    Never construct this with host command errors, environment or provider bodies.
    """
    def __init__(self, message, *, diagnostic=''):
        super().__init__(message)
        self.diagnostic = diagnostic[:4000]
