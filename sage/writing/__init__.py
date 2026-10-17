"""Extension contract only. There is no manuscript writer or publication runner."""
from typing import Protocol


class EvidenceWriter(Protocol):
    """A future writer must preserve claim/evidence links and unverified labels."""
    async def draft(self, *, reviewed_claims: list[dict], evidence: list[dict]) -> str: ...
