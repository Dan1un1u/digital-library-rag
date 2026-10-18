# C 查询理解与证据问答交接

> 2026-10-18 v1.0更新：双语检索、预算及证据选择已升级，当前行为与实测以[修改文档](../../docs/changes/v1.0_检索与证据选择优化.md)为准。共同核心字段不变，english_query与get_neighbors是可选扩展。

接收人 D。已实现共同契约 1.0 的 `QAEngine.ask(dict) -> dict`：回答、澄清、证据不足和错误均保留完整公共字段。C 不写数据库、不改变文献状态，不修改 A/B、shared、界面和共同规格。报告见 `report.md`，验收见 `acceptance.md`，评估结果见 `evaluation/qa/analysis.md`。

## 隔离环境与离线运行

所有命令从仓库根目录在 PowerShell 执行。本次使用 Python 3.13.9 的 venv，位置 `handoff/C/.venv`；该环境独立于系统与其他项目，既有 `.gitignore` 排除 `.venv/`。分发源码不要包含环境，D 应重新创建。Python 3.11/3.12 未在本次机器复测。

```powershell
python -m venv handoff/C/.venv
handoff/C/.venv/Scripts/python.exe -m pip install -r handoff/C/requirements.txt
$env:PYTHONPATH='src'
$env:PYTHONUTF8='1'
handoff/C/.venv/Scripts/python.exe -m pytest tests/qa tests/retrieval -q
handoff/C/.venv/Scripts/python.exe -m dlrag.qa.cli demo --scenario answered
handoff/C/.venv/Scripts/python.exe -m dlrag.qa.cli demo --scenario clarify
handoff/C/.venv/Scripts/python.exe -m dlrag.qa.cli demo --scenario empty
handoff/C/.venv/Scripts/python.exe -m dlrag.qa.cli demo --scenario invalid
```

`invalid` 故意返回 `OUTPUT_VALIDATION_FAILED`，退出码为 1；其余演示退出码 0。demo 清晰标记 `mode=mock, synthetic=true`。`FakeRetriever` 与 `ScriptedMockLLM` 位于 C 的 `demo.py`、`llm_client.py`，仅由显式演示或测试使用；实际服务错误不会启用模拟。所有普通测试离线，不在 import、构造适配器或启动时调用网络。

Windows 的 B 既有测试部分依赖默认 UTF-8；`PYTHONUTF8=1` 必须在启动 Python 前设置。B 原锁定 NumPy 1.26.4 不支持本次 Python 3.13 wheel，本环境用 2.2.6，已通过 B 全部回归；D 在统一 Python 版本后合并依赖，不要同时强制两个 NumPy 版本。

## D 装配示例

```python
from dlrag.retrieval import Retriever
from dlrag.retrieval.embeddings import SiliconFlowEmbedding
from dlrag.qa import QAEngine, SiliconFlowLLM

embedding = SiliconFlowEmbedding.from_env()  # B 的配置与索引保持一致
retriever = Retriever('data/indexes', embedding, {})
retriever.load()  # 即使 keyword 也需要适配器身份；不会因此联网
llm = SiliconFlowLLM.from_env()
engine = QAEngine(retriever, llm, {
    'max_output_tokens': llm.max_output_tokens,
    'context_window_tokens': llm.context_window_tokens,
})
response = engine.ask({
    'question': '有没有不用准确关键词就能找到论文的方法？',
    'filters': {'year_from': None, 'year_to': None, 'topics': []},
    'history': [],
})
```

D 应按共同规格将建库与整次 ask 置于应用层同一读写互斥约束下，使用单进程。C 从一次 search 的命中快照构建引文，拒绝混合版本；不会在生成之后重新读当前库来替换证据。非空命中以 hit 版本为准；空命中仅能从 `get_manifest()` 取版本。更严格的空结果版本一致性需要 D 的应用锁。

`diagnostics` 为附加字段，包含规划回退、模型方法调用次数、检索次数、选中编号、选中完整片段、预算计数方式；D 核心响应模型可选择保留扩展字段，不能用这些字段替换契约核心字段。公开响应并不包含 API 密钥。

## 模型配置及数据发送

