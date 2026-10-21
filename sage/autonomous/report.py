"""Render and verify current reports against the exact primary artifact.

The primary JSON never contains its own hash. A manager-generated report binds
its *bytes*, registered synthesis version, selection, and every candidate field.
This is a deterministic alignment check, not a semantic or scientific review.
Author-written Chinese discussion is preserved separately and cannot replace the
canonical scientific protocol. Old free-form reports remain readable historical
artifacts, but are never silently certified as current reports.
"""
from __future__ import annotations

import hashlib
import json
import re


REPORT_VERSION = 'sage.autonomous.report.v1'
_SECTIONS = {
    'manifest': ('<!-- SAGE_REPORT_MANIFEST_BEGIN -->', '<!-- SAGE_REPORT_MANIFEST_END -->'),
    'canonical': ('<!-- SAGE_REPORT_CANONICAL_BEGIN -->', '<!-- SAGE_REPORT_CANONICAL_END -->'),
    'narrative': ('<!-- SAGE_REPORT_NARRATIVE_BEGIN -->', '<!-- SAGE_REPORT_NARRATIVE_END -->'),
}
_LABELS = {
    'title': '标题', 'problem': '研究问题与动机', 'hypothesis': '可证伪的科学预测',
    'mechanism': '机制解释', 'assumptions': '成立条件与假设',
    'source_ids': '实际来源ID', 'closest_prior_art': '最近工作、重合与区别',
    'novelty_queries': '查新查询', 'falsification': '首轮反证实验与判定协议',
    'risks': '风险、替代解释与未解决问题', 'feasibility': '资源预算与可行性',
    'status': '验证状态', 'disposition': '保留或淘汰状态',
    'rejection_reason': '未入选或淘汰理由', 'origin': '团队来源绑定',
    'protocol': '结构化实验协议', 'scientific_protocol': '结构化实验协议',
    'selection_rationale': '选择理由', 'research_direction': '研究方向',
    'literature_landscape': '文献全景', 'open_questions': '未解决问题',
    'counterevidence': '反证与负面证据', 'limitations': '限制与未知',
}
_PROTOCOL_FIELDS = ('hypothesis', 'assumptions', 'falsification', 'protocol', 'scientific_protocol')


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def _digest(value):
    return hashlib.sha256(_json(value).encode('utf-8')).hexdigest()


def _primary(raw):
    if isinstance(raw, str):
        raw = raw.encode('utf-8')
    if not isinstance(raw, bytes):
        raise ValueError('Report binding requires the exact primary UTF-8 bytes, not a reconstructed dict')
    document = json.loads(raw.decode('utf-8'))
    if not isinstance(document, dict) or not isinstance(document.get('candidates'), list):
        raise ValueError('Report primary must contain a candidates list')
    candidates = document['candidates']
    ids = []
    for candidate in candidates:
        if not isinstance(candidate, dict) or not isinstance(candidate.get('id'), str) or not candidate['id'].strip():
            raise ValueError('Report requires nonempty candidate IDs')
        ids.append(candidate['id'])
    if not ids or len(ids) != len(set(ids)):
        raise ValueError('Report candidate IDs must be nonempty and unique')
    selected = document.get('selected_ids')
    if (not isinstance(selected, list) or not selected or
            any(not isinstance(x, str) or x not in ids for x in selected) or
            len(selected) != len(set(selected))):
        raise ValueError('Report requires distinct selected_ids from its candidate ledger')
    _json(document)
    if any(marker in _json(document) for markers in _SECTIONS.values() for marker in markers):
        raise ValueError('Primary data must not contain reserved report section markers')
    return raw, document


def _version(value):
    if value is not None and (type(value) is not int or value < 1):
        raise ValueError('synthesis_version must be a manager-registered positive integer or None')
    return value


def _protocol_snapshot(document):
    return {c['id']: {k: c[k] for k in _PROTOCOL_FIELDS if k in c}
            for c in document['candidates'] if c['id'] in document['selected_ids']}


