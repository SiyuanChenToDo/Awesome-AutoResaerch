# Method adapted from ARIS novelty-check / idea-creator, MIT (c) 2026 wanshuiyin.
# MODIFIED 2026-10-18: typed bounded screening, supplied-ID checks, explicit unknown,
# actual-response receipts and optional original ARIS gate. See NOTICE.md.
"""Claim-level screening inside the same SAGE proposal and discussion controller."""
import json
from ..checkpoints import digest
from ..errors import InvalidResponse, TransientProviderError, ValidationError
from ..types import NoveltyAssessment, paper_record
from ..integrations.aris import family


def checked_claims(text, source_ids, config):
    try:
        values = json.loads(text)
        if not isinstance(values, list) or not 1 <= len(values) <= config.max_research_claims:
            raise ValueError
        for row in values:
            if set(row) != {'statement','kind','source_ids','queries','falsifier'}:
                raise ValueError
            if row['kind'] not in ('method','finding','evaluation'):
                raise ValueError
            if any(not isinstance(row[k], str) or not 1 <= len(row[k]) <= 650 for k in ('statement','falsifier')):
                raise ValueError
            ids, queries = row['source_ids'], row['queries']
            if not isinstance(ids, list) or not ids or any(not isinstance(x, str) or x not in source_ids for x in ids) or len(set(ids)) != len(ids):
                raise ValueError
            if not isinstance(queries, list) or not 1 <= len(queries) <= config.queries_per_claim or any(not isinstance(x, str) or not 1 <= len(x) <= 120 for x in queries) or len(set(queries)) != len(queries):
                raise ValidationError('claim_queries_'+str(config.queries_per_claim),'queries')
        if len({r['statement'].casefold() for r in values}) != len(values):
            raise ValueError
    except (ValueError, TypeError, KeyError):
        raise InvalidResponse('Claims require bounded statements, falsifiers, unique queries and supplied source IDs') from None
    return [{'claim_id': f'c{i+1}', **row} for i,row in enumerate(values)]


def checked_assessment(text, corpus):
    try:
        value = json.loads(text)
        if set(value) != {'overall_verdict','combination_prior_id','score','verdict','uncertainty','assessments'}:
            raise ValueError
        if value['overall_verdict'] not in ('overlap','distinct_within_retrieved','insufficient_evidence'):
            raise ValueError
        if type(value['score']) is not int or not 1 <= value['score'] <= 10 or value['verdict'] not in ('ready','almost','not ready'):
            raise ValueError
        if not isinstance(value['uncertainty'], str) or not 1 <= len(value['uncertainty']) <= 1000:
            raise ValueError
        rows = value['assessments']
        if not isinstance(rows,list) or len(rows) != len(corpus) or {r['claim_id'] for r in rows} != set(corpus):
            raise ValueError
        for row in rows:
            if set(row) != {'claim_id','status','closest_paper_id','overlap','delta','evidence_limit','decisive_test'}:
                raise ValueError
            if row['status'] not in ('overlap','distinct_within_retrieved','insufficient_evidence'):
                raise ValueError
            ids = corpus[row['claim_id']]
            if row['closest_paper_id'] not in ids and not (not ids and row['closest_paper_id'] is None and row['status'] == 'insufficient_evidence'):
                raise ValueError
            if any(not isinstance(row[k],str) or not 1 <= len(row[k]) <= 1000 for k in ('overlap','delta','evidence_limit','decisive_test')):
                raise ValueError
        all_ids = set().union(*corpus.values())
        if value['combination_prior_id'] is not None and value['combination_prior_id'] not in all_ids:
            raise ValueError
        if value['overall_verdict'] == 'overlap' and not value['combination_prior_id']:
            raise ValueError
    except (ValueError, TypeError, KeyError):
        raise InvalidResponse('Each claim needs one assessment with supplied comparator IDs; whole-idea overlap needs named prior work') from None
    return value


