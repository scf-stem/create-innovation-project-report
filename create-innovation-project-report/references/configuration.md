# 配置与模块接口

## 任务配置

配置用于重复任务、非默认格式或跨 Agent 交接。简单任务可由 Agent 根据用户要求直接采用默认值。配置是本技能的数据接口，不是 Agent 厂商配置；不会安装工具、运行扩展代码或自动生成整份报告。

```bash
python3 <skill-dir>/scripts/plan_report.py --template --output report-config.json
python3 <skill-dir>/scripts/plan_report.py --config report-config.json --output report-plan.json
```

输出文件须为新路径，父目录须存在。省略 `--output` 时 JSON 写入标准输出。返回码：0 表示计划可继续，1 表示存在明确阻塞，2 表示配置或文件读写错误。`planned`、`conditional`、`needs-capability-check` 均为待执行状态。

最小配置：

```json
{
  "schema_version": 1,
  "project": {"name": "项目名称", "root": "."}
}
```

已有报告只读审查：

```json
{
  "schema_version": 1,
  "project": {"name": "项目名称"},
  "task": {"mode": "audit", "previous": "existing.docx"},
  "runtime": {"agent": "generic", "capabilities": {"renderer": false}}
}
```

配置合并顺序为默认值、JSON 文件、明确提供的 CLI 参数。CLI 可覆盖 `--project-name`、`--project-root`、`--mode`、`--format`、`--agent`；其他字段通过 JSON 提供。未知字段和错误类型直接报错，避免拼写错误被静默忽略。

`project.root` 和 `task.previous` 相对配置文件目录解析；无配置时以当前目录解析。`output.directory` 相对项目根目录解析。项目目录必须存在。配置可放在不同工作目录运行，解析结果保持相同。传给 CLI 的相对项目路径也遵守这一规则。

## 字段

| 字段 | 值与作用 |
|---|---|
| `schema_version` | 固定为整数 1；不识别的版本报错 |
| `project.name` | 必填；项目正式名称；禁止路径分隔符和 Windows 保留文件名 |
| `project.root` | 项目目录，默认 `.` |
| `project.domain` | `general/software/hardware/research/data/product/mixed`，指导模块内容 |
| `project.stage` | `concept/prototype/validated/deployed`，限定结果表述 |
| `task.mode` | `create/revise/audit/outline/visuals` |
| `task.previous` | 修订、审查、配图模式必填已有文档；审查不生成替代报告 |
| `task.language` | 默认 `zh-CN`；使用目标语言，中文词库仅用于中文任务 |
| `task.audience` | 目标读者，默认 `technical`；可写业务方、评审或一般读者 |
| `task.depth` | `brief/standard/detailed`；指导篇幅与解释深度 |
| `output.format` | `docx/markdown/pdf`；提纲固定为 Markdown |
| `output.directory` | 默认 `output/doc`；仅规划路径，不创建目录或文件 |
| `output.report_label` | 默认“综合实践报告”；其他语言或机构名称按用户要求配置 |
| `output.date` | `YYYY-MM-DD`，默认本地当天日期；命名使用 YYYYMMDD |
| `output.version` | 如 `v1.0` 或 `v1.0.1`；有版本时优先用于文件名，日期仍保留给修订记录 |
| `document.paper` | `A4/Letter` |
| `document.font` | 字体名或 null；Agent 检查字体可用性、替代字体与字形 |
| `document.toc` | 默认 true；DOCX 为目录域，Markdown 为链接目录 |
| `document.revision_history` | 默认 true；按配置和原稿保留或追加记录 |
| `document.body_page_start` | 正整数，默认 1；分页文档正文起始值 |
| `modules.data/visuals/appendix/polish` | true、false、`auto`；auto 按真实资料与本轮改动选择 |
| `quality.render` | `required/preferred/skip`；默认 preferred，跳过与缺失均不得声称检查通过 |
| `quality.max_pages_without_visual` | 默认 3；分页正文配图密度目标，不用于凑页数 |
| `runtime.agent` | `generic/codex/claude-code/gemini-cli/cursor/copilot`，只用于接入识别 |
| `runtime.offline` | 默认 false；true 时所有步骤使用本地资料，禁止下载 |
| `runtime.capabilities` | `document_writer/renderer/image_generation` 为 true、false 或 auto |
| `extensions` | 组织自定义对象；保留并透传，不执行其中的命令或下载地址 |

能力设为 true 表示当前 Agent 已确认存在相应工具，仍需实际调用并检查结果。auto 表示尚待确认，不能由 Agent 名称推导。render=required 且 renderer=false 时计划返回阻塞；preferred 时继续可执行工作，并列明版式未验证。文档写入工具缺失时不擅自将 DOCX/PDF 改成 Markdown 交付。

## 核心模块与扩展

`plan_report.py` 中的 `MODULES` 提供稳定模块 ID、输入、输出、脚本和参考规则；`MODE_MODULES` 定义不同任务的组合。审查在修订前后各执行一次。各步骤输入输出使用普通文件，避免跨 Agent 私有会话对象。

- 项目理解：inventory、outline、narrative，使用项目类型、阶段、读者和深度决定内容。
- 内容增强：data、visuals、polish、appendix，按材料与配置选用。
- 文档交付：document、audit、render，使用目标格式和质量要求。

Agent 执行模块时将计划中的对应配置传给实际工具。例如 document 读取纸张、字体、目录和页码设置；audit 只对 DOCX 调用 `audit_docx.py`；render 调用可用排版器并检查页面。现有脚本 CLI 保持独立可用，计划不代替实际工作。

新增模块时添加清晰的输入输出、参考说明、失败处理和行为测试，再加入适用任务组合。新增组织配置放在 `extensions.<组织名>`，明确由哪个适配器解释；核心字段改变含义时提升 schema 版本并提供迁移规则。新增输出后端要验证其目录、字体、图表和页码能力，不能仅增加一个格式名称。

## 数据与图片本地化

数据脚本支持 `--encoding`、`--delimiter`、`--max-rows`。小数逗号数据使用 `--decimal-separator , --thousands-separator ""`；带分组符时明确指定分组符。空白或重复列名报错，短行和长行记入宽度问题；截断统计仅代表已扫描行。

附图清单可配置 `caption_prefix` 和 `description_prefix`。英文示例：`"caption_prefix": "Appendix Figure"`、`"description_prefix": "Note: "`，并将 `appendix_title`、题注和正文互引写成对应语言。自动互引检查支持中文、Figure、Fig.、Table、Appendix Figure；其他语言前缀需要人工复核或扩展检查器，不声称已自动检查。