def _value(value):
    if isinstance(value, str):
        return value.strip() or '（未填写）'
    # Arbitrary source text can contain Markdown fences. Choose a longer fence
    # rather than allowing it to escape the data block in the displayed report.
    text = json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)
    fence = '`' * max(3, max((len(x) + 1 for x in re.findall(r'`+', text)), default=3))
    return fence + 'json\n' + text + '\n' + fence


def _source_url(ident):
    if ident.startswith('arxiv:'):
        return 'https://arxiv.org/abs/' + ident[6:]
    if ident.startswith('doi:'):
        return 'https://doi.org/' + ident[4:]
    return '来源元数据见证据账本（未从ID推断网址）'


def _canonical_sections(raw, document, synthesis_version):
    sha = hashlib.sha256(raw).hexdigest()
    version = f'v{synthesis_version}' if synthesis_version is not None else '未登记（单稿按SHA绑定）'
    selected = document['selected_ids']
    lines = ['## 当前稿件与选择', '', f'- 主JSON SHA-256：`{sha}`',
             f'- 管理器登记综合版本：{version}',
             f'- 候选总数：{len(document["candidates"])}',
             '- 当前入选ID：' + '、'.join(f'`{x}`' for x in selected), '',
             '以下科学字段均从上述主JSON逐项生成；措辞、主次终点、反证和判定规则不得另行覆盖。',
             '内容对齐核验不证明引文蕴含、实验有效、新颖性成立或独立验收。', '']
    for key, value in document.items():
        if key in ('candidates', 'selected_ids'):
            continue
        lines.extend(['### ' + _LABELS.get(key, '主稿附加字段：' + key), '', _value(value), ''])
    lines.extend(['## 全部想法与实验方案', '',
                  '保留全部候选及其淘汰记录；未入选不等于已被实验否定。', ''])
    for candidate in document['candidates']:
        state = '本轮入选' if candidate['id'] in selected else '账本保留、未入选'
        lines.extend([f'### {candidate["id"]} · {state}', ''])
        for key, value in candidate.items():
            if key == 'id':
                continue
            lines.extend(['#### ' + _LABELS.get(key, '候选附加字段：' + key), '', _value(value), ''])
    sources = sorted({ident for candidate in document['candidates']
                      for ident in candidate.get('source_ids', []) if isinstance(ident, str)})
    lines.extend(['## 来源入口', '', '网址从已记录ID机械映射；未因此证明已阅读全文或主张得到支持。', ''])
    lines.extend(f'- `{ident}`：{_source_url(ident)}' for ident in sources)
    lines.extend(['', '## 当前证据边界', '',
                  '本报告是待检验猜想与协议。程序核对字节版本和字段，未执行研究实验，',
                  '未提供跨模型家族独立验收。缺失的预算、功效、原文或协议项仍是缺失，不能按零或已完成解释。'])
    return '\n'.join(lines).rstrip() + '\n'


