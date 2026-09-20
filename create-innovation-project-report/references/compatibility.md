# 运行环境与 Agent 兼容性

## 基本能力与可选能力

核心脚本要求 Python 3.9+，全部使用标准库。默认检查无需网络、管理员权限、Office、特定 Agent SDK 或外部 Python 包。文档主体编写、格式导出和视觉检查由当前 Agent 的可用工具完成，本技能的辅助脚本不构成独立的一键报告生成器。

```bash
python3 <skill-dir>/scripts/bootstrap_runtime.py --check-only --json
python3 <skill-dir>/scripts/check_skill_compatibility.py --json
```

Windows 使用 `py -3` 或实际 Python 路径。以命令参数数组调用脚本；在 PowerShell 或其他 shell 中对包含空格的路径按宿主规则引用。JSON 和命令行输出统一使用 UTF-8，支持读取带 BOM 的任务配置。相对路径遵循 [配置规则](configuration.md)。严格禁止任何缓存写入时通过 `python -B` 运行，避免解释器创建 `__pycache__`。

## 默认只读与显式安装

`bootstrap_runtime.py` 默认只检查依赖，不下载、不写 Agent 技能目录。`--check-only` 保留为明确只读的兼容参数。需要安装时使用 `--install`；`--offline` 阻止软件下载，但允许在显式安装模式下复制内置资源。

```bash
python3 <skill-dir>/scripts/bootstrap_runtime.py --install --agent-skills-root <skills-dir> --json
```

安装目标已有有效资源时复用；不兼容或不可写时直接读取内置副本，不覆盖。仅安装脚本中明确映射的软件包，未知模块返回错误，不根据模块名猜测下载包。安装失败返回结构化错误，保留可执行步骤。

缓存路径优先采用 `REPORT_SKILL_CACHE`，兼容旧 `CODEX_SKILL_CACHE`。未指定时使用 XDG 缓存、macOS 用户 Library/Caches、Windows LOCALAPPDATA 或 Linux 用户缓存目录，不要求目录属于 Codex。离线或只读任务不需要创建缓存。

内置 `humanizer-zh` 随附 MIT 许可证。`installed` 表示读取已安装副本，`bundled` 表示读取返回的内置路径；任何 Agent 都可通过文件读取使用它，无需支持 `$humanizer-zh` 语法。损坏的资源会被报告，影响的润色步骤不能计为完成。非中文任务使用相应语言编辑方式。

## 检查范围

检查入口元数据、相对链接、脚本语法、标准库导入、脚本帮助和内置依赖。`agents/openai.yaml` 是可选的 Codex UI 元数据；存在时检查，不将其缺失视为通用技能不可运行。

默认不遍历其他技能。需要排查副本时指定 `--scan-root <directory>`，或使用 `--scan-installed` 检查常见目录。同名副本只提示版本选择；不同 Agent 安装相同技能属于正常使用，不应让当前副本的检查失败。链接别名按实际路径去重，vendor 中的内置技能不计入外部冲突。

检查成功只表示当前文件结构与脚本接口通过检查，不代表所有 Agent 产品、Office 排版器或操作系统都已完成实机测试。自动化测试与待运行平台应分别记录。

## 能力不足时的处理

| 条件 | 继续方式 | 交付时说明 |
|---|---|---|
| 无终端或 Python | 阅读用户提供的资料，按核心规则编写或审查 | 未运行脚本检查 |
| 无 Git | 使用资料版本标记和上一版文档 | 不推断 Git 历史 |
| 无图像生成 | 使用项目原图、Mermaid、SVG、CAD 导出或图表规范 | 不生成伪造实物和数据 |
| 无文档写入或导出工具 | 完成内容和提纲；保留用户请求的格式 | 所需文件尚未生成 |
| 无页面渲染工具 | 执行可用的结构检查 | 版式未验证；required 策略下仍未完成 |
| 无数据 | 写测试设计与记录字段 | 不生成实测统计 |
| 只读技能目录 | 使用内置资源，将工作文件写入项目可写目录 | 技能目录无须写入 |
| 离线 | 使用本地资料、已有文献与内置资源 | 待补的外部资料 |
| 未知 Agent | 读取 SKILL.md，使用标准文件接口 | 根据实际能力选择步骤 |

LibreOffice、Word 或其他排版器均可承担渲染。发现可执行文件不代表渲染成功；用实际输出页面检查字体、分页、图表和目录。需要 LibreOffice 时使用无界面模式和临时隔离配置，遵守当前宿主权限；不自动启动 GUI 或修改全局设置。
