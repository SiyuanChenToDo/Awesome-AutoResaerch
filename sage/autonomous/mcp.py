"""Small stdio MCP client for the manager-owned research service.

No credentials or paper cache are written into an agent's seed repository.
The service is deliberately separate from the agent OS user and grader checkout.
"""
import json
import os
import sys
from urllib.request import Request, urlopen

from ..arxiv import ArxivSource


# Transport bytes, not a limit on scientific claim count or an evidence summary.
MAX_TOOL_RESULT_BYTES = 8 * 1024 * 1024


def oversized_result(observed_bytes):
    return {'error': 'ToolResultTooLarge', 'code': 'tool_result_too_large',
            'limit_bytes': MAX_TOOL_RESULT_BYTES,
            'observed_bytes_at_least': observed_bytes,
            'result_scope': 'complete_result_refused_no_partial_evidence',
            'next_action': ('Request a smaller evidence scope: read(paper_id, topic) for one actually retrieved '
                            'paper, or passages(paper_id) for its outline followed by explicit chunk_ids. '
                            'The rejected payload is not evidence and no uncertainty label was dropped.')}


def result_content(value):
    """Return the entire JSON packet, or a complete JSON refusal, never a slice."""
    text = json.dumps(value, ensure_ascii=False)
    size = len(text.encode('utf-8'))
    if size > MAX_TOOL_RESULT_BYTES:
        value = oversized_result(size)
        text = json.dumps(value, ensure_ascii=False)
    return {'content': [{'type': 'text', 'text': text}], 'isError': bool(value.get('error'))}


TOOLS = [
    ('search', 'Search actual scholarly metadata. Use purpose=landscape, novelty, or counterevidence; retain empty searches. '
     + ArxivSource.query_instructions + ' The receipt records the actual literal AND query, provider failures and cooldown. '
     'Copy exact returned paper_id values for read; this keyword tool does not resolve an arbitrary arXiv ID. '
     'Check reading_limits: metadata without abstract/supported full text cannot produce a card. '
     'Fallback results still require relevance checks; suggested queries have not been executed.',
     {'query': {'type': 'string'}, 'purpose': {'type': 'string'}, 'limit': {'type': 'integer'}}),
    ('read', 'Read a retrieved paper into one shared source-bound and semantically screened card for the run topic. topic records your requested focus; the receipt makes any mismatch explicit. Use passages to investigate a different focus. Records unread/missing text.',
     {'paper_id': {'type': 'string'}, 'topic': {'type': 'string'}}),
    ('passages', 'Read original archived paper passages when a capsule is incomplete. Omit chunk_ids to get an outline; request at most four IDs for exact source text.',
     {'paper_id': {'type': 'string'}, 'chunk_ids': {'type': 'array', 'items': {'type': 'string'}}}),
    ('critique', 'Fresh-context adversarial review of a primary conjectures JSON file. Same-family review is advisory, never independent acceptance.',
     {'artifact_path': {'type': 'string'}, 'focus': {'type': 'string'}}),
    ('evidence', 'Return retrieved metadata, reading scopes, evidence capsules and prior review receipts for writing the research wiki. '
     'Filter with paper_ids (exact IDs; unknown ones come back under unknown_paper_ids) and include (subset of papers/cards/reviews/searches; '
     'paper_ids filters only the papers/cards sections, reviews/searches stay run-wide). Oversized full dumps are archived: the response '
     'becomes an archived pointer whose output_file under .coral/public/tool-archive/ is readable from the native shell.',
     {'paper_ids': {'type': 'array', 'items': {'type': 'string'}},
      'include': {'type': 'array', 'items': {'type': 'string'}}}),
    ('protocol_schema', 'Get the canonical scientific protocol schema: encodings, primary endpoints, uncertainty decisions and resource assumptions.', {}),
    ('report', 'Render complete Chinese CONJECTURES.md from the current registered primary JSON. Binds the SHA, version, all scientific fields and separate explanatory narrative. Re-render after each revision.',
     {'artifact_path': {'type': 'string'}, 'narrative': {'type': 'string'}}),
    ('team', 'Authenticated native research team: status returns a compact view (phase, round, role, next action, counts, frozen slot list '
     'plus snapshot_file/snapshot_sha256 pointers to the all-agent snapshot at .coral/public/team-snapshot.json). Pass sections '
     '(e.g. ["frozen_proposals","incoming_issues","syntheses","peer_advice_audits"]) or detail="full" to inline full sections in one call. '
     'Publish own proposal; review assigned peer; revise addressing every incoming issue; slot 0 synthesizes only after all rounds. '
     'Identity is assigned by the manager, never by tool arguments.',
     {'action': {'type': 'string', 'enum': ['status', 'propose', 'review', 'revise', 'synthesize']},
      'artifact_path': {'type': 'string'}, 'target_slot': {'type': 'integer'},
      'round': {'type': 'integer'},
      'proposal_sha256': {'type': 'string'},
      'sections': {'type': 'array', 'items': {'type': 'string'}},
      'detail': {'type': 'string', 'enum': ['full']},
      'issues': {'type': 'array', 'items': {'type': 'object'}},
      'decisions': {'type': 'array', 'items': {'type': 'object'}}})]


def request_service(tool, arguments):
    port = int(os.environ['SAGE_RESEARCH_PORT'])
    payload = json.dumps({'tool': tool, 'arguments': arguments}).encode()
    req = Request(f'http://127.0.0.1:{port}/tool', data=payload,
                  headers={'Content-Type': 'application/json', 'Authorization': 'Bearer ' + os.environ['SAGE_RESEARCH_TOKEN']})
    with urlopen(req, timeout=1800) as response:
        body = response.read(MAX_TOOL_RESULT_BYTES + 1)
        if len(body) > MAX_TOOL_RESULT_BYTES:
            return oversized_result(len(body))
        return json.loads(body)


def main():
    for line in sys.stdin:
        try:
            msg = json.loads(line)
            if 'id' not in msg:
                continue
            method = msg.get('method')
            if method == 'initialize':
                result = {'protocolVersion': '2024-11-05', 'capabilities': {'tools': {}},
                          'serverInfo': {'name': 'sage-research', 'version': '1.0.0'}}
            elif method == 'tools/list':
                result = {'tools': [{'name': n, 'description': d, 'inputSchema': {'type': 'object', 'properties': p,
                    'required': list(p) if n in ('read', 'critique') else (['artifact_path'] if n == 'report' else (['query'] if n == 'search' else (['paper_id'] if n == 'passages' else (['action'] if n == 'team' else [])))),
                    'additionalProperties': False}} for n, d, p in TOOLS]}
            elif method == 'tools/call':
                params = msg['params']
                if params['name'] not in {x[0] for x in TOOLS}:
                    raise ValueError('Unknown research tool')
                value = request_service(params['name'], params.get('arguments', {}))
                result = result_content(value)
            elif method == 'ping':
                result = {}
            else:
                print(json.dumps({'jsonrpc': '2.0', 'id': msg['id'], 'error': {'code': -32601, 'message': 'Unknown method'}}), flush=True)
                continue
            print(json.dumps({'jsonrpc': '2.0', 'id': msg['id'], 'result': result}), flush=True)
        except Exception as exc:
            # Do not expose HTTP headers, provider errors or credential-bearing reprs.
            if isinstance(locals().get('msg'), dict) and 'id' in msg:
                print(json.dumps({'jsonrpc': '2.0', 'id': msg['id'], 'result': {
                    'isError': True, 'content': [{'type': 'text', 'text': 'Research tool failed: ' + type(exc).__name__}]}}), flush=True)


if __name__ == '__main__':
    main()
