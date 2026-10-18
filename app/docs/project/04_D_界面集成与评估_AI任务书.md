# 组员 D 界面集成与评估 AI 任务书

## 1 对 AI Agent 的直接指令

你现在承担四人数字图书馆项目中组员 D 的开发任务。请把 A 的馆藏、B 的检索和 C 的问答装配为可运行应用，完成 API、Streamlit 界面、统一配置、启动脚本、集成测试和总体评估工具。交付真实文件与运行记录，不只给集成建议。

**文档的重要性：本文是正式任务书、需求规格、接口契约和全组验收依据。你是共享配置和应用装配负责人，必须完整读取共同规格，并让 A/B/C 成果按同一接口组合。你不能为了快速显示页面而另写一套导入、检索或问答实现，也不能用 mock 输出冒充真实完成。**

先遵守系统、用户和仓库规则。存在总说明书及其他任务书时读取，核对共同规格版本。用户变更范围时记录并同步全组。本文内嵌契约足以开始，但不表示你已经读过其他缺失文件。

先检查用户现有文件，保留已有实现。你编辑 api、ui、shared、tests/integration、tests/fixtures、scripts、evaluation/dataset、evaluation/reports、handoff/D、README.md、pyproject.toml、.env.example、.gitignore、docs/demo.md 和 docs/presentation_outline.md。不擅自改 A/B/C 核心实现；发现问题给出准确复现及要求对应负责人修复。

## 2 目标与边界

为用户提供馆藏页、搜索与问答页、管理与实验页，接收请求、显示状态、展开原文、打开 PDF 页面。统一配置和数据验证，确保真实模块接入后不需要重写 UI。

你负责依赖装配和 HTTP 映射，不负责重新实现算法；接口不符合时先指出具体差异，不能静默新增“兼容字段”把错误掩盖。其他模块缺失时用自身 integration 测试替身推进，真实模式不自动回退 mock。

第一版采用本地、单进程后端及可信课堂使用。无需公网部署、用户账户或完整权限管理。

## 3 必须交付的结构

~~~text
src/dlrag/
  __init__.py
  shared/
    config.py
    models.py
  api/
    main.py
    routes.py
    services.py
  ui/
    app.py
tests/integration/
tests/fixtures/
scripts/
  seed_demo.py
  run_evaluation.py
evaluation/dataset/
  questions.jsonl
  annotation_guide.md
evaluation/reports/
  overall_report.md
docs/
  demo.md
  presentation_outline.md
handoff/D/
  README.md
  requirements.txt
  acceptance.md
  candidate_questions.jsonl
README.md
pyproject.toml
.env.example
.gitignore
~~~

布局可细化。pyproject.toml 使用 src 包布局，合并各人 handoff 下的依赖，并记录实际可运行版本。不要覆盖其他人的交接依赖文件。

## 4 第一天先完成的工作

1. 建立目录、可安装的工程骨架和 .env.example。
2. 将共同规格的数据结构实现为 API 验证模型。
3. 为缺失 A/B/C 建立 D 自己的测试替身，结构与接口一致。
4. 完成 UI 骨架及 /health，清楚显示 real/mock 和模型配置状态。
5. 建立服务装配入口，后续替换实例，而不是替换整个应用。

合成 fixtures 必须明确标记，不带真实论文身份。包在没有密钥时也能导入和运行 mock 单元测试。

## 5 模块装配与运行配置

D 通过一个配置入口向三个模块传参，至少支持：

| 配置 | 用途 |
|---|---|
| DATA_DIR、DB_PATH、FILES_DIR、INDEX_DIR | 运行数据与索引位置 |
| APP_MODE | real 或 mock，必须显式选择 |
| EMBEDDING_MODEL、EMBEDDING_REVISION | B 的模型标识 |
| LLM_BASE_URL、LLM_MODEL、LLM_API_KEY | C 的模型服务 |
| LLM_TIMEOUT_SECONDS | 真实模型超时 |
| MAX_UPLOAD_MB | 默认 25 MB |
| CHUNKING_CONFIG | tokenizer/字符模式、长度和重叠 |
| API_BASE_URL | UI 到后端的地址 |

