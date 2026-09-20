# Agent 接入与调用

## 共用入口

复制整个 `create-innovation-project-report` 目录，保留 SKILL.md、scripts、references、vendor 及许可证。入口只采用通用 name、description 元数据；`agents/openai.yaml` 仅服务 Codex 的展示，其他 Agent 可以忽略。无需导入厂商 SDK 或使用特定 MCP。

各 Agent 均可接受自然语言指令：

> 读取此目录的 SKILL.md，根据 report-config.json 处理项目资料，执行适用模块，并交付所要求的报告或审查结果。

有 Python 时运行同一 `plan_report.py` 和辅助脚本。无终端时直接读取规则与用户提供的材料。`runtime.agent` 是本技能的标识，不是宿主产品配置；它不会安装该 Agent、加载插件或授予权限。

## 接入位置

以下位置为安装技能文件夹的父目录。每个位置下都应为 `create-innovation-project-report/SKILL.md`。只选择当前宿主明确支持的一处，避免同时复制多份后产生版本选择歧义。

| Agent | 接入方式 | 需要确认的能力 |
|---|---|---|
| Codex | 当前会话声明的 skills 根目录；现有安装可继续使用 | Python 路径、文件写入、文档及渲染工具 |
| Claude Code | 个人 `~/.claude/skills/` 或项目 `.claude/skills/` | 终端、文件读取、文档工具；可通过 `/create-innovation-project-report` 调用 |
| Gemini CLI | `~/.gemini/skills/` 或项目 `.gemini/skills/`；也支持 `.agents/skills/` 别名 | 技能发现是否启用，以及本地运行与写入能力 |
| Cursor | 项目 `.cursor/skills/` 或 `.agents/skills/`；个人目录同名置于用户目录 | 本地、SSH 和云端是否实际拥有技能与项目文件 |
| GitHub Copilot | 项目 `.github/skills/` 或 `.agents/skills/`；个人 `~/.copilot/skills/` | 所用宿主是否支持 skills、执行脚本与写入文件 |
| 其他 Agent 或 API 工作流 | 将目录作为可读资源，明确要求读取 SKILL.md | 文件、终端、文档后端能力按实际声明 |

Claude、Gemini、Cursor、Copilot 的目录说明按其官方文档核对。产品升级时以官方文档和当前工具列表为准；表格说明接入方式，不代表所有产品均完成实机端到端测试。

## 远程、容器和只读环境

- 云端任务需实际挂载或上传技能与项目资料；本机已安装不能证明云端可见。
- 在任务配置文件所在目录解析项目路径，输出使用工作区可写目录，不使用开发者个人绝对路径。
- 技能目录可只读；环境检查和计划生成到标准输出均不需修改技能或全局配置。
- 离线任务使用已提供的来源与内置资源。只有执行模式明确开启安装时才处理依赖，未知下载包报错。
- Python 可执行文件、Office、字体、图像生成、CAD 和渲染能力由宿主检查；不通过 Agent 名称推断。
- 通过标准 JSON、Markdown、DOCX/PDF 和图片交接；不得在配置中嵌入需要其他 Agent 私有工具名才能解释的核心步骤。

## 官方参考

- [Claude Code Skills](https://code.claude.com/docs/en/skills)
- [Gemini CLI Agent Skills](https://geminicli.com/docs/cli/skills/)
- [Cursor Agent Skills](https://cursor.com/docs/skills)
- [GitHub Copilot Agent Skills](https://docs.github.com/en/copilot/concepts/agents/about-agent-skills)

核对日期：2026-09-20。当前仓库自动化测试验证配置和脚本行为；宿主产品端到端验证须单独记录产品版本、可用工具和实际任务结果。