def _narrative_errors(narrative, primary_sha, document, synthesis_version):
    errors = []
    if any(marker in narrative for markers in _SECTIONS.values() for marker in markers):
        return ['Chinese discussion must not contain reserved report section markers']
    # Other hashes (paper chunks and historical receipts) are legitimate. Only
    # reject explicit assertions about the current primary, not every 64 hex ID.
    pattern = r'(?:primary_sha256|当前主(?:JSON|稿)(?:\s*SHA(?:-256)?)?)\s*[`"\s]*[=:：]\s*[`"\s]*([a-f0-9]{64})'
    for match in re.finditer(pattern, narrative, re.IGNORECASE):
        if match.group(1).lower() != primary_sha:
            errors.append('Chinese discussion contains a stale current-primary SHA-256 assertion')
    # Reserved identity declarations have exact machine meanings; this is not
    # an attempted semantic parser of scientific prose. Historical discussion
    # such as "此前v5有缺陷" remains permitted, but an explicit *current* version
    # cannot contradict the manager registry. Remove Markdown emphasis only for
    # these human-facing labels, not arbitrary scientific words or symbols.
    plain = re.sub(r'[`*_]', '', narrative)
    key_plain = re.sub(r'[`*]', '', narrative)
    human_version = (r'(?:当前(?:综合(?:稿|版本)?|稿件(?:版本)?|版本)?|'
                     r'本(?:报告|文件|稿)(?:的)?(?:综合(?:稿|版本)?|版本)?)'
                     r'[ \t]*[：:=为是（(]*[ \t]*v(\d+)(?=$|[ \t，,。；;:：)）\n])')
    versions = [int(match.group(1)) for match in re.finditer(human_version, plain, re.I)]
    versions.extend(int(match.group(1)) for match in re.finditer(
        r'\b(?:current_)?synthesis_version["\']?\s*[=:：]\s*["`]?v?(\d+)\b', key_plain, re.I))
    if any(version != synthesis_version for version in versions):
        errors.append('Chinese discussion current synthesis version disagrees with the manager registry')
    for match in re.finditer(r'\b(?:current_)?candidate_count["\']?\s*[=:：]\s*(\d+)\b', key_plain, re.I):
        if int(match.group(1)) != len(document['candidates']):
            errors.append('Chinese discussion candidate_count disagrees with the current primary')
    for match in re.finditer(r'\b(?:current_)?selected_ids["\']?\s*[=:：]\s*(\[[^\]\n]*\])', key_plain, re.I):
        try:
            selected = json.loads(match.group(1))
        except ValueError:
            selected = None
        if selected != document['selected_ids']:
            errors.append('Chinese discussion selected_ids disagrees with the current primary')
    # These explicit field assignments belong solely in canonical protocol.
    # Reject redeclaration rather than guessing whether two endpoint names or
    # verbal decision rules mean the same thing. Normal explanations, source
    # comparisons and discussion of uncertainty are still unrestricted.
    machine_protocol = (r'(?im)^\s*(?:[-*]\s*)?["\']?(?:[A-Za-z0-9_-]+\.)?'
                        r'(?:protocol(?:\.[A-Za-z0-9_.-]+)?|primary_endpoint_ids|'
                        r'endpoints(?:\.[A-Za-z0-9_-]+)?\.role|decision_rule(?:\.[A-Za-z0-9_.-]+)?)'
                        r'["\']?\s*[=:：]')
    chinese_protocol = (r'(?m)^\s*(?:[-*]\s*)?(?:[A-Za-z0-9_-]+[.： ]+)?(?:当前)?'
                        r'(?:主指标|次指标|主要指标|次要指标|主要终点|次要终点|主终点|共同主指标|'
                        r'共同主终点|共同主要终点|实验判定规则|判定规则)\s*[：:=]')
    if re.search(machine_protocol, key_plain) or re.search(chinese_protocol, plain):
        errors.append('Chinese discussion must not redeclare reserved endpoint or decision-rule fields; update the primary protocol and regenerate its canonical sections')
    return errors


def _protocol_errors(document):
    """Delegate typed protocol rules; do not infer roles from prose substrings."""
    errors = []
    for candidate in document['candidates']:
        if candidate['id'] not in document['selected_ids'] or 'protocol' not in candidate:
            continue
        from .protocol import protocol_errors
        errors.extend(protocol_errors(candidate))
    return errors


