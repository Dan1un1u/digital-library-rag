# C 验收记录

日期：2026 年 10 月 17 日。执行环境 Windows、Python 3.13.9、独立 `handoff/C/.venv`。所有命令从仓库根目录执行，先设置 `$env:PYTHONPATH='src'`、`$env:PYTHONUTF8='1'`。

| 项目 | 命令或证据 | 结果 |
|---|---|---|
| C 与 B 自动测试 | `handoff/C/.venv/Scripts/python.exe -m pytest tests/qa tests/retrieval -q` | 140 passed；最终复核见 evaluation/qa/tests.xml |
| 正常带引用回答 | `python -m dlrag.qa.cli demo --scenario answered` | answered，退出码 0，合成数据明确标识 |
| 澄清 | `python -m dlrag.qa.cli demo --scenario clarify` | needs_clarification，2 选项，不检索 |
| 零结果 | `python -m dlrag.qa.cli demo --scenario empty` | insufficient_evidence，不生成 |
| 非法引用两次 | `python -m dlrag.qa.cli demo --scenario invalid` | error/OUTPUT_VALIDATION_FAILED，退出码 1 |
| 单轮限制、过滤、错误映射 | tests/qa/test_engine.py | 通过，非空 history 返回 UNSUPPORTED_HISTORY |
| 真实 HTTP 适配器故障分支 | tests/qa/test_llm_client.py | 通过；缺密钥、401/403、限流、超时、重定向、非法 JSON、截断 |
| B 构建、重载、C 对接 | test_b_retriever_build_reload_and_qa | 通过；B 真实现，合成语料及显式 fake embedding，关键词检索 |
| 版本与引用来源 | test_mixed_versions_rejected_and_hit_version_beats_new_manifest | 通过，拒绝混合版本；引文来自 hit 快照 |
| 数据提示注入边界 | test_prompt_injection_is_evidence_data_and_policy_is_system | 通过所测样例；不宣称全面攻击防御 |
| 语义反例 | test_legal_reference_does_not_prove_semantics | 通过预期：结构合法仍可能不受证据支持，等待人工核查 |
| 实验保存与人工计分门禁 | tests/qa/test_evaluation.py | 通过；mock/未审核不计正式成绩，缺失复核拒绝聚合 |
| 真实 7B 开发回放 | `python handoff/C/run_recorded_smoke.py --output-dir evaluation/qa/runs/20261017_real_recorded` | 已执行 full/baseline 各 4；包含误澄清，保留原结果 |
| 真实 32B 开发回放 | 同上，LLM_MODEL=Qwen/Qwen2.5-32B-Instruct，输出 20261017_real_recorded_32b | 已执行 full/baseline 各 4；存在规划回退和证据不足 |
| 真实直接支持问答 | `python handoff/C/run_grounded_smoke.py --output-dir evaluation/qa/runs/20261017_real_grounded_32b` | answered，2 claims，引用 B 的 Sentence-BERT 摘要；2 次 HTTP 调用 |
| 15 道候选题 | handoff/C/candidate_questions.jsonl | 已交付；10 clarify、5 unanswerable，全部待 A 复核，不计分 |
| 真实馆藏 live hybrid 与 PDF 页跳转 | D 恢复 A PDF、数据库和 B 完整索引后运行 README 命令 | 未执行：本机未交付这些运行数据 |
| 正式冻结题集与人工语义成绩 | 每个 run 的 review_template.csv | 未执行：需另一成员人工评审；指标未伪造 |
| Python 3.11/3.12 | D 统一环境后复测 | 本次未执行 |

CLI 四状态原始记录在 `evaluation/qa/cli_smoke.json`。真实回放、固定证据与 mock 分目录保存；每次运行输出目录必须为空，表中已存在目录不能直接重复使用，应换新目录名。

首次测试发现 pytest 参数名 request 被保留，已改为 ask_request；B 接口重载需要匹配适配器身份，已修正 C 对接；Windows 默认 GBK 导致 B 测试读写差异，通过设置进程 PYTHONUTF8=1 解决，未修改 B。后续请求探测曾有 MODEL_UNAVAILABLE，如实记录为调试故障，不以模拟替代。
