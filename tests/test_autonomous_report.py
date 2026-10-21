"""Report regressions from the autonomous run's stale v5/v10 manuscript."""
import copy
import hashlib
import json
import unittest

from sage.autonomous.report import render_report, report_errors, validate_report


def primary():
    return {
        'candidates': [
            {'id': 'F01', 'title': '串行结构与可监控性', 'problem': '核心问题',
             'hypothesis': 'FS_lb is the primary outcome; Grad-Nec is supportive.',
             'mechanism': '可失败的机制预测', 'assumptions': '条件边界',
             'closest_prior_art': [{'paper_id': 'arxiv:2601.12345', 'overlap': '重合', 'difference': '差异'}],
             'source_ids': ['arxiv:2601.12345', 'doi:10.1000/example'],
             'falsification': {'test': '先冻结再测试', 'controls': '负对照',
                              'metric': 'Primary: FS_lb; supportive: Grad-Nec.',
                              'reject_if': '区间含零时不支持假说'},
             'feasibility': '预算400GPU小时，未执行', 'risks': ['来源部分阅读'],
             'status': 'provisional'},
            {'id': 'F02', 'title': '淘汰的想法', 'mechanism': '完整保留机制',
             'disposition': 'rejected', 'rejection_reason': '近邻工作已覆盖',
             'source_ids': ['arxiv:2601.12345']},
        ],
        'selected_ids': ['F01'], 'selection_rationale': '只测试一个清晰机制',
        'open_questions': ['文献缺失', '功效分析尚未完成'],
    }


def raw(document=None):
    return (json.dumps(primary() if document is None else document, ensure_ascii=False, indent=2) + '\n').encode()