.env.example 只放占位符与说明。真实密钥、PDF、SQLite、模型缓存不进版本控制。

real 模式下缺模型配置必须在 /health 和界面显示未就绪，并在依赖该模型的操作中返回明确错误；不要启动一个永远输出固定答案的“真实服务”。

LibraryStore、Retriever、QAEngine 实例在应用服务层管理，避免每次请求重新加载 embedding。单进程使用读写互斥：上传全量构建期间请求等待或明确返回未就绪；一条问答请求必须固定同一索引版本。不启用多 worker。

上传流程由你编排：
1. 校验类型、大小、元数据，保存本次临时文件。
2. A.ingest_pdf 返回 indexing 或已有状态。
3. 取得 include_indexing=True 的候选 Chunk。
4. B.build 成功切换有效索引。
5. 将已纳入索引的新文献设置 ready。
6. 返回 document 与有效 index_version。

失败时不报成功；B 重建失败保留旧索引，新文献保留可重试状态与错误。CLI 导入后未建索引的文献要有明确“建立索引/重试”操作入口，可通过本地 scripts/seed_demo.py 或受控管理操作实现，不必增加未经约定的公共 API。

## 6 API 与 UI 实现

HTTP 方法、路径、请求、响应及状态码严格按共同规格。用 id 查找服务端原文件，不让客户端传任意服务器路径。/search 文献聚合保留最优 rank 和 preview，同时返回片段 hits。

页面要求：

### 馆藏页

显示标题、作者、年份、主题与来源，支持过滤。公开浏览默认 ready；管理视图显示 parsing/indexing/failed 及错误。不要把 PDF 文件路径当成用户需要理解的元数据。

### 搜索与问答页

- 支持搜索和问答两种动作，过滤条件可见。
- 搜索时可选择 keyword/vector/hybrid。
- 问答展示系统理解、claims、limitations 和相关文献。
- 用 evidence_id 为每条 claim 渲染一致引用编号。
- 点击引用展开原文卡片，提供正确 PDF 页链接。
- 澄清状态显示一个追问和选项，用户选择后构成新问题再提交。
- 证据不足和错误使用可理解文字，不只展示堆栈或 HTTP 数字。
- 页面首部清晰标识 mock 模式。

PDF 页跳转依赖浏览器查看器，需在实际演示环境验证。若 #page 未被支持，提供可验证的页号和打开原文件方式，明确高亮或自动定位尚未支持，不能虚报该验收项。

### 管理与实验页

支持受控本地上传及状态查看，展示当前索引和模型配置是否就绪。可显示已运行的实验报告或提供运行命令；不承诺已实现复杂在线实验管理。

第一版 quote 展示规范原文即可，PDF 原页高亮是可选功能。

## 7 评估数据与执行工具

你负责汇总而非代写所有人的标注：

1. 从 handoff/A/B/C/D/candidate_questions.jsonl 收集约 60 题。
2. 根据总说明的配额和题型去重。
3. 组织 A↔C、B↔D 交叉复核。
4. 将相近改写放在同一 split，锁定 dev/test。
5. 核对真实 doc_id、chunk_id、evidence_groups，冻结索引后再评估。
6. 在 annotation_guide.md 写清楚引用支持和题型判断规则。

你自己的约 15 题建议 multi_document 10 + unanswerable 5，由 B 复核。缺真实馆藏时只保存明确标识的样例及标注模板，不能生成看似真实的最终数据集。

