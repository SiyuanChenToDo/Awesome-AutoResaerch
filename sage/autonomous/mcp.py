"""Small stdio MCP client for the manager-owned research service.

No credentials or paper cache are written into an agent's seed repository.
The service is deliberately separate from the agent OS user and grader checkout.
"""
import json
import os
import sys
from urllib.request import Request, urlopen


TOOLS = [
    ('search', 'Search actual scholarly metadata. Use purpose=landscape, novelty, or counterevidence; retain empty searches.',
     {'query': {'type': 'string'}, 'purpose': {'type': 'string'}, 'limit': {'type': 'integer'}}),
    ('read', 'Read a retrieved paper and extract SAGE multi-section, quote-checked evidence capsules. Records unread/missing text.',
     {'paper_id': {'type': 'string'}, 'topic': {'type': 'string'}}),
    ('passages', 'Read original archived paper passages when a capsule is incomplete. Omit chunk_ids to get an outline; request at most four IDs for exact source text.',
     {'paper_id': {'type': 'string'}, 'chunk_ids': {'type': 'array', 'items': {'type': 'string'}}}),
    ('critique', 'Fresh-context adversarial review of a primary conjectures JSON file. Same-family review is advisory, never independent acceptance.',
     {'artifact_path': {'type': 'string'}, 'focus': {'type': 'string'}}),
    ('evidence', 'Return retrieved metadata, reading scopes, evidence capsules and prior review receipts for writing the research wiki.', {}),
    ('team', 'Authenticated native research team: status returns your role, next action and frozen peer proposals. Publish own proposal; review assigned peer; revise addressing every incoming issue; slot 0 synthesizes only after all rounds. Identity is assigned by the manager, never by tool arguments.',
     {'action': {'type': 'string', 'enum': ['status', 'propose', 'review', 'revise', 'synthesize']},
      'artifact_path': {'type': 'string'}, 'target_slot': {'type': 'integer'},
      'round': {'type': 'integer'},
      'proposal_sha256': {'type': 'string'},
      'issues': {'type': 'array', 'items': {'type': 'object'}},
      'decisions': {'type': 'array', 'items': {'type': 'object'}}})]


def request_service(tool, arguments):
    port = int(os.environ['SAGE_RESEARCH_PORT'])
    payload = json.dumps({'tool': tool, 'arguments': arguments}).encode()
    req = Request(f'http://127.0.0.1:{port}/tool', data=payload,
                  headers={'Content-Type': 'application/json', 'Authorization': 'Bearer ' + os.environ['SAGE_RESEARCH_TOKEN']})
    with urlopen(req, timeout=600) as response:
        return json.load(response)


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
                    'required': list(p) if n in ('read', 'critique') else (['query'] if n == 'search' else (['paper_id'] if n == 'passages' else (['action'] if n == 'team' else []))),
                    'additionalProperties': False}} for n, d, p in TOOLS]}
            elif method == 'tools/call':
                params = msg['params']
                if params['name'] not in {x[0] for x in TOOLS}:
                    raise ValueError('Unknown research tool')
                value = request_service(params['name'], params.get('arguments', {}))
                result = {'content': [{'type': 'text', 'text': json.dumps(value, ensure_ascii=False)}],
                          'isError': bool(value.get('error'))}
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
