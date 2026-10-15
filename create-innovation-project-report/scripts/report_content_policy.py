"""Read-only content checks for a project-focused report; no Office dependency."""
from __future__ import annotations

import posixpath
import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

W = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
R = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
PKG = 'http://schemas.openxmlformats.org/package/2006/relationships'
NS = {'w': W}
CONTENT_PROFILES = {'project_only', 'progress'}

# Check statements about unfinished project work, not ordinary runtime states.
# These checks identify a defect and never delete or rewrite document text.
PENDING_PATTERNS = (
    r'待(?:完成|实现|验证|测(?:试)?|开展|标定|联调|复测|确认|完善|补充|归档)',
    r'(?:尚未|仍未|暂未|未能|未)(?:完成|实现|验证|测试|覆盖|开展|形成|提供|归档|标定|建立)',
    r'(?:仍需|尚需|尚待).{0,24}(?:完成|实现|验证|测试|确认|完善|复测|标定|联调|烧录|归档|评估)',
    r'(?:需|需要)(?:另行|进一步|继续).{0,16}(?:确认|验证|测试|完善|实现|标定|联调|归档)',
    r'(?:后续|未来)(?:工作|计划|安排|优化|验证|测试|阶段)',
    r'(?:下一阶段|下一步|下一版)(?:工作|计划|目标|条件|安排|优化|验证)',
    r'(?:后续|下一阶段|下一步|下一版).{0,24}(?:应|需|将|先|再|优先|待).{0,16}(?:完善|验证|测试|复测|标定|联调|归档|封装|实现|开展)',
    r'当前不足|未覆盖目标|本期范围外|尚不能.{0,20}(?:得出|证明|认定|宣称)',
    r'\b(?:not yet|still not)\s+(?:implemented|tested|verified|validated|completed|covered)\b',
    r'\b(?:pending|awaiting)\s+(?:implementation|testing|validation|verification|completion)\b',
    r'\b(?:future work|next steps|remaining tasks|to[- ]do list|unimplemented goals)\b',
)
RUNTIME_PATTERNS = (
    r'(?:若|当|如果|运行中|上电后).{0,20}(?:初始化|接收).{0,4}(?:尚未|未)完成(?:时|则)',
    r'(?:帧|报文)(?:接收|校验)?(?:尚未|未)(?:完成|验证)',
    r'(?:未完成|未验证)的?(?:帧|报文)',
)
WRITING_PROCESS_PATTERNS = (
    r'(?:根据|参照|按照|对照).{0,16}(?:提供的|所提供的).{0,10}(?:参考报告|参考样例|文档模板)',
    r'(?:本次|本报告).{0,12}(?:写作|编写|撰写|排版)(?:过程|工作|中)',
    r'资料扫描过程|报告编写口径|内部整理方法|AI生成说明',
)
BIBLIOGRAPHY_PATTERNS = (
    r'参考(?:报告|样例)|(?:写作|撰写|编写|排版)(?:资料|样例|模板|参考文档)',
    r'腾讯会议.{0,12}(?:录像|录屏|逐字稿)|会议(?:录像|录屏|逐字稿)|逐字稿|meeting\.tencent\.com/',
    r'项目资料|资料包|聊天附件|附件文件|工程导出|实物照片',
)
DEPENDENCY_PATTERNS = (
    r'(?:详见|参见|请查阅|请打开).{0,8}(?:外部|另附|源文件|录像|逐字稿)',
    r'(?:具体|完整)(?:参数|步骤|结果|说明).{0,12}(?:见|查看|查阅|参阅).{0,8}(?:外部|另附|原始资料|源文件)',
    r'(?:需要|必须|需)(?:打开|读取|查阅).{0,12}(?:附件|外部|源文件).{0,12}(?:理解|获得|获取)',
    r'\b(?:see|refer to|open) the external (?:file|attachment|recording|document)\b',
)


def normalized_text(text: str) -> str:
    text = re.sub(r'[\u200b-\u200d\ufeff]', '', text)
    return re.sub(r'(?<=[\u4e00-\u9fff])\s+(?=[\u4e00-\u9fff])', '', text)


def reference_key(text: str) -> str:
    text = re.sub(r'(?i)\.(?:docx?|pdf|txt|md)\b', '', text)
    text = re.sub(r'(?i)[_\s-]*v\d+(?:\.\d+)+', '', text)
    return re.sub(r'[\W_]+', '', text.casefold())


