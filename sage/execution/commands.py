# Adapted from Agent Laboratory mlesolver.py Replace/Edit, MIT (c) 2025 Samuel Schmidgall.
# MODIFIED 2026-10-17: pure non-executing parser, strict single command and bounds.
# License: LICENSES/Agent-Laboratory-MIT.txt; source map: docs/agent-laboratory-migration.md.
import re


class CommandFormatError(ValueError):
    """Owned wire-format diagnostics; never includes provider or host error text."""


def apply_command(command: str, current: str = '') -> str:
    match = re.fullmatch(r'```(REPLACE|EDIT (\d+) (\d+))\n(.*?)\n```', command.strip(), re.S)
    if not match or '```' in match[4] or not match[4].strip():
        raise CommandFormatError('Expected one fence beginning with ```REPLACE or ```EDIT N M, followed by a newline and Python source; do not put REPLACE outside a ```python fence')
    if match[1] == 'REPLACE':
        return match[4]
    start, end = int(match[2]), int(match[3])
    lines = current.splitlines()
    if not 0 <= start <= end < len(lines):
        raise CommandFormatError('EDIT requires valid zero-based inclusive line indices; use REPLACE for an empty candidate')
    return '\n'.join(lines[:start] + match[4].splitlines() + lines[end+1:])