scripts/run_evaluation.py：
- 接受 dataset、mode、检索方式和输出目录；
- 记录 git 版本（若有）、模型、依赖、配置、馆藏哈希和索引版本；
- 保存逐题结果和汇总结果；
- 调用 B/C 的工具或公开接口，不另写不同算法；
- mock 成绩不进入真实实验对比；
- 人工指标缺标注时显示未评估；
- 网络调用失败、空分母、缺少参考证据分开处理，不当作成功；
- 同一测试题各实验配置保持一致，只改变被比较组件；
- 记录样本数、中位数、P95 耗时和失败数。

overall_report.md 写清实际结果、与预期差异、至少三个具体失败案例和局限。无真实实验时交付运行入口及报告模板，明确未执行。

## 8 必须完成的集成测试

| 场景 | 验收 |
|---|---|
| A/B/C 模拟装配 | API 全部核心状态可用统一结构 |
| 真实合成 PDF 链路 | 入库→建索引→检索→问答→原文件 |
| 重复文件 | 不重复文献及文本块 |
| 错误文件、超限、非法过滤 | 状态码和信息正确 |
| 各种检索模式 | Filters 与聚合一致 |
| 引用点击 | 文献、原文、页码相符 |
| 歧义问题 | 追问后可继续独立请求 |
| 无答案问题 | 明确不足，没有虚构 claims |
| 缺模型/超时 | real 不静默退回 mock |
| 索引重建失败 | 旧索引仍服务，新文献状态准确 |
| 应用重启 | 正确加载原馆藏与索引 |
| 完整启动说明 | 从空运行数据到演示可复现 |

测试替身证明接口；至少一次真实模块接入验证才能称集成完成。即使只有合成 PDF，也需区分“真实模块运行”与“真实学术语料评估”。

## 9 启动与交付要求

README.md 必须包含共同规格给定的安装、测试、后端、UI、seed_demo、评估命令，并逐条实际执行或注明未执行。提供终端、端口、环境变量、数据位置、真实与 mock 切换和停止方法。

seed_demo.py 能在空目录准备明确标识的合成演示资料、通过 A 导入、B 建索引；真实问答取决于 C 的模型配置，不能用固定答案掩盖缺配置。

docs/demo.md 提供四类演示问题、期望行为、实际证据点击路径和故障备用步骤。docs/presentation_outline.md 按 A/B/C/D 分配展示时长与内容，不伪造实验结论。

handoff/D/README.md 列：
- 当前使用的各模块版本及状态；
- 可运行命令、API 示例与模式；
- 合并的依赖和冲突处理；
- 已完成/未完成验收；
- 尚需人工配置、资料核查与课堂准备。

acceptance.md 真实记录执行结果。最终回复说明产出文件、真实检查、尚缺模块或模型，以及可复现的下一步。不要把已画出界面等同于完整集成完成。

## 10 缺少其他成果时继续工作

用你自己目录中的可替换测试依赖推进界面、配置和 HTTP 验证；给 A/B/C 列出精确字段/接口差异和复现。不要越界修改他们的核心模块，也不要只等待。

以下共同规格是全组必须遵守的集成依据，必须完整读取。

## 共同规格与集成契约

本节在五份文件中保持一致，版本为 **1.0**。它是接口和数据的共同依据。实现时必须遵守，不得在自己的模块中另起字段或接口。需要变更时，先提交具体变更建议，由组员 D 协调更新总说明书和四份任务书，再同步代码。本文是项目规格，不是已经实现的功能声明。

### 项目范围与默认配置

