"""Extension contract only. SAGE does not run generated code or experiments."""
from typing import Protocol
from ..types import ExperimentPlan


class ExperimentExecutor(Protocol):
    """Implement separately with an authorized frozen protocol and real isolation.

    Merely implementing this interface is not approval to run an experiment.
    The current SAGE orchestrator never invokes it.
    """
    async def execute(self, plan: ExperimentPlan, *, approved_protocol_id: str) -> dict: ...