def content_policy_status(docx: Path, profile: str = 'project_only', forbidden_reference_titles=None) -> dict:
    if profile not in CONTENT_PROFILES:
        raise ValueError(f'Unknown content profile: {profile}')
    forbidden_reference_titles = forbidden_reference_titles or []
    if not isinstance(forbidden_reference_titles, list) or any(
        not isinstance(title, str) or not reference_key(title) for title in forbidden_reference_titles
    ):
        raise ValueError('forbidden_reference_titles must be a list of nonempty document titles')
    findings = []
    reference_entries = []
    paragraphs_checked = 0
    ignored_revision_paragraphs = 0
    with zipfile.ZipFile(docx) as archive:
        members = set(archive.namelist())
        for part in sorted(members):
            if not part.endswith('.xml') or not (
                part == 'word/document.xml' or part.startswith(('word/header', 'word/footer'))
                or part in ('word/footnotes.xml', 'word/endnotes.xml', 'word/comments.xml', 'docProps/core.xml', 'docProps/custom.xml')
            ):
                continue
            root = ET.fromstring(archive.read(part))
            revision_paragraphs = set()
            for table in root.findall('.//w:tbl', NS):
                row = table.find('w:tr', NS)
                header = ''.join(row.itertext()).lower() if row is not None else ''
                if (all(term in header for term in ('版本', '日期', '修订'))
                        or all(term in header for term in ('version', 'date', 'change'))):
                    revision_paragraphs.update(table.findall('.//w:p', NS))
            rel_name = posixpath.join(posixpath.dirname(part), '_rels', posixpath.basename(part) + '.rels')
            links = {}
            if rel_name in members:
                rels = ET.fromstring(archive.read(rel_name))
                links = {node.get('Id'): node.get('Target', '') for node in rels
                         if node.tag == f'{{{PKG}}}Relationship' and node.get('Type', '').endswith('/hyperlink')}
            in_bibliography = False

            def examine(value: str, location: str, bibliography: bool = False):
                nonlocal paragraphs_checked
                if not value.strip():
                    return
                paragraphs_checked += 1
                text = normalized_text(value)
                groups = [('project_focus', WRITING_PROCESS_PATTERNS), ('external_dependency', DEPENDENCY_PATTERNS)]
                if profile == 'project_only':
                    groups.append(('pending_project_work', PENDING_PATTERNS))
                runtime_spans = [(m.start(), m.end()) for pattern in RUNTIME_PATTERNS for m in re.finditer(pattern, text)]
                for code, patterns in groups:
                    matches = []
                    for pattern in patterns:
                        for match in re.finditer(pattern, text, re.I):
                            if code == 'pending_project_work' and any(a <= match.start() and match.end() <= b for a, b in runtime_spans):
                                continue
                            matches.append(match.group(0))
                    if matches:
                        findings.append({'part': part, 'location': location, 'kind': code,
                                         'matches': sorted(set(matches)), 'text': value[:320]})
                if bibliography:
                    reference_entries.append({'part': part, 'location': location, 'text': value[:500]})
                    matches = [m.group(0) for pattern in BIBLIOGRAPHY_PATTERNS
                               for m in re.finditer(pattern, text, re.I)]
                    keys = [title for title in forbidden_reference_titles if reference_key(title) in reference_key(text)]
                    if matches or keys:
                        findings.append({'part': part, 'location': location, 'kind': 'writing_material_reference',
                                         'matches': sorted(set(matches)), 'forbidden_titles': keys, 'text': value[:500]})

            for index, paragraph in enumerate(root.findall('.//w:p', NS)):
                if paragraph in revision_paragraphs:
                    ignored_revision_paragraphs += 1
                    continue
                value = ''.join(node.text or '' for node in paragraph.findall('.//w:t', NS)).strip()
                style = paragraph.find('w:pPr/w:pStyle', NS)
                style_id = style.get(f'{{{W}}}val', '') if style is not None else ''
                is_toc = style_id.lower().startswith('toc') or style_id.startswith('目录')
                if not is_toc and re.fullmatch(r'(?:参考文献|参考资料|references|bibliography)', normalized_text(value), re.I):
                    in_bibliography = True
                elif not is_toc and (re.match(r'(?:附录|appendix)\b|^附录', value, re.I)
                                     or (re.match(r'heading\s*1|标题\s*1', style_id, re.I) and in_bibliography)):
                    in_bibliography = False
                is_reference = in_bibliography and not re.fullmatch(r'(?:参考文献|参考资料|references|bibliography)', normalized_text(value), re.I)
                for link in paragraph.findall('.//w:hyperlink', NS):
                    target = links.get(link.get(f'{{{R}}}id', ''), '')
                    if target and is_reference:
                        value += ' ' + target
                examine(value, f'paragraph[{index}]', is_reference)
                for node_index, node in enumerate(paragraph.iter()):
                    description = node.get('descr')
                    if description:
                        examine(description, f'paragraph[{index}]/alt[{node_index}]')
                instructions = ''.join(node.text or '' for node in paragraph.findall('.//w:instrText', NS))
                instructions += ' '.join(node.get(f'{{{W}}}instr', '') for node in paragraph.findall('.//w:fldSimple', NS))
                if re.search(r'\b(?:INCLUDETEXT|INCLUDEPICTURE|LINK|DDEAUTO|DATABASE)\b', instructions, re.I):
                    findings.append({'part': part, 'location': f'paragraph[{index}]/field',
                                     'kind': 'external_dependency', 'text': instructions[:320]})
            if part.startswith('docProps/'):
                for index, child in enumerate(root):
                    examine(''.join(child.itertext()), f'property[{index}]')
    return {
        'profile': profile, 'passed': not findings, 'findings': findings,
        'finding_count': len(findings), 'paragraphs_checked': paragraphs_checked,
        'ignored_revision_paragraphs': ignored_revision_paragraphs,
        'reference_entries': reference_entries, 'forbidden_reference_titles': forbidden_reference_titles,
        'scope': 'Blocks explicit unfinished-work statements, writing-process references and external dependencies. Technical correctness, source support and complete explanations require manual review.',
        'manual_reviews_required': ['project implementation, architecture, core functions, design and achievements',
                                    'technical relevance of every bibliography entry',
                                    'independent understanding of parameters, methods, diagrams and conclusions',
                                    'no fabricated measurements or completion claims'],
    }