- 项目：基于 LLM 的专题数字图书馆搜索与证据问答系统。
- 默认馆藏：数字图书馆、信息检索、知识组织主题，50–100 篇具有使用权限的文本型 PDF；先以 10 篇试运行。扫描件识别、复杂表格理解、微调、知识图谱暂不纳入必做。
- 第一版：批量导入及元数据、关键词检索、向量检索、混合检索、意图澄清、单轮带引用问答、证据查看、PDF 页跳转、实验评估。
- 约四周开发；Python 3.11；FastAPI 后端；Streamlit 界面；SQLite；模型与依赖版本在首次可运行后固定。这里的版本是建议基线，应先验证开发机兼容性。
- B 负责 embedding，C 负责生成模型。LLM 提供方通过环境配置接入；真实模型不可用时允许明确标识的 mock 模式。mock 只能证明接口运行，不能作为语义效果或真实回答质量的实验结果。
- 不自动购买服务、上传整个馆藏到外部平台或公开部署。API 密钥由使用者配置；调用外部 LLM 时，仅发送该次问题和选定片段，并在运行说明交代这一点。
- 默认参数：每块约 300–500 tokens、长段落拆分重叠约 50 tokens、不跨 PDF 页；每个检索分支取 20 条；RRF 常数 60；证据最多 6 块，总上下文预算可配置。切块 tokenizer 名称、版本和计数口径须记入索引清单。
- 用实际 tokenizer 计数；如使用字符近似，必须明确记录该模式及字符阈值，不能把字符数报告为 token 数。
- 年份与主题过滤在两个检索分支一致生效。年份为空的文献在指定年份范围时排除；主题过滤为与选中主题至少有一个交集。
- 文件路径在服务端解析；API 不接受客户端给出的服务器绝对路径。原始文件、模型缓存和数据库不放进源码提交。

### 目录与编辑归属

~~~text
project/
  docs/project/                    这五份设计与任务文档
  src/dlrag/
    __init__.py                   D
    ingestion/                    A 所有实现
    retrieval/                    B 所有实现
    qa/                           C 所有实现
    api/                          D 所有实现
    ui/                           D 所有实现
    shared/                       D 配置与 API 模型
  tests/
    ingestion/                    A
    retrieval/                    B
    qa/                           C
    integration/                  D
    fixtures/                     D 公共小型样例
  scripts/                        D 启动与端到端演示
  evaluation/
    ingestion/                    A 解析质量记录
    retrieval/                    B 检索实验
    qa/                           C 问答与引用评估
    dataset/                      D 汇总经全员标注的测试题
    reports/                      D 总体结果
  handoff/
    A/ B/ C/ D/                   各自的交付说明和依赖片段
  data/
    raw/ library.sqlite indexes/  运行生成，不提交实际馆藏
  .env.example                    D
  pyproject.toml                  D
  README.md                       D
~~~ 

A、B、C 不修改 D 或其他成员拥有的实现文件。缺少共享组件时，通过依赖注入、临时测试目录和自身测试替身推进；不要创建竞争版本的共享配置。D 是共同配置、依赖合并和应用装配的负责人。各人将依赖写入自己的 handoff/<角色>/requirements.txt，由 D 合并到 pyproject.toml。有既存仓库规则时先读取，保留用户已有代码。

### 配置键与错误约定

上传 metadata_json 对象只接受 title、authors、year、topics、language、source_url、rights_note。数组、年份和语言按 Document 规则；title 缺失时可用文件名并标待核验；rights_note 缺失时写“待人工确认”，不能自动写成已授权。doc_id、文件哈希、状态和路径由服务端生成，客户端不能覆盖。A 的 metadata 参数使用同一组键。

A.ingest_pdf 的 options 使用下列 ChunkingConfig，D 向 A 传入，并把同一值传给 B 记录在 manifest：

~~~json
{
  "count_mode": "token",
  "tokenizer_name": "<实际 tokenizer 标识>",
  "tokenizer_revision": null,
  "max_tokens": 400,
  "overlap_tokens": 50,
  "max_chars": 1200,
  "overlap_chars": 150
}
~~~

token 模式使用 max_tokens/overlap_tokens，character 模式使用 max_chars/overlap_chars；不用的参数仅保留配置，不混用单位。tokenizer 获取失败不能静默降级，应明确选择 character 模式并记录。character 模式 Chunk.token_count 为 null，额外记录 char_count；这不是实际 token 统计。同一个有效索引不混用切块配置；对已经导入的相同 PDF 要改变切块参数时，A 提供明确的离线重建流程，默认重复导入不重切。重建会改变标注位置，应在冻结测试集前完成。