async def screen_claims(runtime, discovery, idea, topic):
    config = runtime.config
    cards = getattr(runtime, 'evidence_cards', {})
    if not cards:
        return NoveltyAssessment('not_established', [], [], 'No read source cards available for claim decomposition.')
    evidence = [{'paper_id': key, 'scope':e.paper.evidence_scope, 'capsule':e.capsule,
                 'idea':e.idea if not e.capsule else None} for key,e in cards.items()]
    prompt = (f'Topic: {topic}\nIDEA: {idea}\nREAD_EVIDENCE: ' + json.dumps(evidence, ensure_ascii=False) +
        f'\nExtract 1-{config.max_research_claims} distinct core proposed claims, not facts asserted as established. '
        'Separate mechanism innovation from a possible new finding or evaluation contribution. '
        'For each cite actual read source IDs as context (not proof of the proposal), state a concrete falsifier, '
        f'and 1-{config.queries_per_claim} unique short search queries, choosing within that limit from problem/mechanism/history aspects. '
        'Use 2-5 essential terms per query, not a conjunction of every control. No fixed recent-year exclusion. '
        'Return <claims>[{"statement":"...","kind":"method|finding|evaluation","source_ids":["supplied ID"],'
        '"queries":["short terms"],"falsifier":"..."}]</claims>. Max 650 characters per statement/falsifier. '
        f'HARD LIMIT: at most {config.queries_per_claim} query strings per claim, not three by default.')
    queries, papers, claims = [], {}, []
    try:
        response = await runtime.ask('review.claims.extract', prompt, ('claims',),
            validate=lambda r: checked_claims(r['claims'], set(cards), config))
        claims = checked_claims(response['claims'], set(cards), config)
        inputs, corpus = [], {}
        for claim in claims:
            found, attempted = {}, []
            for query in claim['queries']:
                # Comparison discovery favors recall. Keep up to six metadata
                # candidates in provider order and let the explicit comparison
                # assess overlap; semantic ranking is for anchor discovery.
                batch, tried = await discovery.search_expanded(query, limit=6, rerank=False)
                attempted += tried
                found.update({p.paper_id:p for p in batch})
            queries += attempted
            papers.update(found)
            # Include read seed work explicitly, without pretending it was freshly retrieved.
            records = {key: {'paper':paper_record(e.paper), 'capsule':e.capsule, 'acquisition':'read_input'}
                       for key,e in cards.items() if key in claim['source_ids']}
            for key,paper in found.items():
                records[key] = {'paper':paper_record(paper), 'capsule':cards[key].capsule if key in cards else None,
                                'acquisition':'fresh_retrieval' if getattr(runtime.source,'fresh_search',True) else 'recorded_corpus_lookup'}
            corpus[claim['claim_id']] = set(records)
            claim.update(searched_queries=attempted, retrieved_source_ids=list(found),
                         coverage={'fresh_retrieval':bool(found) and getattr(runtime.source,'fresh_search',True), 'systematic_search':False},
                         input_sha256=digest({'claim':claim['statement'],'records':records}))
            inputs.append({'claim':claim, 'sources':list(records.values())})
            runtime.event('review.claims.retrieval','recorded', claim_id=claim['claim_id'],
                          attempted_queries=attempted, fresh_ids=list(found), read_input_ids=claim['source_ids'])
        review_prompt = (f'Topic: {topic}\nIDEA: {idea}\nCLAIM_DOSSIER: ' + json.dumps(inputs, ensure_ascii=False) +
            '\nIndependently assess every claim against ONLY its supplied sources. Give overlap, actual delta, '
            'reading limits and the strongest alternative explanation/decisive test. Neighboring research is not '
            'automatic rejection; known components may yield a new finding or combination. Whole-idea overlap '
            'requires naming supplied prior work that contains the combination/result, not merely one component. '
            'Missing detail in an abstract or selected chunk is not absence from the paper. Empty or inadequate '
            'search means insufficient_evidence, never novelty proven. Scores and ready/almost only advise '
            'whether to continue exploration; they are not scientific acceptance. '
            'Return <assessment>{"overall_verdict":"overlap|distinct_within_retrieved|insufficient_evidence",'
            '"combination_prior_id":null,"score":5,"verdict":"ready|almost|not ready","uncertainty":"...",'
            '"assessments":[{"claim_id":"c1","status":"overlap|distinct_within_retrieved|insufficient_evidence",'
            '"closest_paper_id":"supplied ID or null only if no sources","overlap":"...","delta":"...",'
            '"evidence_limit":"...","decisive_test":"..."}]}</assessment>. '
            'Exactly one row per supplied claim, max 1000 characters per text field. Be concise.')
        response = await runtime.ask('review.claims.assess', review_prompt, ('assessment',), reviewer=True,
            validate=lambda r: checked_assessment(r['assessment'], corpus))
        value = checked_assessment(response['assessment'], corpus)
        by_id = {r['claim_id']:r for r in value['assessments']}
        for claim in claims:
            row = by_id[claim['claim_id']]
            if not claim['coverage']['fresh_retrieval'] and row['status'] == 'distinct_within_retrieved':
                row['status'] = 'insufficient_evidence'
                row['evidence_limit'] += ' No fresh comparison work was retrieved.'
            claim['assessment'] = row
        overall = value['overall_verdict']
        if overall == 'distinct_within_retrieved' and any(c['assessment']['status'] == 'insufficient_evidence' for c in claims):
            overall = 'insufficient_evidence'
        event = next((e for e in reversed(runtime.audit) if e['stage'] == 'review.claims.assess' and e['status'] == 'response_receipt'), None)
        model = runtime.reviewer_model or runtime.main_model
        requested = getattr(getattr(model,'config',None),'model','fixture')
        executor = getattr(getattr(runtime.main_model,'config',None),'model','fixture')
        returned = event.get('returned_model') if event else None
        ef, rf = family(executor), family(returned or requested)
        relation = 'same_family' if ef == rf != 'unknown' else ('cross_family' if ef != 'unknown' and rf != 'unknown' else 'unknown')
        receipt = {'schema_version':'sage.review_receipt.v1', 'artifact_sha256':digest(idea),
                   'screening_status':'completed',
                   'dossier_sha256':digest(inputs), 'requested_model':requested, 'returned_model':returned,
                   'executor_model':executor, 'independence':relation,
                   'identity_assurance':'provider_response_and_config_not_independent_attestation',
                   'acceptance_status':'provisional', 'score':value['score'], 'verdict':value['verdict'],
                   'response_receipt':event, 'scientific_validation':'not_performed', 'native_aris_gate':None}
        if runtime.aris_gate:
            receipt['native_aris_gate'] = await runtime.aris_gate.evaluate(score=value['score'],verdict=value['verdict'],
                executor_model=executor, reviewer_model=returned or requested)
        if relation == 'cross_family' and event and receipt['native_aris_gate'] and receipt['native_aris_gate']['decision'] == 'stop':
            receipt['acceptance_status'] = 'accepted_for_further_research_only'
        for e in cards.values():
            papers.setdefault(e.paper.paper_id, e.paper)
        status = {'overlap':'similar_work_found', 'distinct_within_retrieved':'no_similar_work_found',
                  'insufficient_evidence':'not_established'}[overall]
        return NoveltyAssessment(status, queries, list(papers.values()),value['uncertainty'],
            value['combination_prior_id'] if overall == 'overlap' else None,
            basis='claim_level_model_comparison_not_global_novelty',comparisons=value['assessments'],
            research_claims=claims,review_receipt=receipt)
    except (InvalidResponse, TransientProviderError) as error:
        if isinstance(error,TransientProviderError) and not runtime.allow_incomplete_novelty:
            raise
        runtime.event('review.claims','not_established',reason=error.code,partial_claims=claims)
        return NoveltyAssessment('not_established',queries,list(papers.values()),
            'Claim screening incomplete; preserved partial evidence does not establish novelty.', research_claims=claims,
            review_receipt={'screening_status':'failed','error_code':error.code,'scientific_validation':'not_performed'})
