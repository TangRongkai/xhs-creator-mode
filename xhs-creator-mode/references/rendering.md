# 可选本地渲染工具

`scripts/render_notes.py` 使用 Pillow 进行确定性的文字和原截图合成，不调用网络、生成式 AI 或外部 API，不含用户资料。提供基础布局而非固定设计模板。需要 Python 3.10+ 与 Pillow 10+（如果本机没有，请先征得用户同意再安装依赖）。字体须使用本机有权使用的文件，不随 Skill 分发字体。

## 使用方法

1. 复制 `assets/page-plan.example.json` 为工作目录的 `plan.json`，按实际步骤改写。所有 `path` 相对于计划文件所在目录，或者绝对路径。先人工确认每个原图的裁切和遮盖坐标。
2. 找到真实的仿宋_GB2312 字体文件；没有时确认替代字体，必要时使用 `--font-index` 指定 TTC 字体索引。不要直接用未知字体路径。
3. 执行：

```bash
python3 /path/to/authentic-sop-carousel/scripts/render_notes.py plan.json --font /path/to/font.ttf --out ./sop-output
```

会输出编号 PNG、`overview.jpg` 和 `pages.zip`。要求输出目录为新建/空目录，避免将旧版和新图混入。渲染器在页面溢出时失败并提示页号；调整布局或拆页重跑，不通过全局缩小字体回避问题。

## JSON 字段

根对象：`width`、`height`（默认 1080、1920）、`margin`（默认 72，单位以1080宽为基准）、`pages`。

封面：`{"cover":true,"title":["品牌/主题","流程"]}`，默认无副标题、页码和附图；`cover_rules` 为 `false` 时不画细线。

正文页：`title` 必填；`lead` 可选，`section` 是可选短页眉，`footer:false` 可取消页码。`blocks` 按顺序组合：

- `{"type":"text","text":"...","size":40,"color":"ink"}`：段落（可换行）；色值可用 `ink`,`muted`,`red` 或十六进制颜色。
- `{"type":"heading","text":"...","size":45}`：小标题。
- `{"type":"steps","items":["操作一","操作二"],"size":40}`：自然数字编号、红色数字。各区块按页内累计编号，可通过 `start` 覆盖起始数字。
- `{"type":"image","path":"real.png","crop":[x1,y1,x2,y2],"masks":[[x1,y1,x2,y2]],"highlights":[[x1,y1,x2,y2]],"max_height":650,"width":936}`：原图处理后等比插入。坐标均为原始像素，右/下边界不包含；`crop` 省略时使用全图。遮盖用不透明浅灰，先遮盖再绘制红框；目标框须完整在 crop 内。高度、宽度按1080宽基准缩放。原图保持不变。禁止在计划里以虚构截图作为证据。
- `{"type":"rule"}`：细分隔线。
- `{"type":"gap","height":32}`：补充垂直间距。

排版器以段落顺序布局，采用适度中英文换行，标题以轻微描边增强字重；对复杂布局、脚注或精细字体控制，可直接修改脚本或改用 SVG/HTML 工具。输出为平面 RGB 图片，默认无原始图 EXIF。无论使用哪种方式，仍必须执行两轮人工视觉审查：脚本无法判断文字事实、隐私遗漏、实际框注目标及美观程度。