B 的 settings 使用 candidate_k=20、rrf_k=60、normalize_embeddings=true；模型名称/修订由 embedding_backend 的配置提供。C 的 settings 使用 planning_enabled=true、retrieval_mode="hybrid"、retrieval_top_k=20、max_evidence_chunks=6、context_budget_tokens=6000、max_output_tokens=1000、max_answer_repairs=1。预算是起始配置；C 必须按实际服务上下文上限检查，并预留系统提示和输出，不强行发送超限内容。D 的 baseline 评估可以通过 planning_enabled=false 关闭改写与澄清，记录这项差异。

各模块提供名为 ProjectError 的异常，至少有字符串属性 code/message；可各自定义，不要求共享 Python 类的身份相同，D 按属性处理。推荐固定代码：

| 模块 | 错误码 |
|---|---|
| A | INVALID_PDF、NO_EXTRACTABLE_TEXT、FILE_NOT_FOUND、CHUNK_CONFIG_MISMATCH |
| B | INDEX_NOT_READY、EMBEDDING_NOT_CONFIGURED、EMBEDDING_MISMATCH、INDEX_BUILD_FAILED |
| C | MODEL_NOT_CONFIGURED、MODEL_TIMEOUT、MODEL_UNAVAILABLE、OUTPUT_VALIDATION_FAILED、UNSUPPORTED_HISTORY |
| D | INVALID_REQUEST、NOT_FOUND、UPLOAD_TOO_LARGE、UNSUPPORTED_FILE、INTERNAL_ERROR |

参数问题通常映射 422，对象缺失 404，上传超限 413，类型不支持 415，模型或索引未就绪/超时 503，内部失败 500。坏 PDF 与空文本导入返回 422 并保留管理诊断记录。/ask 遵循完整 AnswerResponse；不要把有 error 属性的任意对象当作失败，业务状态须按明确规则识别。

### 统一数据对象

模块边界使用可 JSON 序列化的 dict/list；内部可自行使用类。D 在 API 层实现验证模型。必须使用以下字段，扩展字段不得替换核心字段。

**Document**

~~~json
{
  "doc_id": "d_012345abcdef",
  "title": "文献标题",
  "authors": ["作者甲"],
  "year": 2023,
  "topics": ["信息检索"],
  "language": "en",
  "source_url": null,
  "rights_note": "组员确认可用于课程项目",
  "file_sha256": "<原始文件完整 SHA256>",
  "status": "ready",
  "error_code": null,
  "error_message": null,
  "page_count": 8
}
~~~

year 允许 null；authors/topics 为数组；language 使用 zh/en/mixed/unknown。缺失作者和年份不让模型猜测。元数据标题必须非空，可暂用文件名并注明待核验。文献 ID 使用文件哈希的稳定映射，并检测截短冲突。状态为 uploaded/parsing/indexing/ready/failed。A 解析成功后返回 indexing，D 在 B 成功构建索引后才设置 ready；解析完成的 indexing 文献可作为候选建索引输入。索引失败保留可重试状态和错误，不虚报 ready。API 默认只展示可服务的 ready 文献，管理页可查看全部状态。

**Chunk**

~~~json
{
  "chunk_id": "c_012345abcdef_p0003_0001",
  "doc_id": "d_012345abcdef",
  "pdf_page": 3,
  "printed_page": null,
  "section": null,
  "text": "来自 PDF 第三页的原文片段。",
  "page_char_start": 0,
  "page_char_end": 19,
  "token_count": 24,
  "document": {
    "title": "文献标题",
    "authors": ["作者甲"],
    "year": 2023,
    "topics": ["信息检索"],
    "language": "en"
  }
}
~~~

上例偏移与 token 数只示意字段，真实值由程序计算。pdf_page 为从 1 开始的 PDF 文件页序号；printed_page 为可空字符串，不混用。偏移是清洗后规范页面文本的半开区间 [start,end)，必须满足 text == normalized_page_text[start:end]。Chunk 中 document 是检索用元数据快照，由 A 联表生成。chunk_id 在相同文件和切块配置下稳定；配置变更由新的 index_version 区分。本版冻结馆藏后不提供页面清洗在线改写。

