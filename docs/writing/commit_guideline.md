# 提交信息规范

## 标题

`type(scope): 中文摘要`，不加句号。写改动后的结果，不写过程。

- **type**：`feat` / `fix` / `refactor` / `perf` / `docs` / `test` / `chore`。
- **scope**（按这个项目的模块）：

| scope | 范围 |
|---|---|
| `ranges` | Ranges 条目的编辑与映射（含 ComplexMapping） |
| `sections` | Skin / Aim / RotExpr / Material / JXG 等其他分区 |
| `preview` | 驱动器与原生约束预览（`jcns_drivers`、`jcns_preview`、预览相关的 `jcns_operators`） |
| `read` | 源读取与目标合成（`modules/jcns_source_read.py`、`jcns_mapping`） |
| `mirror` | 镜像 |
| `import` / `export` | 导入、导出 |
| `codec` | 解析与写入（`jcns_parser`、`jcns_writer`、`jcns_schema`） |
| `ui` | 面板、列表、文案 |
| `probes` | `scripts/probes` 下的实机探测脚本 |
| `docs` | 文档 |

- 定版固定为 `chore(version): 定版 X.Y.Z`。

示例：`fix(preview): 缩放按相对静止缩放的比值驱动`

## 正文

只写 diff 里看不出的事实，一般不超过五行：

- 原来的行为错在哪。
- 现在怎样。
- 兼容影响：要不要重新导入、有没有别名、导出字节会不会变。
- 刻意没改的部分。

## 不写

调查证据、语料数、验证记录、测试通过数、文件或函数清单、日期。

例外：应该跑却没跑、或者仍然失败的测试，要写一行说明。

## 拆分

- 按类别拆，一件事只归一个类别。
- 每个提交单独检出都能运行。
- 不同人的改动分开提交。
- 定版单独提交。
- 注释修缮不和逻辑改动混在一起。