class ReportContractTests(unittest.TestCase):
    def test_full_report_preserves_all_ideas_science_budget_and_chinese_discussion(self):
        data = raw()
        narrative = '## 中文文献全景\n\n' + ('长篇中文讨论、反证、来源、未知均需保留。\n' * 150)
        report = render_report(data, narrative, synthesis_version=10)
        result = validate_report(data, report.encode(), synthesis_version=10)
        self.assertEqual(result['errors'], [])
        self.assertEqual(result['status'], 'verified_alignment')
        self.assertEqual(result['protocol_structure'], 'legacy_unverified')
        self.assertIn(narrative, report)
        for text in ('淘汰的想法', '完整保留机制', '近邻工作已覆盖', '预算400GPU小时',
                     '功效分析尚未完成', 'https://arxiv.org/abs/2601.12345',
                     'https://doi.org/10.1000/example', '负对照', '区间含零时不支持假说'):
            self.assertIn(text, report)
        self.assertEqual(result['candidate_count'], 2)
        self.assertEqual(result['selected_ids'], ['F01'])

    def test_v5_report_cannot_bind_v10_even_if_its_own_bytes_are_authentic(self):
        old = raw()
        doc = primary()
        doc['candidates'][0]['hypothesis'] = 'Substantive v10 hypothesis'
        current = raw(doc)
        report = render_report(old, '中文完整旧稿', synthesis_version=5)
        errors = report_errors(current, report, synthesis_version=10)
        self.assertTrue(any('primary_sha256' in error for error in errors))
        self.assertTrue(any('synthesis_version' in error for error in errors))
        self.assertTrue(any('canonical scientific sections' in error for error in errors))

    def test_changing_only_the_stale_report_header_does_not_pass(self):
        old = raw()
        doc = primary()
        doc['candidates'][0]['mechanism'] = 'Current mechanism replacing the old mechanism'
        current = raw(doc)
        report = render_report(old).replace(hashlib.sha256(old).hexdigest(), hashlib.sha256(current).hexdigest())
        self.assertTrue(any('canonical scientific sections' in error for error in report_errors(current, report)))

    def test_co_primary_metric_cannot_replace_single_primary_in_rendered_report(self):
        data = raw()
        report = render_report(data)
        report = report.replace('Primary: FS_lb; supportive: Grad-Nec.',
                                'FS_lb and Grad-Nec as co-primary outcomes.')
        errors = report_errors(data, report)
        self.assertTrue(any('canonical scientific sections' in error for error in errors))

    def test_selection_and_candidate_count_are_checked_not_just_a_hash_header(self):
        data = raw()
        report = render_report(data).replace('当前入选ID：`F01`', '当前入选ID：`F02`').replace('候选总数：2', '候选总数：12')
        self.assertTrue(report_errors(data, report))

    def test_same_primary_different_registered_synthesis_version_is_rejected(self):
        data = raw()
        self.assertTrue(report_errors(data, render_report(data, synthesis_version=5), synthesis_version=10))

    def test_primary_whitespace_changes_require_regeneration(self):
        data = raw()
        self.assertTrue(report_errors(data + b'\n', render_report(data)))

    def test_old_unstructured_reports_are_explicitly_unverified(self):
        result = validate_report(raw(), '# 中文科研报告\n\n旧版v5\n')
        self.assertEqual(result['status'], 'legacy_unverified')
        self.assertTrue(result['errors'])

    def test_current_sha_claim_in_narrative_cannot_point_to_a_previous_primary(self):
        with self.assertRaisesRegex(ValueError, 'stale'):
            render_report(raw(), '本报告 primary_sha256 = ' + 'a' * 64)

    def test_other_legitimate_hashes_do_not_trigger_primary_mismatch(self):
        data = raw()
        report = render_report(data, '历史来源chunk SHA256=' + 'a' * 64)
        self.assertEqual(report_errors(data, report), [])

    def test_narrative_current_v5_cannot_override_manager_v10(self):
        for narrative in ('当前v5', '当前综合版本：v5。', '本报告版本为v5',
                          'synthesis_version = 5', '`synthesis_version` = 5',
                          'current_synthesis_version: "v5"'):
            with self.subTest(narrative=narrative), self.assertRaisesRegex(ValueError, 'synthesis version'):
                render_report(raw(), narrative, synthesis_version=10)

    def test_matching_current_version_and_historical_discussion_remain_allowed(self):
        data = raw()
        narrative = '当前综合版本：v10。\n此前v5包含缺陷，v7曾修订；本文解释其历史，不重新定义协议。'
        self.assertEqual(report_errors(data, render_report(data, narrative, synthesis_version=10), synthesis_version=10), [])

    def test_undeclared_manager_version_cannot_be_fabricated_in_narrative(self):
        with self.assertRaisesRegex(ValueError, 'synthesis version'):
            render_report(raw(), '本报告版本：v5')

    def test_narrative_structural_selection_and_count_claims_must_match(self):
        for narrative in ('candidate_count=12', 'selected_ids=["F02"]', 'selected_ids=[F01]'):
            with self.subTest(narrative=narrative), self.assertRaises(ValueError):
                render_report(raw(), narrative)
        data = raw()
        self.assertFalse(report_errors(data, render_report(data, 'candidate_count=2\nselected_ids=["F01"]')))

    def test_narrative_reserved_protocol_assignments_cannot_redefine_primary_roles(self):
        for narrative in ('主指标：Grad-Nec', '**主要终点**：Grad-Nec', '- 次要终点：FS_lb',
                          '`主要指标`：Grad-Nec', 'F01.primary_endpoint_ids=["E2"]',
                          '`primary_endpoint_ids`=["E2"]', '"primary_endpoint_ids": ["E2"]',
                          'protocol.endpoints.E2.role="primary"',
                          'decision_rule.support_when="different condition"'):
            with self.subTest(narrative=narrative), self.assertRaisesRegex(ValueError, 'reserved endpoint'):
                render_report(raw(), narrative)

    def test_protocol_explanation_is_not_mistaken_for_a_field_assignment(self):
        data = raw()
        narrative = '主指标的可靠性仍需校准。多个终点会增加误判风险。\n文献介绍了co-primary outcomes，但我们不借此推断科学结论。'
        self.assertFalse(report_errors(data, render_report(data, narrative)))

    def test_reserved_marker_injection_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'reserved'):
            render_report(raw(), '<!-- SAGE_REPORT_CANONICAL_END -->')

    def test_free_form_claims_appended_outside_bound_narrative_are_rejected(self):
        data = raw()
        report = render_report(data) + '\n主指标改为Grad-Nec。\n'
        self.assertTrue(report_errors(data, report))

    def test_complete_source_schema_is_not_rewritten_or_self_hashed(self):
        document = primary()
        before = copy.deepcopy(document)
        data = raw(document)
        render_report(data, synthesis_version=10)
        self.assertEqual(document, before)
        self.assertNotIn('primary_sha256', document)

    def test_malformed_or_duplicate_primary_candidates_are_rejected(self):
        document = primary()
        document['candidates'][1]['id'] = 'F01'
        with self.assertRaisesRegex(ValueError, 'unique'):
            render_report(raw(document))
        document = primary()
        document['selected_ids'] = ['F99']
        with self.assertRaisesRegex(ValueError, 'selected_ids'):
            render_report(raw(document))


if __name__ == '__main__':
    unittest.main()
