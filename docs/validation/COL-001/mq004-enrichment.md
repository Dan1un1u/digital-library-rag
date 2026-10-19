# MQ-004 原因分析与书目补全候选

## 缺字段的原因

MQ-004 是增强识别后的补全改进项，不把空值一概算作误识别，也不修改范围外的本机作者抽取规则。

| 样本 | 原增强结果 | 原因 | 本次补全方向 |
| --- | --- | --- | --- |
| ENEC | year=null；已有 arXiv 来源 | 页面中的预印本版本日期不能证明正式出版年，原流程无外部查询 | 检索题名与作者吻合的正式出版记录；没有记录时仍留空 |
| EQ-ViT | year/source_url 均为空 | 原前两页没有明确出版年或本篇 DOI/arXiv，模型不得猜填 | 查询正式注册书目中的出版日期和 DOI |
| PackQViT | year=2023，source_url=null | 原提示只接受页面出现的 DOI/arXiv；会议主页由外部核对得到，应用没有查询能力 | 通过书目注册 DOI 提供来源，无需硬编码会议网页 |

2026-10-19（Asia/Hong_Kong）查证的新情况：ENEC 已可检索到 ISCA 2026 的正式记录 `10.1109/isca66397.2026.00100`，出版日期为 2026-06；此依据与原批次用到的 PDF 修订日期不同。PackQViT 官方会议页现提供 DOI `10.52202/075280-0396`，Crossref 也返回对应记录。历史 metadata-review.json 保持原样，不将新查询倒算成当时的自动识别成功。