**Filters**

~~~json
{"year_from": null, "year_to": null, "topics": []}
~~~

年份范围包含边界；year_from 大于 year_to 时返回校验错误。只接受明示的结构化过滤条件。初版不把问题中的“最近几年”自动转成隐藏年份过滤。

**RetrievalHit**

~~~json
{
  "rank": 1,
  "chunk": {"...": "完整 Chunk 对象"},
  "scores": {"bm25": null, "cosine": 0.71, "rrf": 0.03, "rerank": null},
  "matched_by": ["vector"],
  "index_version": "idx_20261003_001"
}
~~~

rank 从 1 开始；未运行的评分填 null；scores 是排序信息，不是答案可信概率。关键词、向量、混合模式分别为 keyword/vector/hybrid。不同分支的原始分数不直接相加。所有返回片段来自同一有效索引快照。

**AskRequest**

~~~json
{
  "question": "有没有不用准确关键词就能找到论文的方法？",
  "filters": {"year_from": null, "year_to": null, "topics": []},
  "history": []
}
~~~

第一版 history 必须为空；非空返回 UNSUPPORTED_HISTORY，不静默装作支持多轮。确认完成单轮后再协商扩展。

**QueryPlan**

~~~json
{
  "original_query": "用户原问题",
  "intent": "explain",
  "rewritten_query": "保留原意的检索表达",
  "keywords": ["语义检索"],
  "needs_clarification": false,
  "clarification_question": null,
  "clarification_options": []
}
~~~

intent 为 find/explain/compare/clarify。查询改写失败时可回退原问题并记录降级原因；不能虚构澄清选项所对应的馆藏。澄清选择与原问题组合为新的独立请求。

**AnswerResponse**

~~~json
{
  "request_id": "q_001",
  "status": "answered",
  "query_plan": {"...": "完整 QueryPlan 对象"},
  "claims": [
    {"claim_id": "cl_1", "text": "一条可核验的回答结论。", "evidence_ids": ["ev_1"]}
  ],
  "evidence": [
    {
      "evidence_id": "ev_1",
      "chunk_id": "c_012345abcdef_p0003_0001",
      "doc_id": "d_012345abcdef",
      "title": "文献标题",
      "authors": ["作者甲"],
      "year": 2023,
      "pdf_page": 3,
      "printed_page": null,
      "quote": "数据库中的原文。",
      "file_url": "/documents/d_012345abcdef/file#page=3"
    }
  ],
  "related_documents": [{"doc_id": "d_012345abcdef", "title": "文献标题"}],
  "limitations": [],
  "clarification_question": null,
  "clarification_options": [],
  "index_version": "idx_20261003_001",
  "timings_ms": {"planning": 0, "retrieval": 0, "generation": 0, "total": 0},
  "error": null
}
~~~

status 为 answered/needs_clarification/insufficient_evidence/error。answered 的 claims 必须非空且每条有可解析证据；其他状态 claims 为空。无检索时 index_version 允许 null。needs_clarification 必须包含追问；insufficient_evidence 包含原因，可附相关文献；error 包含 {"code": "...", "message": "..."}。全部字段保留，未使用项设为空数组、null 或 0。服务器耗时用毫秒。

证据由 C 从本次选中 Chunk 的数据库或索引快照构造，不信任模型生成的标题、页码、链接和引文。第一版 quote 可以直接取完整 Chunk.text；模型只返回 claim 文本和 chunk_id 列表。合法引用不代表语义正确，语义支持需要人工评估。

**IndexManifest**

