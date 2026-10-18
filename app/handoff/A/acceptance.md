# A 验收记录

日期：2026-10-12（Asia/Shanghai）。契约：1.0。

实际环境：Python 3.13.5；PyMuPDF 1.27.2.2；tiktoken 0.14.0；pytest 8.3.4。Python 3.11 未实测。本次 tiktoken 安装在 /private/tmp/lib-management-a-deps，编码缓存位于 /private/tmp/lib-management-tiktoken，未修改系统环境。

## 模块测试：通过

实际执行：

```sh
PYTHONPATH=src:/private/tmp/lib-management-a-deps TIKTOKEN_CACHE_DIR=/private/tmp/lib-management-tiktoken /opt/anaconda3/bin/python3 -m pytest tests/ingestion -q
```

结果：22 passed，耗时 0.75 秒。PyMuPDF 的 SWIG 类型产生 5 个弃用警告，没有测试失败。

| 项目 | 状态 | 真实验证内容 |
|---|---|---|
| 正常 PDF | 通过 | PyMuPDF 生成文本 PDF 后实际解析，多页内容入库 |
| 重复导入 | 通过 | 文献与 Chunk 不增长，元数据冲突保留旧值 |
| 损坏/加密 PDF | 通过 | INVALID_PDF、failed、错误原因，无半成品块 |
| 空文本/扫描 PDF | 通过 | NO_EXTRACTABLE_TEXT；混合馆藏页诊断 EMPTY_PAGE |
| 页码与原文 | 通过 | 每块的页面、Python 半开偏移严格对应规范页文本 |
| 字符切块 | 通过 | 最大长度、强制拆分重叠、中文、稳定块 ID |
| 真 token 切块 | 通过 | cl100k_base 实际计数、中文/emoji、token 上限 |
| 页边界/段落 | 通过 | 不跨页，短页保留，优先段落边界 |
| 页眉页脚 | 通过 | 重复页边缘文本去除，raw_text 保留 |
| 双栏 | 通过 | 位置块标记待人工复核，不宣称语义顺序正确 |
| 过滤 | 通过 | 年份含边界、空年份排除、主题交集、状态过滤 |
| 重启/迁移 | 通过 | 重新连接 SQLite；复制整个目录后原文件定位正常 |
| 外键/事务 | 通过 | 外键检查无异常；中途唯一约束失败整批回滚 |
| 文件路径 | 通过 | 受控文件名、相对路径，拒绝目录逃逸 |
| 失败重试 | 通过 | 失败不冒充重复成功；修正模式后显式重试成功 |
| 参数变动 | 通过 | 重复导入及跨文献配置不一致均被拒绝 |
| 批量 CLI | 通过 | 正常项与缺文件项独立处理，失败退出码为 1 |
| 离线重建 | 通过 | 拒绝覆盖既存库，新库成功构建 |
| 报表与题目 | 通过 | CSV 自动/人工状态分离，15 模板不虚构证据 ID |

## 独立批量演示：通过

```sh
/opt/anaconda3/bin/python3 tests/ingestion/synthetic.py --output tests/ingestion/samples
PYTHONPATH=src /opt/anaconda3/bin/python3 -m dlrag.ingestion.cli batch --db /private/tmp/lib-management-a-demo/library.sqlite --files /private/tmp/lib-management-a-demo/raw --manifest tests/ingestion/samples/manifest.json --options handoff/A/chunking_character.json
PYTHONPATH=src /opt/anaconda3/bin/python3 -m dlrag.ingestion.cli report --db /private/tmp/lib-management-a-demo/library.sqlite --files /private/tmp/lib-management-a-demo/raw --output evaluation/ingestion
PYTHONPATH=src /opt/anaconda3/bin/python3 -m dlrag.ingestion.cli questions --db /private/tmp/lib-management-a-demo/library.sqlite --files /private/tmp/lib-management-a-demo/raw --output handoff/A/candidate_questions.jsonl
PYTHONPATH=src:/private/tmp/lib-management-a-deps TIKTOKEN_CACHE_DIR=/private/tmp/lib-management-tiktoken /opt/anaconda3/bin/python3 -m dlrag.ingestion.cli batch --db /private/tmp/lib-management-a-token/library.sqlite --files /private/tmp/lib-management-a-token/raw --manifest tests/ingestion/samples/manifest.json --options handoff/A/chunking_token.json
```

字符模式：3 篇合成 PDF、4 页、7 块，最长 1192 字符。token 模式：同样 3 篇、6 块，最长 397 tokens。结果位于 evaluation/ingestion/synthetic_import.json 与 synthetic_token_import.json，CSV 为字符模式快照。所有导入成功文献均保持 indexing。

## 尚未执行的真实工作

- 真实馆藏尚未提供，未做 10 篇人工抽查或 50–100 篇真实批处理。
- 正文顺序、真实页眉清洗和双栏质量尚未人工验收，CSV 保留 pending_human_review。
- 15 道候选题为模板，真实参考要点、文献 ID、片段 ID、证据组与 C 复核待完成；usable_for_evaluation=false。
- B/D 模块尚未存在，验证接口数据及接入说明，未执行真实 B/D 集成。

这份记录证明 A 模块实现与合成资料功能验收，不代表真实论文解析质量或问答效果评估。

## 后续真实论文实验（2026-10-12）：通过

根据用户要求，从 arXiv 下载 10 篇论文实际试验。最终 10/10 成功、156 页、732 块；偏移切片及重复导入检查全部通过。完整来源与结果见 evaluation/ingestion/arxiv_trial。

真实 PDF 暴露空字符导致 SQLite 长度校验失败的问题，parser v2 已修复并增加回归测试。模块测试现为 23 passed（0.89 秒）。此前“真实馆藏尚未提供”的记录为历史状态；现在完成了 10 篇真实资料的自动实验，人工双栏正文复核、50–100 篇扩展、候选题标注及 C 复核仍未执行。
