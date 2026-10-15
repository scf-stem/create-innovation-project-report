from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
from report_content_policy import content_policy_status
from report_config import load_config
from plan_report import build_plan
from test_self_containment import fixture, paragraph, W, R, NAMESPACES


def table(header: str, text: str) -> str:
    return f'<w:tbl><w:tr><w:tc>{paragraph(header)}</w:tc></w:tr><w:tr><w:tc>{paragraph(text)}</w:tc></w:tr></w:tbl>'


class ContentPolicyTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.path = self.directory / '项目 报告.docx'

    def cli(self, *args):
        return subprocess.run([sys.executable, str(ROOT / 'scripts/audit_docx.py'), str(self.path), '--json', *args],
                              capture_output=True, encoding='utf-8', check=False)

    def test_project_report_default_rejects_pending_work_without_mutation(self):
        fixture(self.path, paragraph('项目尚未完成整机验证，后续工作是标定传感器。'))
        before = hashlib.sha256(self.path.read_bytes()).hexdigest()
        result = self.cli('--project-report')
        self.assertEqual(result.returncode, 1, result.stderr)
        policy = json.loads(result.stdout)['content_policy']
        self.assertFalse(policy['passed'])
        self.assertEqual({item['kind'] for item in policy['findings']}, {'pending_project_work'})
        self.assertEqual(before, hashlib.sha256(self.path.read_bytes()).hexdigest())

    def test_independent_flag_also_enforces_content_policy(self):
        fixture(self.path, paragraph('固件待验证。'))
        self.assertEqual(self.cli().returncode, 0)
        self.assertEqual(self.cli('--check-content-policy').returncode, 1)

    def test_split_runs_table_and_caption_are_checked(self):
        split = '<w:p><w:r><w:t>待</w:t></w:r><w:r><w:t>测</w:t></w:r></w:p>'
        fixture(self.path, table('功能 状态', '尚待标定') + split + paragraph('表 3-1 后续验证安排'))
        policy = content_policy_status(self.path)
        self.assertEqual(len(policy['findings']), 3)
        self.assertTrue(all(item['kind'] == 'pending_project_work' for item in policy['findings']))

    def test_runtime_faults_initialization_and_later_bytes_are_not_project_incompleteness(self):
        values = ['通信未连接时显示状态；定位未定位时保留位置更新时间。',
                  '若初始化尚未完成时，程序继续等待。', '接收未完成的帧时，丢弃报文片段。',
                  '接收后续字节并完成校验，传感器随后进入待机状态。']
        fixture(self.path, ''.join(paragraph(value) for value in values))
        self.assertTrue(content_policy_status(self.path)['passed'])

    def test_references_allow_technical_manuals_but_reject_writing_materials(self):
        fixture(self.path, paragraph('参考文献') + paragraph('[1] DHT11 温湿度传感器说明书 A0-1208。')
                + paragraph('[2] 项目腾讯会议录像与逐字稿。')
                + paragraph('[3] 某项目_综合实践报告_v1.5.docx。'))
        policy = content_policy_status(self.path, forbidden_reference_titles=['某项目_综合实践报告_v1.4.docx'])
        self.assertEqual(len(policy['reference_entries']), 3)
        violations = [f for f in policy['findings'] if f['kind'] == 'writing_material_reference']
        self.assertEqual(len(violations), 2)
        self.assertIn('某项目_综合实践报告_v1.4.docx', violations[1]['forbidden_titles'])

    def test_hidden_reference_hyperlink_target_is_checked(self):
        link = '<w:p><w:hyperlink r:id="source"><w:r><w:t>[1] 开发会议</w:t></w:r></w:hyperlink></w:p>'
        rels = f'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="source" Type="{R}/hyperlink" Target="https://meeting.tencent.com/cw/example" TargetMode="External"/></Relationships>'
        fixture(self.path, paragraph('References') + link, rels)
        policy = content_policy_status(self.path)
        self.assertEqual(policy['findings'][0]['kind'], 'writing_material_reference')

    def test_reference_section_ends_before_embedded_photo_appendix(self):
        fixture(self.path, paragraph('参考文献') + paragraph('[1] STM32 Datasheet.')
                + paragraph('附录 A 项目照片') + paragraph('实物照片说明模块安装。'))
        policy = content_policy_status(self.path)
        self.assertTrue(policy['passed'])
        self.assertEqual(len(policy['reference_entries']), 1)

    def test_writing_process_narration_and_external_lookup_fail(self):
        fixture(self.path, paragraph('参照所提供的参考报告整理本次内容。')
                + paragraph('完整参数详见外部文件。'))
        policy = content_policy_status(self.path)
        self.assertEqual({f['kind'] for f in policy['findings']}, {'project_focus', 'external_dependency'})

    def test_field_dependency_fails_but_normal_citation_hyperlinks_are_allowed(self):
        include = '<w:p><w:r><w:instrText>INCLUDE</w:instrText></w:r><w:r><w:instrText>TEXT "external.docx"</w:instrText></w:r></w:p>'
        fixture(self.path, include)
        self.assertEqual(content_policy_status(self.path)['findings'][0]['kind'], 'external_dependency')
        simple = '<w:p><w:fldSimple w:instr="INCLUDETEXT external.docx"/></w:p>'
        fixture(self.path, simple)
        self.assertFalse(content_policy_status(self.path)['passed'])
        fixture(self.path, '<w:p><w:fldSimple w:instr="HYPERLINK https://example.invalid/manual"/></w:p>')
        self.assertTrue(content_policy_status(self.path)['passed'])

    def test_header_notes_metadata_and_image_alternative_text_are_checked(self):
        fixture(self.path, extra={
            'word/header1.xml': f'<w:hdr {NAMESPACES}>{paragraph("后续工作计划")}</w:hdr>',
            'word/footnotes.xml': f'<w:footnotes {NAMESPACES}>{paragraph("尚未完成验证")}</w:footnotes>',
            'docProps/core.xml': '<core><description>固件待测试</description></core>',
            'word/footer1.xml': f'<w:ftr {NAMESPACES}><w:p><w:r><w:drawing><x xmlns="urn:test" descr="图 1 待验证方案"/></w:drawing></w:r></w:p></w:ftr>',
        })
        policy = content_policy_status(self.path)
        self.assertEqual({f['part'] for f in policy['findings']}, {'word/header1.xml', 'word/footnotes.xml', 'docProps/core.xml', 'word/footer1.xml'})

    def test_historical_revision_description_is_preserved(self):
        fixture(self.path, table('版本 修订日期 修订内容', 'v1.0 删除后续计划表述。')
                + paragraph('项目采用三组独立串口。'))
        policy = content_policy_status(self.path)
        self.assertTrue(policy['passed'])
        self.assertGreater(policy['ignored_revision_paragraphs'], 0)

    def test_explicit_progress_profile_only_relaxes_pending_work(self):
        fixture(self.path, paragraph('项目尚未完成验证。'))
        self.assertEqual(self.cli('--project-report').returncode, 1)
        self.assertEqual(self.cli('--project-report', '--content-profile', 'progress').returncode, 0)
        fixture(self.path, paragraph('参考文献') + paragraph('[1] 参考样例报告。'))
        self.assertFalse(content_policy_status(self.path, 'progress')['passed'])

    def test_english_pending_claims_are_checked(self):
        fixture(self.path, paragraph('Firmware is not yet tested. Future work includes validation.'))
        self.assertFalse(content_policy_status(self.path)['passed'])

    def test_technical_conditions_and_examples_do_not_claim_measured_success(self):
        fixture(self.path, paragraph('设计采用 40 位帧，校验示例为 0x41 + 0x1A = 0x5B。')
                + paragraph('表中 18—30 ms 为手册时序参数。'))
        policy = content_policy_status(self.path)
        self.assertTrue(policy['passed'])
        self.assertIn('no fabricated measurements or completion claims', policy['manual_reviews_required'])

    def test_invalid_profiles_and_reference_lists_fail(self):
        fixture(self.path)
        with self.assertRaises(ValueError): content_policy_status(self.path, 'unknown')
        with self.assertRaises(ValueError): content_policy_status(self.path, forbidden_reference_titles='sample.docx')
        self.assertEqual(self.cli('--content-profile', 'unknown').returncode, 2)


