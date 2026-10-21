"""Execute ARIS's pinned original review gate, not a simulated replacement.

Upstream: wanshuiyin/Auto-claude-code-research-in-sleep, MIT (c) 2026 wanshuiyin.
Owned adapter; upstream bytes remain external. See NOTICE.md.
"""
import asyncio
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from ..errors import ConfigurationError

ARIS_COMMIT = '15c0b799e6cd5fbc4da381a5786dd0bc2cdf15ee'
GATE_SHA256 = 'fc0830dee82349ee92e4ab1ae7b13ed8dd584456e6e521b179ebc2cdb5390a45'


def family(model):
    value = (model or '').lower()
    for name, pattern in [('deepseek', r'deepseek'), ('openai', r'(^|[/\-])(gpt|o[134])'),
                          ('anthropic', r'claude'), ('google', r'gemini'), ('qwen', r'qwen')]:
        if re.search(pattern, value):
            return name
    return 'unknown'


def reviewer_from_env(*, timeout, env=None):
    """Optional independent HTTP reviewer; no silent change of provider or model."""
    env = dict(os.environ if env is None else env)
    if not env.get('SAGE_REVIEWER_MODEL'):
        return None
    for suffix in ('MODEL_PROVIDER', 'OPENAI_BASE_URL', 'OPENAI_API_KEY', 'IS_AZURE',
                   'AZURE_OPENAI_KEY', 'AZURE_OPENAI_ENDPOINT', 'AZURE_OPENAI_API_VERSION',
                   'DEEPSEEK_THINKING'):
        if 'SAGE_REVIEWER_' + suffix in env:
            env['SAGE_' + suffix] = env['SAGE_REVIEWER_' + suffix]
    env['SAGE_MAIN_MODEL'] = env['SAGE_REVIEWER_MODEL']
    from ..providers import OpenAIModel
    return OpenAIModel.from_env(role='main', env=env, timeout=timeout)


class ArisGate:
    def __init__(self, root, *, python=sys.executable):
        self.script = Path(root).absolute() / 'tools' / 'review_gate.py'
        self.python = str(python)
        if not self.script.is_file() or hashlib.sha256(self.script.read_bytes().replace(b'\r\n', b'\n')).hexdigest() != GATE_SHA256:
            raise ConfigurationError('ARIS review gate does not match the pinned audited source')

    async def evaluate(self, *, score, verdict, executor_model, reviewer_model):
        command = [self.python, str(self.script), '--round-backend', 'llm-chat', '--score', str(score),
                   '--verdict', verdict, '--executor-model', executor_model, '--reviewer-model', reviewer_model]
        env = {k:v for k,v in os.environ.items() if k in ('PATH', 'SYSTEMROOT', 'TEMP', 'TMP', 'LANG')}
        try:
            result = await asyncio.to_thread(subprocess.run, command, capture_output=True, text=True, timeout=5, env=env)
            if result.returncode or len(result.stdout) > 8000:
                raise ValueError
            value = json.loads(result.stdout)
            if set(value) != {'decision','next_backend','requires_external_acquittal','identity_assurance','reason'}:
                raise ValueError
        except (OSError, subprocess.TimeoutExpired, ValueError):
            raise ConfigurationError('Pinned ARIS gate execution failed; no acceptance was granted') from None
        return {'upstream_commit': ARIS_COMMIT, 'tool_sha256': GATE_SHA256, 'executed': True, **value}
