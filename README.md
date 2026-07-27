# Create Innovation Project Report

一个面向科创、课程实践、工程训练和项目结项场景的 Codex Skill。它能够从项目文件夹中的源码、模型、图纸、图片、实验数据和既有文档出发，生成或迭代正式中文项目综合报告 DOCX。

技能强调事实可追溯、图文对应和工程边界，不会把文件目录改写成报告，也不会补造准确率、运行速度、测试次数或量产结论。

## 核心能力

- 自动盘点机械、电路、嵌入式、算法、数据、测试和交付资料
- 区分当前版本、历史原型、重复文件和教学参考资料
- 建立内部事实清单，约束“已实现”“实验性设计”和“后续优化”措辞
- 分析参考 DOCX 的章节结构、内容密度、表格和图片数量
- 组织项目背景、需求、技术路线、创新点、实验结果和交付成果
- 生成机械装配爆炸图规范，并支持 CAD、图像生成和示意图三种模式
- 在报告最后阶段自动插入真实项目图片附录
- 检查自动目录、项目名称、图表互引、正文缩进和表格一致性
- 在技术内容稳定后，仅润色非表格正文
- 渲染 DOCX 并检查图片、表格、分页、字体和页眉页脚

## 目录结构

```text
create-innovation-project-report/
├── SKILL.md
├── agents/
│   └── openai.yaml
├── references/
│   ├── compatibility.md
│   ├── exploded-view-and-appendix.md
│   └── ...
├── scripts/
│   ├── bootstrap_runtime.py
│   ├── check_skill_compatibility.py
│   ├── inventory_project.py
│   ├── prepare_exploded_view.py
│   ├── appendix_images.py
│   └── ...
└── tests/
    └── test_*.py
```

仓库根目录的 README 不属于 Skill 安装内容。实际安装时复制内层 `create-innovation-project-report/` 文件夹。

## 安装

### Codex

```bash
git clone https://github.com/scf-stem/create-innovation-project-report.git
mkdir -p ~/.codex/skills
cp -R create-innovation-project-report/create-innovation-project-report ~/.codex/skills/
```

重新开始任务后即可通过 `$create-innovation-project-report` 调用。

### 其他 Agent

将内层技能目录复制到对应 Agent 的 Skills 目录。只要运行环境支持 `SKILL.md` 工作流和 Python 3.9 及以上版本，核心脚本即可运行。

## 首次运行

核心实现只使用 Python 标准库，不要求预装 `python-docx`、Pillow 或 PyYAML。

```bash
python3 ~/.codex/skills/create-innovation-project-report/scripts/bootstrap_runtime.py --json
python3 ~/.codex/skills/create-innovation-project-report/scripts/check_skill_compatibility.py --json
```

如果后续版本引入第三方模块，自举脚本会在用户缓存目录创建隔离环境并自动安装，不会修改全局 Python。

## 使用示例

```text
使用 $create-innovation-project-report，基于当前项目文件夹制作
《智能温室环境控制系统项目综合实践报告》，输出正式 DOCX。
```

也可以指定更具体的要求：

```text
使用 $create-innovation-project-report，分析参考报告的结构和篇幅，
补充机械爆炸图，并将真实样机照片统一放入附录A。
```

## 爆炸图流程

先生成清单模板：

```bash
python3 create-innovation-project-report/scripts/prepare_exploded_view.py --template
```

填写真实装配来源、零件清单、展开方向、视角、题注和输出位置后运行：

```bash
python3 create-innovation-project-report/scripts/prepare_exploded_view.py exploded-view.json \
  --output exploded-view-spec.json \
  --prompt-output exploded-view-prompt.txt
```

详细规则见 [`references/exploded-view-and-appendix.md`](create-innovation-project-report/references/exploded-view-and-appendix.md)。

## 附录真实图片

正文应先包含“见附图 A-1”等引用。内容和编号稳定后运行：

```bash
python3 create-innovation-project-report/scripts/appendix_images.py \
  report.docx report-with-appendix.docx \
  --manifest appendix-images.json
```

清单可配置图片顺序、宽度、最大高度、对齐、分页、题注、说明和替代文本。脚本输出新文件，不覆盖原稿，并保护原有表格内容。

## 测试

```bash
python3 -m unittest discover \
  -s create-innovation-project-report/tests -v

python3 create-innovation-project-report/scripts/check_skill_compatibility.py --json
```

测试覆盖：

- Python 3.9 洁净环境
- 首次运行依赖检测和自动安装分支
- 爆炸图参数与零件真实性约束
- 附录图片、题注、替代文本和 OOXML 关系
- 附图正文互引
- 重复分页保护
- 参考报告零依赖分析
- Agent Skill 名称冲突和元数据检查

## 报告写作边界

- 文件存在不等于功能已经完成实测。
- 测试计划和预期结果不能写成实际结果。
- 模型权重不能单独证明准确率和实时性。
- 编译通过不能证明硬件运行正常。
- 生成图只能解释结构和关系，不能替代真实测试证据。
- 成稿只写项目内容，不加入资料扫描过程、编写口径或内部检查说明。

## 兼容性

技能提供无图像生成工具、无 DOCX 专用 Skill、无 LibreOffice 和无数据可视化工具时的降级路径。详细说明见 [`references/compatibility.md`](create-innovation-project-report/references/compatibility.md)。

兼容性检查只能验证当前已安装的 Agent 和公开技能接口，无法对尚未发布的私有接口作永久保证。建议在安装或升级后重新运行兼容性检查。
