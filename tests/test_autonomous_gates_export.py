"""Regressions for actual review-stage counting and scientific artifact export."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

from sage.autonomous.export import export_submissions
from sage.autonomous.gates import advisory_errors, frozen_problem_anchors
from sage.autonomous.report import render_report
from sage.autonomous.skills import REQUIRED_SKILLS, assemble_native_task


A, B = 'a'*64, 'b'*64


def review(ident, sha=A, slot=0, time='2026-10-18T12:00:01+00:00', grading=False):
    return dict(id=ident, input_sha256=sha, research_slot=slot, time=time, grading=grading)


class GateExportTests(unittest.TestCase):
    def team(self):
        return SimpleNamespace(state={'syntheses': [
            {'primary_sha256': A, 'receipt': {'time': '2026-10-18T12:00:00+00:00'}},
            {'primary_sha256': B, 'receipt': {'time': '2026-10-18T12:01:00+00:00'}}]})

    def test_initial_researcher_reviews_cannot_discharge_synthesis_gate(self):
        reviews=[review('early1', time='2026-10-18T11:59:59+00:00'),review('other',slot=1)]
        self.assertTrue(advisory_errors(A,reviews,self.team()))

    def test_reviewed_lineage_still_requires_current_version_critique(self):
        reviews=[review('one'), review('two')]
        self.assertEqual(len(advisory_errors(B,reviews,self.team())),1)
        reviews.append(review('three',sha=B,time='2026-10-18T12:01:01+00:00'))
        self.assertEqual(advisory_errors(B,reviews,self.team()),[])

    def test_formal_grades_and_duplicate_receipts_do_not_count_as_two_reviews(self):
        one=review('one',sha=B)
        self.assertTrue(advisory_errors(B,[one,one,review('formal',sha=B,grading=True)],self.team()))

    def test_unregistered_and_wrong_coordinator_reviews_do_not_count(self):
        reviews=[review('one',sha='c'*64),review('two',sha=B,slot=2)]
        self.assertTrue(advisory_errors(B,reviews,self.team()))

    def test_later_version_cannot_retroactively_register_an_earlier_critique(self):
        reviews=[review('a1'),review('a2'),
                 review('premature-b',sha=B,time='2026-10-18T12:00:30+00:00')]
        self.assertTrue(advisory_errors(B,reviews,self.team()))

    def test_same_json_different_reports_preserve_both_historical_submissions(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            raw=b'{"candidates": [{"id":"C1"}], "selected_ids":["C1"]}\n'; sha=hashlib.sha256(raw).hexdigest()
            (root/f'conjectures-{sha}.json').write_bytes(raw)
            grades=[]
            for index,score in enumerate((.8,.6)):
                report=render_report(raw, '中文完整讨论版本 '+str(index)).encode()
                report_sha=hashlib.sha256(report).hexdigest()
                name=f'report-{sha}-{report_sha}.md'
                (root/name).write_bytes(report)
                grades.append(dict(primary_sha256=sha,score=score,contract_errors=[],
                                   report_file=name,report_sha256=report_sha))
            export_submissions(root,root,grades)
            self.assertEqual((root/'CONJECTURES.md').read_bytes(), render_report(raw,'中文完整讨论版本 1').encode())
            self.assertEqual((root/'best-score-CONJECTURES.md').read_bytes(), render_report(raw,'中文完整讨论版本 0').encode())

    def test_single_researcher_also_requires_two_and_current_artifact(self):
        self.assertTrue(advisory_errors(B,[review('old1'),review('old2')]))
        self.assertEqual(advisory_errors(B,[review('old'),review('new',sha=B)]),[])

    def test_problem_fidelity_uses_manager_initial_problem_not_mutable_author_anchor(self):
        team=self.team()
        team.grade_errors=lambda doc,sha: []
        team.state['proposals']={'1':{'document':{'candidates':[{'id':'C1','problem':'Original bottleneck'}]}}}
        primary={'problem_anchor':'Author changed the goal', 'candidates':[
            {'id':'S1-C1','problem':'A different easier problem','origin':{'slot':1,'candidate_id':'C1'}}]}
        anchors=frozen_problem_anchors(primary,B,team,0)
        self.assertEqual(anchors['candidates']['S1-C1']['problem'],'Original bottleneck')

    def test_unregistered_author_origin_cannot_reveal_peer_problem_before_barrier(self):
        team=self.team()
        team.grade_errors=lambda doc,sha: ['not registered']
        team.state['proposals']={'1':{'document':{'candidates':[{'id':'C1','problem':'Hidden peer problem'}]}}}
        primary={'candidates':[{'id':'C1','origin':{'slot':1,'candidate_id':'C1'}}]}
        self.assertEqual(frozen_problem_anchors(primary,A,team,0)['status'],'not_frozen')

    def test_early_unfrozen_problem_does_not_claim_an_immutable_anchor(self):
        self.assertEqual(frozen_problem_anchors({'candidates':[]},A)['status'],'not_frozen')

    def test_latest_valid_lower_score_is_primary_and_exact_bytes_are_retained(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); private=root/'private'; private.mkdir()
            grades=[]
            raw_files=[]
            for index, score in enumerate((.8,.6)):
                raw=json.dumps({'candidates':[{'id':'C1','hypothesis':f'Protocol {index}'}],
                                'selected_ids':['C1']},indent=2).encode()+b'\n'
                sha=hashlib.sha256(raw).hexdigest(); raw_files.append(raw)
                (private/f'conjectures-{sha}.json').write_bytes(raw)
                (private/f'report-{sha}.md').write_bytes(render_report(raw,'中文完整报告 '+str(index)).encode())
                grades.append(dict(primary_sha256=sha,score=score,contract_errors=[]))
            result=export_submissions(private,root,grades+[{'score':1,'contract_errors':['invalid']}])
            self.assertEqual(result['selected_grade'],grades[1])
            self.assertEqual(result['best_score_grade'],grades[0])
            self.assertEqual((root/'conjectures.json').read_bytes(),raw_files[1])
            self.assertEqual((root/'best-score-conjectures.json').read_bytes(),raw_files[0])
            self.assertEqual(hashlib.sha256((root/'latest-conjectures.json').read_bytes()).hexdigest(),grades[1]['primary_sha256'])
            self.assertEqual(result['files']['primary']['report_alignment']['status'],'verified_alignment')

    def test_stale_report_with_real_recorded_bytes_is_not_exported(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            old=json.dumps({'candidates':[{'id':'F01','hypothesis':'Old science'}],
                            'selected_ids':['F01']}).encode()
            raw=json.dumps({'candidates':[{'id':'F01','hypothesis':'Current science'}],
                            'selected_ids':['F01']}).encode()
            sha=hashlib.sha256(raw).hexdigest()
            report=render_report(old,'旧版v5中文长报告',synthesis_version=5).encode()
            (root/f'conjectures-{sha}.json').write_bytes(raw)
            (root/f'report-{sha}.md').write_bytes(report)
            grade=dict(primary_sha256=sha,score=.7,contract_errors=[],synthesis_version=10,
                       report_sha256=hashlib.sha256(report).hexdigest())
            with self.assertRaisesRegex(ValueError,'internally bound'):
                export_submissions(root,root,[grade])
            self.assertFalse((root/'CONJECTURES.md').exists())
            self.assertFalse((root/'conjectures.json').exists())

    def test_corrupted_graded_primary_is_not_exported(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            (root/f'conjectures-{A}.json').write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError,'SHA-256'):
                export_submissions(root,root,[dict(primary_sha256=A,score=.5,contract_errors=[])])
            self.assertFalse((root/'conjectures.json').exists())

    def test_no_valid_grade_does_not_create_a_successful_export(self):
        with tempfile.TemporaryDirectory() as folder:
            result=export_submissions(folder,folder,[{'score':1,'contract_errors':['incomplete']}])
            self.assertIsNone(result['selected_grade'])

    def test_refine_pipeline_cannot_launch_without_actual_calibration_reference(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            for name in REQUIRED_SKILLS:
                file=root/'skills'/name/'SKILL.md'; file.parent.mkdir(parents=True)
                file.write_text('Synthetic skill '+name)
            with self.assertRaisesRegex(Exception,'rubric reference missing'):
                assemble_native_task(root,'Synthetic workflow')


if __name__=='__main__': unittest.main()
