# 爆炸图与附录实图流程

## 爆炸图触发条件

满足任一条件时建立爆炸图：

- 用户明确要求爆炸图、装配分解图或零件关系图。
- 项目有两个以上可区分零件，普通外观图无法说明装配顺序。
- 机械章节需要解释伸缩、套接、分层、紧固或维护拆装关系。
- CAD 装配体、零件模型或多角度实物图能够支持真实结构。

只有单一零件、没有结构证据或爆炸后不能增加理解时，不生成。

## 参数清单

创建 JSON 清单，至少包含：

- `subject`：图示对象
- `mode`：`cad-native`、`imagegen` 或 `schematic`
- `reference_images`：真实装配图或实物图
- `assembly_source`：CAD 装配文件
- `parts`：编号、名称、装配顺序、来源路径和必要说明
- `layout.view`：等轴测、正视、侧视、俯视或透视
- `layout.axis`：水平、垂直、纵深或径向展开
- `layout.spacing`：零件间距
- `layout.label_style`：仅编号、编号加名称或无标注
- `target.section`、`target.caption`、`target.width_cm`
- `output_image`

运行 `prepare_exploded_view.py --template` 获取模板。脚本会校验零件编号、文件路径、模式、视角、展开轴、题注和输出格式。

## 生成顺序

### 1. CAD 原生模式

1. 打开当前有效装配体，不使用历史或无关版本。
2. 建立单独的爆炸视图配置，不改写默认装配状态。
3. 沿真实装配轴移动零件，保持相对尺度和朝向。
4. 检查紧固件、套接件、线束和端部件是否遗漏。
5. 采用白色或透明背景、统一等轴测视角导出 PNG。
6. 图内只保留编号和必要引出线。

### 2. 图像生成模式

1. 使用真实装配照片、CAD 截图和零件清单作为引用。
2. 运行 `prepare_exploded_view.py` 生成规范和提示词。
3. 将全部参考图传给图像生成工具。
4. 要求保持零件数量、外形、连接关系和相对尺度。
5. 禁止加入标题、长说明、品牌标识、尺寸和性能数据。
6. 对照零件清单逐项验收；任何结构臆造都应重做。

### 3. 示意模式

只在需要解释装配逻辑、且无法获得真实外观渲染时使用。题注必须写“结构示意图”，不得把示意图描述成实物或 CAD 成果。

## 爆炸图输出

输出至少包含：

- PNG 或 JPEG 成图
- 规范 JSON
- 零件编号与名称对照
- 目标章节和题注
- 验收结果

爆炸图放入对应机械结构章节。正文解释装配顺序和关键关系；不要把爆炸图放入附录代替真实项目照片。

## 附录图片清单

附录只放真实项目照片、真实界面截图或真实测试图片。建立 JSON：

```json
{
  "appendix_title": "附录A 项目实物图片",
  "require_body_references": true,
  "start_new_page": true,
  "one_image_per_page": true,
  "width_cm": 15.5,
  "max_height_cm": 18.5,
  "alignment": "center",
  "images": [
    {
      "path": "images/project-overview.png",
      "number": "A-1",
      "caption": "项目样机整体外观",
      "description": "可见主体结构、传感器和执行机构。",
      "alt_text": "项目样机整体外观"
    }
  ]
}
```

图片路径相对清单文件解析，也可使用绝对路径。支持 PNG、JPEG、GIF 和 BMP；正式报告优先使用 PNG 或 JPEG。

## 附录终装

1. 先在正文相关章节写“见附图 A-1”等引用。
2. 冻结正文、图号和附图顺序。
3. 运行 `appendix_images.py`，输出新 DOCX，不覆盖上一版。
4. 检查新增媒体、题注、替代文本、图片比例和分页。
5. 运行 `audit_docx.py --check-cross-references`。
6. 完整渲染并逐页检查附录。

默认每张图片单独分页。需要连续排版时将 `one_image_per_page` 设为 `false`，并在渲染后确认图、题注和说明没有跨页。
