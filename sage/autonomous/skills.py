"""Deliver pinned original ARIS methods as native task input, not agent claims.

Skill discovery alone does not ensure that an agent reads a skill. These five
original files are included verbatim in DSH workspace instructions on every fresh
agent launch. Hash receipts describe delivery, never methodological correctness.
"""
import hashlib
from pathlib import Path

from ..errors import ConfigurationError


REQUIRED_SKILLS = ('research-lit', 'idea-creator', 'novelty-check',
                   'research-review', 'research-refine-pipeline')


def assemble_native_task(aris_root, workflow):
    parts = ['# Runtime-provided original ARIS research methods\n\n'
             'The following pinned upstream skill files are workflow instructions, '
             'not scientific evidence. They are supplied by the runtime so that '
             'merely listing a skill cannot substitute for receiving its methods.\n']
    receipts = []
    for name in REQUIRED_SKILLS:
        relative = Path('skills') / name / 'SKILL.md'
        source = Path(aris_root) / relative
        if not source.is_file():
            raise ConfigurationError(f'Required original ARIS skill missing: {name}')
        raw = source.read_bytes()
        text = raw.decode('utf-8')
        parts.append(f'\n<original_aris_skill name="{name}">\n{text}\n</original_aris_skill>\n')
        receipts.append({'name': name, 'path': relative.as_posix(),
                         'sha256': hashlib.sha256(raw).hexdigest(), 'characters': len(text)})
    parts.append('\n# Current task and explicit API-only runtime adaptation\n\n'
                 'The task below governs tool mappings, noninteractive operation '
                 'and acceptance claims. Use the original scientific methods above; '
                 'do not invent an unavailable independent reviewer, wait for operator '
                 'choices, or claim that a delivered method has thereby been followed.\n\n' + workflow)
    task = '\n'.join(parts)
    return task, {'delivery': 'verbatim_original_files_in_native_dsh_workspace_instructions',
                  'skills': receipts, 'instruction_file': 'AGENTS.local.md',
                  'instruction_sha256': hashlib.sha256(task.encode()).hexdigest(),
                  'coral_task_sha256': hashlib.sha256(workflow.encode()).hexdigest(),
                  'scope': 'input delivery, not proof of scientific quality or independent acceptance'}
