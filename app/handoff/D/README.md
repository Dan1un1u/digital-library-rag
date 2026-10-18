# D 集成交接与当前部署说明

> 后续功能更新：已增加PDF本地元数据识别、预填和确认入库，新预览接口不写库；最新全量测试233项通过（19项新增）。见[识别与切分说明](../../docs/pdf_import.md)。下文214项为前一轮部署合并验收记录。

更新日期：2026-10-18，Asia/Shanghai。已将用户提供的 `lib_management_D_v2_20261017.zip` 合并进当前项目；A/B/C/D 全部代码到齐。根 README 是本机安装、mock/real 切换及启动的现行说明；逐项完成度见 [需求核验报告](../../evaluation/reports/update_20261018/requirements_review.md)。

## 合并与修复

压缩包 194 个文件：新增 90、差异 7、相同 97。新增文件全部合入；README 和 .gitignore 更新，五份共同规格仅多尾部空行，保留原文件。B/C 核心文件与包内完全一致。差异与合并清单在 evaluation/reports/update_20261018，覆盖前文件备份在 data/update_20261018/before_update.zip。

保留了 `.venv/` 等原有忽略规则，防止 C 的嵌套环境被纳入源码。全工程独立环境使用 Python 3.12.15；pyproject 明确支持 3.11–3.12，避免 NumPy 1.26.4 在 3.13 上安装失败。新增统一 LLM_MAX_OUTPUT_TOKENS/LLM_CONTEXT_WINDOW_TOKENS 并传到 C；seed_real 输出建库后的 ready 状态；评估 provenance 改为当前源码文件哈希，移除写死的旧提交说明。

## 模块与配置

A 提供 LibraryStore，B 提供 Retriever、硅基流动 BGE-M3 和显式 FakeHashEmbedding，C 提供 QAEngine、SiliconFlowLLM、ScriptedMockLLM。D 管理实例、单进程 RLock、上传临时文件、建库后状态与边界校验。mock 明确使用 D 的 ScriptedQA，只用于流程展示；real 使用 C，不自动降级。

`.env.example` 已设置工厂 `LLM_CLIENT_FACTORY=dlrag.api.qa_factory:create_client`。生成密钥优先 LLM_API_KEY，其次 SILICONFLOW_API_KEY；B 的嵌入配置与索引身份必须一致。LLM 超时60秒为每次连接/读取超时，整次请求可能包含规划、生成和一次修复。C 与客户端输出/上下文预算保持一致。

本机 `.env` 为不含密钥的 mock 配置。为验证而使用的密钥仅存在于子进程环境；切换 real 请自行注入自己的密钥。数据目录分为 data/mock 与 data/real_arxiv。A/B/C 实例只构造一次；不启用多 worker，不让离线 CLI 和后端同时写同一库。

## 当前验证与交接重点

214 项自动测试通过，包含 A/B/C、API、Streamlit AppTest、失败保留旧索引、重启、引用映射及新配置回归。实际启动 API/UI，四状态、原文和 PDF 返回已核对。十篇论文真实建库成功，732 块；本次真实开发问答的响应和引用检查保存在 real_smoke.json。D 包内 2026-10-17 的历史联调记录继续保留，不能当成本机新成绩。

候选题现已合并 60 道：A/B/C/D 各 15，dev/test 候选分配为44/16。全部未完成签名复核和冻结；collect 不替代去近义重复或事实检查。real 评分入口按预期拒绝未审核 A001。质量成绩继续留空。

本地管理扩展为 GET /documents?include_nonready=true；原公开默认 ready。按明确 status 判断 /ask：三种正常业务状态200，非法参数/非空history422，缺模型/超时/索引未就绪503，输出验证/内部错误500。不能因为 error 键存在就判断失败，成功响应 error=null。

剩余工作是 A↔C/B↔D 人工标注、语义支持评审、正文阅读顺序核查、冻结后正式三模式及规划对比、浏览器实际 PDF 页跳转与课堂排练；50–100篇扩充尚未执行。OCR、连续会话、重排序和原页高亮为当前范围外或可选项。

## 历史记录

history/README_20261016.md、history/acceptance_20261016.md 保留初版 D 说明；integration_c_20261017.md 保留随后联调结果。当前安装清单和测试以 evaluation/reports/update_20261018 为准，不能沿用旧文档中的“C缺失”“45题”“149项测试”作为当前状态。