class ContentConfigTest(unittest.TestCase):
    def test_stage_never_silently_switches_to_progress_and_options_reach_audit(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            cfg_path = root / 'task.json'
            for stage in ['concept', 'prototype', 'validated', 'deployed']:
                cfg_path.write_text(json.dumps({'project': {'name': '项目', 'root': str(root), 'stage': stage},
                                               'quality': {'forbidden_reference_titles': ['排版样例.docx']}}), encoding='utf-8')
                cfg = load_config(cfg_path)
                self.assertEqual(cfg['quality']['content_profile'], 'project_only')
                audit = next(s for s in build_plan(cfg)['modules'] if s['id'] == 'audit')
                self.assertEqual(audit['content_profile'], 'project_only')
                self.assertIn('--check-content-policy', audit['audit_options'])
                self.assertEqual(audit['audit_options'][-2:], ['--forbid-reference-title', '排版样例.docx'])

    def test_explicit_profile_is_respected_and_invalid_configuration_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); path = root / 'task.json'
            base = {'project': {'name': '项目', 'root': str(root)}}
            for quality in [{'content_profile': 'unknown'}, {'forbidden_reference_titles': 'x'}, {'forbidden_reference_titles': [1]}, {'forbidden_reference_titles': ['']}]:
                path.write_text(json.dumps({**base, 'quality': quality}), encoding='utf-8')
                with self.assertRaises(ValueError): load_config(path)
            path.write_text(json.dumps({**base, 'quality': {'content_profile': 'progress'}}), encoding='utf-8')
            self.assertEqual(load_config(path)['quality']['content_profile'], 'progress')


if __name__ == '__main__':
    unittest.main()