依据：[ENEC Crossref 记录](https://api.crossref.org/works/10.1109/isca66397.2026.00100)、[ENEC arXiv 页面](https://arxiv.org/abs/2604.03298)、[EQ-ViT Crossref 记录](https://api.crossref.org/works/10.1109/TCAD.2024.3443692)、[PackQViT 官方会议页](https://papers.neurips.cc/paper_files/paper/2023/hash/1c92edb990a05f2269f0cc3afbb4c952-Abstract-Conference.html)。

## 实现与匹配规则

采用“LLM 识别 → 页面证据校验 → 用户选择的外部书目补全 → 人工确认导入”。外部补全使用规则约束登记记录，不让 LLM 凭记忆生成 DOI。第一版支持 Crossref 的期刊论文与会议论文；不包含所有图书馆文献类型和全部注册机构。

- 新增 `bibliography.py`。固定请求 Crossref `/works`，仅发送题名与前两位作者姓名；返回至多 5 项，并限制字段、响应大小和超时。使用独立的无模型凭据会话，禁止重定向，不跟随 PDF 或响应内任意 URL，不自动重试。
- 题名须经 NFKC、标点及大小写归一化后完全吻合，副标题参与比较。第一作者须吻合，完整姓名的交集须达到两侧较大作者集合的 80%（向上取整），多人论文至少两位，单作者论文允许一位。缩写、缺作者或小幅标题改写可能无法补全，留给人工核对，不报告为模糊匹配置信度。
- 仅一个匹配记录才补全；完全相同的重复项可合并。不同 DOI 或元数据存在差异的匹配项视为歧义，不按搜索排名自动选择。
- 仅补 `year`、`source_url` 的空值；已有 arXiv 来源等保留。已有年份或 DOI 与外部候选不一致时保存冲突，供用户选择，不自动覆盖。
- 出版日期单独记录 `published-print` / `published-online` / `published`。优先在明确的在线/印刷日期中选最早出版日期；没有明确类型时才用通用 published。不同日期类型原样展示，不把 `created`、`issued`、`accepted`、预印本 posted-content 当作正式出版年。
- 预览保存匹配规则、作者交集、原出版日期、查询时间、来源记录链接、补全字段与冲突；字段出处标记 `bibliographic_lookup`，仍为待核对候选。
- 同步预览与任务预览增加 `use_lookup=false` 默认选项。只有用户选择、增强识别成功、真实模式和服务器允许时查询。界面提供“联网补全出版资料”，默认关闭；管理员可用 `METADATA_LOOKUP_ENABLED=false` 禁用，超时由 `METADATA_LOOKUP_TIMEOUT_SECONDS` 设置。
- 网络、限流、无匹配、歧义或格式错误都不丢弃已有识别结果；缺字段留空并提示。预览不写馆藏，确认后的入库流程继续复用现有接口。

API 依据：[Crossref 官方查询说明](https://api.crossref.org/swagger-ui/index.html)、[官方字段及日期定义](https://github.com/CrossRef/rest-api-doc/blob/master/api_format.md)、[查询使用建议](https://www.crossref.org/documentation/retrieve-metadata/rest-api/tips-for-using-the-crossref-rest-api/)。

## 验证结果（2026-10-19，Asia/Hong_Kong）

正式验证均基于干净源码 `bbcbe98bbbd5107f4b3ba867568e1e27370ce9ec`，证据另行归档，未回写既有记录。

- 完整离线回归 **440 passed，0 failed/error/skipped/xfail**，执行前后工作区干净，见 [完整摘要](mq004-all-summary.json)。仍有两条既有警告：Starlette/httpx 弃用、重复 PDF 保留原元数据。
- 本轮新增 **51 项参数展开用例：41 项书目校验和失败路径 + 10 项接口/流程/界面验证**。本 PR 累计新增 110 项、复用基线 330 项；原 MQ-003 回归继续通过。
- 覆盖正常补全、日期类型、作者/题名不符、重复与歧义、已有值保护、限流/超时/重定向/坏响应，以及同步/异步预览、确认后导入。界面采用 Streamlit AppTest 实际操作开关、重新识别按钮并检查年份及出处展示；不是用户人工点检或演示视频。
- 新书目模块语句覆盖 **100.00%**、分支覆盖 **96.43%**；增强 API 模块 **80.80% / 74.00%**。未覆盖分支见摘要。覆盖率只描述离线执行，不代表匹配正确率或已覆盖所有外部服务行为。

真实验证分两类，由 `tools/probe_bibliography.py` 固定 PDF SHA256、读取正式实例前后索引快照，且均不导入数据：

1. 原增强候选回放 + 实时 Crossref，直接检查原 MQ-004 空字段能否补全；不重新调用模型，不用外部修订后的最终值充当模型输出。
2. 当前分支真实 Luna 识别 + 实时 Crossref，检查完整增强预览流程及出处。

两类实验均验证了以下候选变化：

| PDF | 补全前 year / source_url | 补全后 | 注册记录及实际补全字段 |
| --- | --- | --- | --- |
| ENEC | null / 已有 arXiv | 2026 / arXiv 保留 | `10.1109/isca66397.2026.00100`，published-print 2026-06；只补 year |
| EQ-ViT | null / null | 2024 / DOI 来源 | `10.1109/tcad.2024.3443692`，published-print 2024-11；补 year 与 source_url |
| PackQViT | 2023 / null | 2023 / DOI 来源 | `10.52202/075280-0396`，published-print 2023；只补 source_url |

真实运行记录：

- [首次原候选回放](mq004-replay-01.json)：ENEC 成功，EQ-ViT 的 Crossref 查询超时；结果保留 null 与原作者，状态为 failed/TIMEOUT。工具在此结束，因此 PackQViT 当次未执行。该记录整体 passed=false，不删去或算为成功。
- [第二次原候选回放](mq004-replay-02.json)：同一源码、同一输入，显式重新发起一次实验，3/3 完成上述补全；不是程序内自动重试。
- [真实 Luna + 实时 Crossref](mq004-live-preview.json)：三次模型调用均 completed，三篇均完成上述补全，3/3 达到本批预设结果。结果保存补全前后候选、原返回书目、匹配依据、字段出处和预期值。

所有实验的正式馆藏前后均为 **25 篇 / 1821 片段**；完整索引 manifest 保持一致，索引 `idx_20261018T153334_20ed96d8ced7`。没有对已入库文献重识别、修改记录或重建索引。此处“通过”是三篇限定样本符合预设结果，不是一般文献的补全率或准确率。

## 复现与限制

```powershell
.venv/Scripts/python.exe scripts/run_catalog_checks.py --scope all --output reports/COL-001/mq004-rerun
```

真实实验入口：`tools/probe_bibliography.py --cases <本机清单.json> --batch docs/validation/COL-001/batches/COL-001-20261018-P01/metadata-review.json --mode replay或live --env-file <本机配置.env> --output <新目录>`。清单按 case_id、pdf_path、expected_year、expected_source_url、expected_doi 固定预期，并与归档批次 SHA256 核对输入。PDF 路径和配置仅在本机；预期值是实验对照，不进入业务匹配器。

单一 Crossref 数据源不能覆盖全部文献，首五项之外的真匹配、作者缩写、题名改写和缺失注册信息会导致留空。匹配也依赖增强候选题名和作者本身正确，不保证绝对不会误配。网络可能超时，本次已有真实失败证据；第一版不做持久缓存和自动重试。当前仅补空值，冲突需人工选择，图像页的原始识别仍保留 MQ-003 中说明的限制。

原 MQ-003 摘要及全部批次证据保持原样。候选尚未合并部署，正式实例仍是之前版本；PR 维持 Draft。新候选的用户人工验收与视频演示尚未执行，不沿用之前入库抽查的人工确认。