真实适配器为硅基流动 Chat Completions，使用 requests，JSON object 模式，不使用 SDK。配置从进程读取，D 也可显式传入构造参数。`LLM_API_KEY` 优先于 `SILICONFLOW_API_KEY`；C 不自动读取 `.env`。本目录 `.env.example` 不含可用密钥；用户给定密钥仅用于本次子进程环境，未保存到文件。

| 变量 | 默认值或说明 |
|---|---|
| LLM_BASE_URL | https://api.siliconflow.cn/v1 |
| LLM_MODEL | Qwen/Qwen2.5-7B-Instruct；32B 实验由环境显式指定 |
| LLM_API_KEY | 无默认值；可回退 SILICONFLOW_API_KEY |
| LLM_TIMEOUT_SECONDS | 60，requests 连接/读取超时，不是整个 ask 的总时限 |
| LLM_MAX_OUTPUT_TOKENS | 1000，须与 QA settings 一致 |
| LLM_CONTEXT_WINDOW_TOKENS | 32768，替换模型时由 D 核对服务限制 |

规划只发送问题和必要馆藏范围说明；生成只发送该次问题及选中原文片段；不会上传 PDF、整库或历史会话。只接受 HTTPS，拒绝鉴权重定向。日志不保存密钥、请求头、上游错误正文；API 实验记录只保留模型、耗时、状态、usage。更换模型须明确核对上下文配置，不能把模型名称变化视作已验证。

