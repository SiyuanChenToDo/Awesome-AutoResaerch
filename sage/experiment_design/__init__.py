# Derived from CoI-Agent generate_experiment/refine_experiment/improve_experiment,
# Apache-2.0. MODIFIED for SAGE 2026-10-17: explicit proposal status and revisions.
# Source and modification map: NOTICE.md and docs/sage-migration.md.
"""Generate and iteratively refine experimental plans without executing them."""
from ..types import ExperimentPlan
from .contract import INSTRUCTIONS, parse_contract
from ..literature import paper_content
from .prompts import (get_deep_generate_experiment_prompt, get_deep_refine_experiment_prompt,
                      get_deep_refine_experiment_search_query_prompt, get_deep_paper_info_prompt_for_refine_experiment)


class ExperimentDesign:
    def __init__(self, runtime, discovery, review):
        self.runtime, self.discovery, self.review = runtime, discovery, review

    async def plan_response(self, stage, prompt):
        # Finite output specification applies to generation and every refinement.
        words = max(80, self.runtime.config.max_tokens_per_call // 4)
        return await self.runtime.ask(stage, prompt + INSTRUCTIONS +
            f'\nKeep prose below {words} words; complete both required tags within the output cap.',
            ('experiment', 'plan_contract'), validate=lambda r: parse_contract(r['plan_contract']))

    async def generate(self, candidate, topic):
        related = [{'paper_id': e.paper.paper_id, 'capsule': e.capsule} if e.capsule else e.experiment
                   for e in candidate.chain.evidence]
        response = await self.plan_response('experiment_design.generate', get_deep_generate_experiment_prompt(candidate.idea, related, candidate.chain.entities))
        plan = ExperimentPlan(response['experiment'], design_contract=parse_contract(response['plan_contract']))
        # Save immediately so partial state survives later provider failure.
        self.current_plan = plan
        literature_review = await self.review.literature_suggestions(candidate, topic)
        for number in range(1, self.runtime.config.refinement_rounds + 1):
            suggestion = await self.review.experiment(candidate.idea, plan.proposal, candidate.chain.entities)
            suggestion += '\n' + literature_review['suggestions']
            query = await self.runtime.ask('experiment_design.refine_query', get_deep_refine_experiment_search_query_prompt(plan.proposal, suggestion),
                                           ('query',), allow_empty=('query',))
            infos = []
            if query['query']:
                papers = await self.discovery.optional_search(query['query'], limit=2)
                for paper in papers:
                    response = await self.runtime.ask('experiment_design.paper_info', get_deep_paper_info_prompt_for_refine_experiment(paper_content(paper), plan.proposal, suggestion),
                                                      ('info',), cheap=True)
                    infos.append({'paper_id': paper.paper_id, 'title': paper.title, 'url': paper.url, 'scope': paper.evidence_scope, 'info': response['info']})
            response = await self.plan_response('experiment_design.refine', get_deep_refine_experiment_prompt(plan.proposal, suggestion, infos, candidate.chain.entities))
            plan.revisions.append({'round': number, 'previous_proposal': plan.proposal, 'suggestion': suggestion,
                                   'literature_review': literature_review, 'query': query['query'], 'paper_infos': infos,
                                   'proposal': response['experiment']})
            plan.proposal = response['experiment']
            plan.design_contract = parse_contract(response['plan_contract'])
        return plan