字段至少包括 index_version、contract_version、built_at、embedding_model、embedding_revision、dimension、normalized、chunking_config、tokenizer、document_count、chunk_count、corpus_hash。corpus_hash 覆盖规范化文本和检索元数据；元数据修改后也需要重建。built_at 用明确带时区的 ISO 8601 时间。manifest 与文本快照、词项索引、向量一起保存。

### 统一 Python 接口

A 提供 src/dlrag/ingestion/library.py：

~~~python
class LibraryStore:
    def __init__(self, db_path: str, files_dir: str): ...
    def ingest_pdf(self, file_path: str, metadata: dict, options: dict) -> dict: ...
    def list_documents(self, filters: dict | None = None,
                       include_nonready: bool = False) -> list[dict]: ...
    def get_document(self, doc_id: str) -> dict | None: ...
    def list_chunks(self, filters: dict | None = None,
                    include_indexing: bool = False) -> list[dict]: ...
    def get_chunk(self, chunk_id: str) -> dict | None: ...
    def get_file_path(self, doc_id: str) -> str | None: ...
    def set_document_status(self, doc_id: str, status: str,
                            error: dict | None = None) -> None: ...
~~~

A 不调用 B。get_file_path 仅用于受控文件服务，不直接暴露给前端。重复导入相同文件返回现有记录，不新增文本块；相同文件元数据冲突默认保留现有值并提示组员人工处理。

B 提供 src/dlrag/retrieval/retriever.py：

~~~python
class Retriever:
    def __init__(self, index_dir: str, embedding_backend, settings: dict): ...
    def build(self, chunks: list[dict]) -> dict: ...
    def load(self) -> dict: ...
    def search(self, query: str, filters: dict | None = None,
               mode: str = "hybrid", top_k: int = 20) -> list[dict]: ...
    def get_manifest(self) -> dict | None: ...
~~~

embedding_backend.encode(texts: list[str]) 返回 n×d 数值矩阵，可转成 NumPy 数组。B 必须提供实际模型适配器及测试用替身。build 成功返回 IndexManifest；空馆藏可构建零片段清单，search 返回 []。查询和建库使用同一模型与归一化配置。精确搜索先过滤候选子集再取 top_k，不能先取全库 top_k 再过滤造成漏检。

C 提供 src/dlrag/qa/engine.py：

~~~python
class QAEngine:
    def __init__(self, retriever, llm_client, settings: dict): ...
    def ask(self, request: dict) -> dict: ...
~~~

retriever 遵守 B 接口；llm_client.generate_json(system_prompt: str, user_payload: dict) -> dict。C 提供真实服务适配器和 mock 适配器；网络超时、无密钥、非 JSON 输出要明确处理，不在导入模块时发网络请求。

D 将 A、B、C 实例化并注入依赖；C 不直接写库，B 不直接读取 HTTP 请求，A 不依赖 LLM。除可识别的业务状态外，模块失败使用带 code/message 的 ProjectError，定义在各模块边界可识别的异常基类中；D 按异常的 code/message 映射。不要为导入此异常而强制依赖尚未完成的 shared 模块。

### HTTP 规格

| 方法与路径 | 请求 | 成功响应 |
|---|---|---|
| GET /health | 无 | 状态、real/mock、模型是否配置、当前索引版本 |
| POST /documents | multipart：file 和 metadata_json 字符串 | {"document": Document, "index_version": "..."} |
| GET /documents | year_from、year_to、topics 可重复参数 | {"documents": [Document]} |
| GET /documents/{doc_id} | 路径 ID | {"document": Document} |
| GET /documents/{doc_id}/file | 路径 ID | application/pdf |
| GET /chunks/{chunk_id} | 路径 ID | {"chunk": Chunk} |
| POST /search | {"query": "...", "filters": Filters, "mode": "hybrid", "top_k": 20} | {"hits": [RetrievalHit], "documents": [...], "index_version": "..."} |
| POST /ask | AskRequest | AnswerResponse |
| POST /feedback | {"request_id": "...", "rating": "useful", "comment": ""} | {"saved": true} |