def render_report(primary_raw, narrative='', *, synthesis_version=None):
    """Return a full Chinese-framed report; never shorten or translate research.

    ``narrative`` preserves the agent's full Chinese landscape/discussion. The
    authoritative fields and source URLs are generated from the current JSON.
    The manager version is external to the JSON to avoid a self-hash cycle.
    """
    raw, document = _primary(primary_raw)
    _version(synthesis_version)
    if not isinstance(narrative, str):
        raise ValueError('Chinese discussion must be text')
    narrative = narrative.strip() + '\n' if narrative.strip() else '（本轮没有额外中文阐释；以上保留全部原始科学字段。）\n'
    errors = _narrative_errors(narrative, hashlib.sha256(raw).hexdigest(), document, synthesis_version) + _protocol_errors(document)
    if errors:
        raise ValueError('; '.join(errors))
    canonical = _canonical_sections(raw, document, synthesis_version)
    manifest = {
        'schema_version': REPORT_VERSION,
        'primary_sha256': hashlib.sha256(raw).hexdigest(),
        'synthesis_version': synthesis_version,
        'candidate_count': len(document['candidates']),
        'candidate_ids': [c['id'] for c in document['candidates']],
        'selected_ids': document['selected_ids'],
        'scientific_protocol_sha256': _digest(_protocol_snapshot(document)),
        'canonical_section_sha256': hashlib.sha256(canonical.encode()).hexdigest(),
        'narrative_sha256': hashlib.sha256(narrative.encode()).hexdigest(),
        'narrative_semantics': 'not_independently_verified',
        'reserved_declarations': 'checked_against_primary_and_manager_registry',
        'scientific_validation': 'not_performed',
    }
    return ('# 自主科研猜想报告\n\n'
            + _SECTIONS['manifest'][0] + '\n' + json.dumps(manifest, ensure_ascii=False, indent=2) + '\n' + _SECTIONS['manifest'][1] + '\n\n'
            + _SECTIONS['canonical'][0] + '\n' + canonical + _SECTIONS['canonical'][1] + '\n\n'
            + '## 作者中文全景与补充讨论\n\n'
            + '下文保留完整中文论述；其语义尚未独立核验。当前版本、选择和协议以上方程序生成字段为准，'
            + '补充叙述不得另行设定主次终点或实验判定。\n\n'
            + _SECTIONS['narrative'][0] + '\n' + narrative + _SECTIONS['narrative'][1] + '\n')


def validate_report(primary_raw, report, *, synthesis_version=None):
    """Audit report identity *and internal contents*, without modifying files."""
    audit = {'schema_version': REPORT_VERSION, 'status': 'invalid', 'errors': [],
             'scientific_validation': 'not_performed',
             'narrative_semantics': 'not_independently_verified'}
    try:
        raw, document = _primary(primary_raw)
        _version(synthesis_version)
        text = report.decode('utf-8') if isinstance(report, bytes) else report
        if not isinstance(text, str):
            raise ValueError('Report must be UTF-8 bytes or text')
        sections = {}
        for name, (begin, end) in _SECTIONS.items():
            if text.count(begin) != 1 or text.count(end) != 1:
                audit.update(status='legacy_unverified')
                raise ValueError('Report has no unique current binding/canonical sections; legacy reports require regeneration from current primary bytes')
            start, stop = text.index(begin) + len(begin), text.index(end)
            if stop <= start or text[start:start + 1] != '\n':
                raise ValueError('Invalid report section framing')
            sections[name] = text[start + 1:stop]
        manifest = json.loads(sections['manifest'])
        if not isinstance(manifest, dict) or manifest.get('schema_version') != REPORT_VERSION:
            raise ValueError('Unsupported report binding schema')
        expected_text = render_report(raw, sections['narrative'], synthesis_version=synthesis_version)
        # Strict reconstruction disallows extra, contradictory scientific prose
        # outside the two explicitly delimited data/narrative regions too.
        if text != expected_text:
            expected_manifest = json.loads(expected_text.split(_SECTIONS['manifest'][0] + '\n', 1)[1].split(_SECTIONS['manifest'][1], 1)[0])
            for key, value in expected_manifest.items():
                if manifest.get(key) != value:
                    audit['errors'].append(f'Report manifest {key} does not match the exact current primary/report')
            if sections['canonical'] != _canonical_sections(raw, document, synthesis_version):
                audit['errors'].append('Report canonical scientific sections differ from the current JSON fields, selected IDs, candidate count or protocol')
            if not audit['errors']:
                audit['errors'].append('Report framing or content was changed outside the bound sections')
        else:
            audit.update(status='verified_alignment', primary_sha256=manifest['primary_sha256'],
                         synthesis_version=synthesis_version, candidate_count=manifest['candidate_count'],
                         selected_ids=manifest['selected_ids'],
                         protocol_structure=('structured_present' if all(
                             'protocol' in c
                             for c in document['candidates'] if c['id'] in document['selected_ids'])
                             else 'legacy_unverified'))
    except (ValueError, TypeError, UnicodeError) as exc:
        audit['errors'].append(str(exc))
    return audit


def report_errors(primary_raw, report, *, synthesis_version=None):
    return validate_report(primary_raw, report, synthesis_version=synthesis_version)['errors']