已按[硅基流动官方接口](https://docs.siliconflow.cn/docs/api/chat-completions-post)验证 `messages`、`max_tokens`、`response_format={"type":"json_object"}` 及 `choices[0].message.content`。默认 7B 的保守 32768 上限参考[模型官方说明](https://huggingface.co/Qwen/Qwen2.5-7B-Instruct)；本实现不会启用模型权重下载。

## 状态和引用映射

模型内部只能返回 `status=answered/insufficient_evidence`，`claims=[{text,evidence_chunk_ids}]`，`limitations=[]`。C 验证所有编号属于本次选中集合；逐项分配 `cl_1`、`ev_1`，重复编号只建一条证据。标题、作者、年份、PDF 文件页、原文 quote 全部取检索快照，忽略模型伪造的页码或引文。`file_url` 为 `/documents/{编码后的doc_id}/file#page={pdf_page}`，D 负责受控文件端点；当前目录没有原 PDF，尚未做浏览器页跳转验收。

| 场景 | status | 主要字段 |
|---|---|---|
| 有有效结论与引用 | answered | 非空 claims、可解析 evidence |
| 真正对象歧义 | needs_clarification | 追问、2–3 个选项；claims/evidence 空 |
| 零命中、预算放不下或证据不覆盖 | insufficient_evidence | limitations 说明原因，claims 空 |
| 缺模型、超时、非法输出等 | error | 完整响应及 error.code/message |

澄清选择与原问题组成新请求发送，`history` 仍为空。模型最多规划一次、回答一次、修复一次，总计三次 generate_json；规划非法或暂时失败直接回退原问题，不做规划修复。回答仅格式/引用不合规可修复一次；第二次失败为 `OUTPUT_VALIDATION_FAILED`，不会删除坏引用伪装成功。真实 HTTP 没有自动重试。缺密钥/鉴权失败为 `MODEL_NOT_CONFIGURED`，超时 `MODEL_TIMEOUT`，连接/限流/服务故障 `MODEL_UNAVAILABLE`。

查询默认 hybrid/top_k=20，过滤条件原样传给 B。改写检索零结果或明确参数拒绝时回退原问题一次；索引损坏或服务故障不会被回退掩盖。非空但不相关由生成判断不足。默认问答将中文与英文查询分别检索并按编号融合。选中至多8块，以本地正文BM25和排名先验重排，参考文献软降权，允许同文献相关片段及相邻块共同入选；这不是神经语义重排模型，也未经正式人工质量评估。

上下文采用 `utf8_byte_upper_bound`：序列化 UTF-8 字节数加 128 framing 预留，明确为保守预算上界，**不是实际 token 计数**。18000 输入预算上界含完整提示、问题、证据及最大修复包络，并预留输出 1000；实际模型更小的上限优先。整块放不下则减少证据，不截断引文。不足证据可能被误拒答，须结合人工评估改善选择策略。

## 真实索引 CLI 与评估

D 恢复 A 馆藏与 B 索引并设置自己的模型密钥后：

```powershell
$env:PYTHONPATH='src'
$env:PYTHONUTF8='1'
$env:LLM_MODEL='Qwen/Qwen2.5-32B-Instruct'
# 密钥由本地进程或 D 的安全配置注入，不写进命令示例。
handoff/C/.venv/Scripts/python.exe -m dlrag.qa.cli ask --index-dir data/indexes --question 'BM25 是什么？'
handoff/C/.venv/Scripts/python.exe -m dlrag.qa.cli ask --index-dir data/indexes --retrieval-mode keyword --question 'BM25 是什么？' --output evaluation/qa/answer.json
handoff/C/.venv/Scripts/python.exe -m dlrag.qa.cli evaluate --index-dir data/indexes --questions handoff/C/candidate_questions.jsonl --output-dir evaluation/qa/runs/live_full
handoff/C/.venv/Scripts/python.exe -m dlrag.qa.cli evaluate --index-dir data/indexes --questions handoff/C/candidate_questions.jsonl --output-dir evaluation/qa/runs/live_baseline --baseline
```

每次实验目录必须为空，避免覆盖旧记录。full 与 baseline 固定题集、模型、证据选择参数、索引；baseline 仅关闭规划，意味着同时关闭改写与澄清。CLI 运行配置与每题响应保存在 runs.jsonl。

本机缺馆藏时可复现已执行的真实 LLM 加 B 检索结果回放（不是实时检索，更不能用它衡量改写的检索增益）：

```powershell
handoff/C/.venv/Scripts/python.exe handoff/C/run_recorded_smoke.py --output-dir evaluation/qa/runs/new_recorded_run
handoff/C/.venv/Scripts/python.exe handoff/C/run_grounded_smoke.py --output-dir evaluation/qa/runs/new_grounded_run
```

`candidate_questions.jsonl` 有 10 道澄清、5 道无答案候选，全为 AI 草案，`usable_for_evaluation=false`，等待 A 逐题复核，D 冻结和汇总。无答案题无相关文献编号；不得补造。真实快照题有 B 的真实编号，但尚需 A 对原 PDF 核验。

人工逐条填写每次实验 `review_template.csv`：`support` 使用 supported/partial/unsupported；`factual_issue` 写事实问题；`reviewer` 必填。每题只在第一行填一次 `point_score/point_max` 和 `coverage`（0–1，要点中有引用支持的比例），包括无 claim 的题。引用支持正确率按 claim–evidence 链接统计，partial 不计为 fully supported。先由另一成员复核题目并设置 usable_for_evaluation=true，再运行正式评估；未审核候选、mock 不计正式分数。

```powershell
handoff/C/.venv/Scripts/python.exe -m dlrag.qa.cli summarize-review --run-dir evaluation/qa/runs/live_full --review evaluation/qa/runs/live_full/review_template.csv --output evaluation/qa/runs/live_full/human_metrics.csv
```

自动表将 dev/test 分开，提供状态、耗时及已审核题的澄清/无答案行为命中；回答要点、引用支持和引用覆盖必须人工填写后聚合。合法引用仅证明可追溯，不能证明语义支持。提示注入测试只证明所测样例的提示边界，不构成全面防御保证。

## D 后续动作

合并 C 依赖与提示词资源，按上方注入实例；保留 B 的 `.gitignore`。实现受控 PDF 文件服务及引用展开；依据完整 `status` 映射 `/ask`：正常三状态 200，参数/非空 history 422，模型与索引未就绪 503，输出验证或内部错误 500。按 error.code 判定，不能仅看 error 键存在，因为成功响应的 error 也是 null。

恢复真实馆藏和完整索引，核验 A 的页内文本顺序；与 A 复核候选题后再冻结正式集。真实模型首轮的误澄清和拒答等结果须保留，不得用通过结构校验替代语义验收。将全文报告、完整实验和已知限制纳入 D 总报告。
