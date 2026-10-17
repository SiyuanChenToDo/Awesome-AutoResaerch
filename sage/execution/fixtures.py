"""Owned, trusted scalar fixture. Model-generated source is NEVER executed here."""
from .contracts import EvaluationContract
from ..fixtures import FixtureModel

BASELINE_CODE = 'import json\nxs = json.load(open("/input/features.json"))["features"]\nprint(json.dumps([x for x in xs]))'
IMPROVED_CODE = 'import json\nxs = json.load(open("/input/features.json"))["features"]\nprint(json.dumps([2*x for x in xs]))'


def fixture_contract():
    return EvaluationContract('fixture-protocol-v1', 'synthetic-double-v1', 'development', (0, 1, 2), (0, 2, 4))


class TrustedFixtureBackend:
    fixture = True

    async def predict(self, code, features, *, timeout):
        if code == BASELINE_CODE:
            return list(features)
        if code == IMPROVED_CODE:
            return [2*x for x in features]
        raise ValueError('Only the exact reviewed fixture source is recognized; source is not executed')


class LaboratoryFixtureModel(FixtureModel):
    def __init__(self):
        super().__init__()
        self.generations = 0
        from ..writing import FixtureReportModel
        self.report_model = FixtureReportModel()

    async def complete(self, stage, prompt, *, max_tokens):
        if stage == 'execution.generate':
            self.generations += 1
            code = BASELINE_CODE if self.generations == 1 else IMPROVED_CODE
            return f'<command>```REPLACE\n{code}\n```</command>'
        if stage == 'execution.repair':
            return f'<command>```REPLACE\n{IMPROVED_CODE}\n```</command>'
        if stage == 'execution.reflect':
            return '<reflection>Synthetic development fixture: try multiplying the scalar by two.</reflection>'
        if stage.startswith(('writing.', 'review.report')):
            return await self.report_model.complete(stage, prompt, max_tokens=max_tokens)
        return await super().complete(stage, prompt, max_tokens=max_tokens)
