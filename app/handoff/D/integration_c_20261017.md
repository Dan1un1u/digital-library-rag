# D 联调记录：C 接入（2026-10-17，macOS / Python 3.11.15）

## 本轮完成
- 合并 C（来自 lib_management.zip）：`src/dlrag/qa/`、`tests/qa/`、`handoff/C/`、`evaluation/qa/` 原样放入；未修改 C 代码。A/B 与 GitHub 仓库版本逐字节一致，未改动。
- 新增 D 装配工厂 `src/dlrag/api/qa_factory.py:create_client`：Settings → C 的 `SiliconFlowLLM`（LLM_API_KEY 为空时回退 SILICONFLOW_API_KEY）。`.env.example` 已填 `LLM_CLIENT_FACTORY=dlrag.api.qa_factory:create_client`。
- `services.assemble`：QAEngine 的 `max_output_tokens/context_window_tokens` 取自客户端（C 要求二者一致）；缺配置/工厂失败时在 /health issues 写明具体原因；health 增加 `active_models.qa_engine`。
- 新增 `scripts/seed_real.py`：按 manifest.json 批量经 A 入库，B 一次性建真实索引。
- 新增 `tests/integration/test_c_integration.py`（5 项）：真实 A/B + C QAEngine + 脚本化 LLM 走 HTTP，覆盖 answered（引用→/chunks 原文一致、PDF 200）、澄清、伪造引用→500 OUTPUT_VALIDATION_FAILED、证据不足、超时→503、real 装配用 C 引擎且不泄露密钥。
- 依赖：保持 NumPy 1.26.4（Python 3.11 有 wheel），C 的 requests==2.34.2、pytest==8.3.4 与 D 一致，无需新增。

## 实际执行
```
uv venv -p 3.11 .venv && uv pip install -e ".[dev]"
python -m pytest -q                                  → 210 passed（A/B 107 + D 42 + C 56 + 联调 5）
python evaluation/ingestion/arxiv_trial/download.py --output data/arxiv_src
DATA_DIR=data/real_arxiv python scripts/seed_real.py --source data/arxiv_src
  → 10/10 入库，idx_20261017T105453_bcd3e56aa64f，BAAI/bge-m3，1024 维，732 块
python -m dlrag.api.main  +  streamlit run src/dlrag/ui/app.py
  → /health status=ready mode=real，issues=[]；UI 8501 返回 200
```

## 真实端到端（real：A 解析 + B bge-m3 hybrid + C Qwen2.5-32B-Instruct）
| 问题 | 状态 | 耗时 | 备注 |
|---|---|---|---|
| 有没有不用准确关键词也能找到论文的方法？ | answered | 7.5 s | 引用 BEIR p3，原文可展开，PDF 200 |
| What is dense passage retrieval and how does it compare to BM25? | insufficient_evidence | 6.8 s | 证据已选中 DPR p6 等 4 块，但模型判为不足 → **疑似误拒答** |
| 那个系统怎么样？ | insufficient_evidence | 5.6 s | 规划输出未过校验，回退原问题；**未触发澄清** |
| 这些论文里有没有讲量子计算机的硬件实现？ | insufficient_evidence | 4.4 s | 正确拒答 |

Streamlit AppTest 连真实后端：提问→结论→点击 [1] 查看原文→馆藏页→管理页，均无异常。

## 遗留
- C 侧：英文定义/对比类问题误拒答；指代不明问题规划校验失败未能澄清（需 C 看 prompt/validate_plan）。
- 45+15 题人工复核、冻结 dev/test 后再跑 `run_evaluation.py --mode real` 与 C 的 `qa.cli evaluate`（full vs baseline）。
- 浏览器 #page 跳转人工验收、课堂排练。
