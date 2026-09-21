# Create Innovation Project Report

将真实项目资料整理为综合实践报告的可移植 Skill。支持软件、硬件、实验研究、数据分析、产品设计及混合项目，适用于项目展示、阶段汇报和结项材料。

当前版本：**1.1.0**（以 SKILL.md 的 `metadata.version` 标识）。本版补充成稿独立性、参考报告深度转化、实施过程细节、封面与署名、视频取帧裁切和修订保护规则，新增可选的 DOCX 图片依赖与资料叙述检查。规则按用户模板和项目资料应用，不绑定某个项目、人员或会议软件。

默认生成中文 DOCX，并保留客观表述、通俗术语、修订记录、“项目名称_综合实践报告_日期或版本号”的命名和第一章起算页码规则。用户可配置其他语言、篇幅、模板及 Markdown/PDF 交付。核心辅助脚本使用 Python 3.9+ 标准库；报告内容生成、格式导出和页面检查由宿主 Agent 的实际工具完成。

## 使用方式

实际安装内容为仓库内层 `create-innovation-project-report/` 目录。保留整个目录，包括 vendor 中的依赖与许可证。将其复制到当前 Agent 的技能目录，或直接让 Agent 读取目录中的 SKILL.md。

支持接入 Codex、Claude Code、Gemini CLI、Cursor、GitHub Copilot，以及具备文件读取能力的其他 Agent。各平台的入口和能力检查见 [Agent 接入说明](create-innovation-project-report/references/agent-adapters.md)。该说明区分已核对的接口与需要在宿主上实际运行的能力。

通用请求示例：

```text
读取 create-innovation-project-report/SKILL.md，按当前项目资料生成综合实践报告。
目标读者为项目评审，使用中文 DOCX，保留现有报告结构。
```

也可要求只审查、只形成提纲、修订特定章节或补充配图。任务不会自动扩展为完整重写。

## 环境检查

```bash
python3 create-innovation-project-report/scripts/bootstrap_runtime.py --check-only --json
python3 create-innovation-project-report/scripts/check_skill_compatibility.py --json
```

Windows 可使用 `py -3` 或实际 Python 路径。默认不联网、不安装、不扫描其他 Agent 目录。仅在显式传入 `--install` 时安装；离线时使用 `--offline`。无需预装 python-docx、Pillow 或 PyYAML 来运行本仓库的辅助脚本。

默认读取内置 humanizer-zh；检测到已有有效副本时可复用。非中文任务采用目标语言的编辑规则。升级前使用本地验证，详情见 [运行环境与兼容性](create-innovation-project-report/references/compatibility.md)。

## 灵活配置

```bash
python3 create-innovation-project-report/scripts/plan_report.py --template --output report-config.json
python3 create-innovation-project-report/scripts/plan_report.py --config report-config.json --output report-plan.json
```

最小配置：

```json
{
  "schema_version": 1,
  "project": {"name": "项目名称", "root": "."}
}
```

配置支持项目类型和阶段、任务模式、读者、语言、篇幅、格式、纸张、字体、目录、修订记录、命名、模块开关、离线和渲染要求。字段与路径规则见 [配置与模块接口](create-innovation-project-report/references/configuration.md)。计划文件包含模块输入输出与能力缺口；它本身不是生成完毕的报告。

模式包括 `create`、`revise`、`audit`、`outline` 和 `visuals`。渲染可设置为 required、preferred 或 skip。缺少必需后端时保留用户目标并明确列出未完成项，不将其他格式冒称为已完成结果。

## 可独立使用的工具

| 脚本 | 用途 |
|---|---|
| plan_report.py | 配置校验、任务分流和模块计划 |
| bootstrap_runtime.py | 默认只读的运行环境检查、显式依赖安装 |
| check_skill_compatibility.py | 技能结构、引用、语法和命令接口检查 |
| inventory_project.py | 资料盘点、去重、图片元数据和目录排除 |
| analyze_reference_docx.py | 参考报告的标题、篇幅、表格和图片分析 |
| inspect_experiment_data.py | CSV/TSV 质量、数值格式与截断检查 |
| prepare_exploded_view.py | CAD、图像生成和示意图的爆炸图规范 |
| appendix_images.py | 真实图片、题注、替代文本和附录互引 |
| audit_docx.py | 项目名称、目录域、图表引用、缩进、表格比较及可选的独立性检查 |

各工具通过 `--help` 查看参数。图表资料不足时使用结构图、流程图或测试计划，保留实际结果与预期结果的区别。图片附录默认拒绝覆盖任何已有输出文件。

对需要脱离源文件阅读的 DOCX，可运行：

```bash
python3 create-innovation-project-report/scripts/audit_docx.py report.docx --check-self-contained --json
```

该选项只读检查 Word 部件中的图片引用、包内媒体是否存在及是否依赖外部位置，同时提示需人工复核的资料来源叙述。图片关系损坏、缺失或外链导致非零退出码；措辞候选不导致失败，也不自动删除“记录”等词语。默认不开启此项。检查不联网，不验证图中文字、外部数据域或技术语义，不能据此宣称报告已经完整自洽。

## 扩展结构

`SKILL.md` 保留核心规则及任务路由；`references/` 按场景加载；`scripts/report_config.py` 定义版本化配置；`scripts/plan_report.py` 定义模块契约与组合；`tests/` 验证行为。新增 Agent 通过接入说明和能力声明复用同一核心流程，新增模块通过输入输出契约扩展。组织专用参数放在 `extensions`，不会被核心代码当作命令执行。

## 验证

```bash
python3 -m unittest discover -s create-innovation-project-report/tests -v
python3 create-innovation-project-report/scripts/check_skill_compatibility.py --json
```

测试涵盖原有 DOCX 附录与参考分析，以及任务配置、模式分流、Agent/项目类型组合、离线和只读检测、同名副本、路径带空格与中文、英文图表引用、缺损目录域、输出保护和地区数值格式；独立性检查另覆盖内嵌与外链图片、丢失关系与媒体、正文以外部件、路径解析、措辞候选和合法术语保留。

GitHub Actions 提供 Windows、macOS、Linux 与 Python 3.9/3.13 的运行矩阵。配置文件存在不等于远程 CI 已运行；以实际 Actions 结果为准。产品级 Agent 调用、Office 字体和真实分页仍需在相应宿主验证。

## 第三方资源

内置 [humanizer-zh](https://github.com/tianpeng-dev/Humanizer-zh) 保留原 [MIT 许可证](create-innovation-project-report/vendor/humanizer-zh/LICENSE)。其资源仅用于中文正文编辑，项目事实、参数和已确认格式在各语言流程中保持一致。