POST /documents 采用同步导入与全量重建，适合当前小馆藏。D 先取得包括 indexing 状态的完整候选文本块，B 成功生成新索引后再把新文献设为 ready；文献处理失败不得返回成功。已服务索引在失败时继续可用。构建与查询用锁或快照机制，保证单次请求不会混用版本。为了简化这项要求，第一版采用单进程后端和显式读写互斥，不支持多 worker。

/search 中 documents 按 hits 首次出现顺序聚合文献，每项包含 doc_id/title/authors/year/best_rank/preview；hits 保持片段级。top_k 范围 1–50。question/query 去除首尾空白后不得为空，默认最长 2000 字符。支持的上传文件大小上限默认 25 MB，可配置。

非问答接口统一错误体 {"error": {"code": "...", "message": "..."}}；422 为参数非法，404 为对象不存在，413 为超限，415 为不支持类型，503 为服务未就绪。/ask 的正常 answered、needs_clarification、insufficient_evidence 返回 200；status=error 根据原因返回 422/503/500，仍遵守完整 AnswerResponse。日志不得包含密钥。第一版 GET /health 与管理页面须说明上传入口仅适用于本地可信课堂环境。

### 可独立运行与交付格式

每位成员都必须提供：

1. 自己目录中的真实实现及对应有意义的测试。
2. handoff/<角色>/README.md：做了什么、运行前提、命令、输入输出示例、已知限制、交接事项。
3. handoff/<角色>/requirements.txt：直接依赖及实际验证的版本；不得把未验证版本写成已通过。
4. handoff/<角色>/acceptance.md：验收项目、执行命令、通过/失败/未执行状态、真实结果。
5. 所属 evaluation 目录的实际记录；无真实模型或数据时提供格式和运行入口，标记未执行，不伪造分数。
6. 不依赖其他成员最终成果的最小演示或测试入口。

A、B、C 各提供自己的 python -m dlrag.<模块>.cli ... 入口，并在交接文件给出实际可运行的完整参数。D 在完成打包后提供：
- python -m pip install -e ".[dev]"
- python -m pytest
- python -m dlrag.api.main
- python -m streamlit run src/dlrag/ui/app.py
- python scripts/seed_demo.py
- python scripts/run_evaluation.py --dataset evaluation/dataset/questions.jsonl --mode real

开发期间 A、B、C 可设置 PYTHONPATH=src 运行各自模块，不以缺少 D 的 pyproject.toml 为理由停止。

### 共同验收与测试数据

端到端必测：正常 PDF 导入、重复导入、空文本/坏 PDF、精确搜索、日常表达搜索、年份/主题过滤、引用展开与 PDF 页定位、需要澄清、证据不足、无模型或模型超时、重启加载索引、重建失败保留旧索引。

全组共建约 60 题，每人约 15 题，另一位成员复核。D 汇总为 JSONL，一行一题：

~~~json
{
  "question_id": "t001",
  "split": "test",
  "category": "vague",
  "question": "有没有不用准确关键词就能找到论文的方法？",
  "filters": {"year_from": null, "year_to": null, "topics": []},
  "expected_status": "answered",
  "reference_points": ["指出语义检索并说明作用"],
  "relevant_doc_ids": ["真实馆藏文献 ID"],
  "relevant_chunk_ids": ["真实支持片段 ID"],
  "evidence_groups": [["支持同一要点的可替代片段 ID"]],
  "clarification_expectation": null
}
~~~

category 为 exact/vague/clarify/multi_document/unanswerable。建议数量 10/15/10/15/10；split 为 dev/test。近似改写不得跨集合；只用 dev 调参。片段变化需重新核验标注。多文献题按要点标注 evidence_groups，用于判断证据是否覆盖完整答案。无答案题相关 ID 为空。

报告必须区分：自动结构检查、人工语义核验、真实模型实验与 mock 测试。引用 ID 存在不等于支持结论；相似度不等于正确率。不得为达到指标而修改测试题或伪造证据。

