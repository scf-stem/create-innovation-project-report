# 运行环境与 Agent 兼容性

## 首次运行

使用当前 Agent 可用的 Python 3.9 或更高版本运行：

```bash
python3 <skill-dir>/scripts/bootstrap_runtime.py --json
```

自举脚本会：

1. 检查 Python 版本。
2. 扫描 `scripts/` 的导入项。
3. 区分标准库、本技能本地模块和第三方模块。
4. 在发现第三方模块时，在用户缓存目录创建隔离虚拟环境。
5. 自动安装缺少的软件包并返回应使用的 Python 路径。
6. 校验随附的 `humanizer-zh` Skill 及其参考文件。
7. 当前技能位于标准 `skills` 目录时，将缺少的 `humanizer-zh` 原子复制到同级目录。

当前核心实现只使用标准库，因此全新环境不需要预装 `python-docx`、Pillow 或 PyYAML。Python 本身属于 Agent 运行时前提；在 Codex 桌面环境中优先通过工作区依赖加载器取得 Python。

`humanizer-zh` 的完整副本位于 `vendor/humanizer-zh/`，保留原 MIT 许可证。自举结果会在 `skill_dependencies.humanizer-zh` 中返回使用模式和路径：

- `installed`：Agent 可以按 `$humanizer-zh` 调用。
- `bundled`：直接读取返回路径中的 `SKILL.md` 和参考文件。

从普通 Git 仓库而不是标准技能目录运行时，可明确指定安装位置：

```bash
python3 <skill-dir>/scripts/bootstrap_runtime.py \
  --agent-skills-root <agent-skills-dir> --json
```

目标目录已有完整版本时直接复用；已有不完整或名称不一致的版本时不覆盖，转用内置副本。安装目录不可写时也转用内置副本，因此润色流程不依赖网络或人工安装。

## 兼容性检查

运行：

```bash
python3 <skill-dir>/scripts/check_skill_compatibility.py --json
```

检查范围包括：

- `SKILL.md` 前置元数据、目录名和行数
- `agents/openai.yaml` 的显示名称、描述和默认提示词
- 引用文件是否存在
- 脚本语法、导入项和 `--help` 可运行性
- 用户专属绝对路径
- Codex、Agents、Claude 和插件缓存中的同名技能冲突
- Python 运行时和可选外部工具
- 内置 Skill 依赖的元数据、相对引用和可用模式

“兼容”表示技能本身没有结构、依赖或命名冲突。它不能证明未来未知 Agent 的私有接口永远不变化；每次安装或升级后都应重新运行检查。

## 能力降级

### 没有图像生成工具

优先从 CAD 软件导出真实装配爆炸图。CAD 也不可用时，保留 `prepare_exploded_view.py` 生成的规范、零件清单和提示词，继续完成文字和附录，不生成伪造图片。

### 没有 DOCX 专用 Skill

使用本技能标准库脚本完成资料盘点、参考报告分析、审计和附录图片插入。文档主体仍可使用 Agent 自带的 OOXML 或 Word 能力创建。

### 没有 LibreOffice

执行 DOCX 包结构、目录、交叉引用、表格和图片检查，并明确记录未完成页面渲染。LibreOffice 属于视觉验收增强能力，不是本技能脚本启动依赖。

### 没有数据可视化工具

保留真实数据表和计算说明，不生成推测性图表。报告其他章节照常完成。

## 安全边界

- Python 包只安装到用户缓存中的隔离环境。
- 随附 Skill 只在目标不存在时安装，不覆盖现有技能；安装失败时使用内置副本。
- 不调用管理员权限，不改系统 Python。
- 兼容性扫描只读访问其他技能目录。
- 跨 Agent 传递使用普通 Markdown、JSON、DOCX 和图片文件，不依赖私有消息格式。
