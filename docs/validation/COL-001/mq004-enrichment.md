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

## 验证计划与状态

开发阶段的定向检查已通过，覆盖正常补全、预印本日期排除、作者及题名不符、重复与歧义、已有值保护、限流/超时/重定向/坏响应，以及同步/异步预览、确认后导入和界面开关及出处展示。正式统计将在干净源码上完成完整回归后归档。

真实验证分两类，由 `tools/probe_bibliography.py` 固定 PDF SHA256、读取正式实例前后索引快照，且均不导入数据：

1. 原增强候选回放 + 实时 Crossref，直接检查原 MQ-004 空字段能否补全；不重新调用模型，不用外部修订后的最终值充当模型输出。
2. 当前分支真实 Luna 识别 + 实时 Crossref，检查完整增强预览流程及出处。

正式回归、两类真实实验的源码版本、结果和边界待执行后追加。原 MQ-003 摘要及全部批次证据保持原样。候选尚未合并部署，PR 维持 Draft。
