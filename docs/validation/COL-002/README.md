# COL-002：社科与人文各 25 篇的独立 dev 添加检测

检测日期：2026-10-19（Asia/Hong_Kong）。工作项：[COL-002](../../work-items/COL-002.md)。沿用 Draft PR #1，暂不合并。

**本次独立检测已执行完成，结果包含未通过项。** 独立 dev 库实际加入社会科学 25 篇、人文 25 篇，共 892 个 PDF 物理页、3,262 个片段。正式实例仍为 25 篇、1,821 个片段，索引和馆藏快照未变。本次未修改被测业务逻辑，也未将修复候选部署到正式实例。

离线回归 450 项通过；真实题名检索 150 次中 148 次命中、2 次纯向量检索未命中。另确认两项正文入库质量问题，登记一项日期口径改进和一项检索观察。不能将本轮称为“全部通过”或用户人工验收完成。

后续独立修复阶段：ING-001已形成候选并在新dev库验证，最新完整回归468项通过，详见[ING-001修复报告](ING-001/README.md)。对这50份入库文件重扫还发现SS14同类正文缺失，已保留证据；原50篇库及以上历史450/150次结果不回写，ING-002/MQ-005/RET-001仍开放。

## 1. 样本及获取

完整 50 篇及链接见[入选清单](selection.md)，机器可读清单见 [catalog.json](catalog.json)。采用目的抽样，兼顾经典地位、学科与方法覆盖，以及当前全文可获取性；不声称是引用量排名前 25。社科覆盖经济、社会、心理、政治、教育、传播，人文覆盖哲学、文学理论、史学、数字人文。目前均为英文版本，符合中英文不限的约定。

清单逐项记录来源、最终下载 URL、原件 SHA256、物理页数、参考作者及顺序、原作年和所供版本年、入选理由。译本、章节、工作论文和重印均按所供文件登记；HU16 的所供 Eliot 重印本是 1982 年，原作 1919 年不替代版本年。HU11、HU12、HU13 尚不能确认所供副本的具体版本年，保持空值。

[获取记录](acquisition.json)列出最终下载回执投影、四次初选替换及两份未采用文件。SS11 未采用的 71 页扫描版、SS14 的一页档案目录及 HU20 首次方向处理不佳的 OCR 派生文件均在本地保留。最早的临时下载脚本没有完整保存每次失败重试，不能将现有回执描述为完整的不可变采集日志。文献可公开访问，不自动等于具备再分发授权；原 PDF 和 OCR 副本不提交 Git。

## 2. 环境及版本冻结

| 项目 | 实际使用与边界 |
| --- | --- |
| 正式库 | API `18000` / UI `18501`；25 篇、1,821 片段；本次前后快照相同 |
| dev 库 | API `19000` / UI `19501`；独立进程、数据库、原文存储和索引，页面显示 DEV 标记 |
| 被测业务及 50 次预览、实际导入 | 干净提交 `20ec245051a783e55701ae4001418c45a93b6e8e`；包含 MQ-003/MQ-004 候选 |
| 三个原 PDF 的可移植负例复现工具 | 干净提交 `da0fdc126d89f601a6581b2e106c226d9918bd45` |
| 最终验证器及 450 项离线回归 | 干净提交 `fc60a065056195297bada598b6746ad3c84be34a` |
| 业务源码关系 | 上述提交间 `app/src/dlrag` 无改动；验证器核对差异，后端标记返回实际载入的 `20ec245` |
| 增强识别与书目补全 | 本机 CLIProxyAPI 的 `gpt-6-luna`；显式开启 Crossref 补全 |
| 真实索引 | 本机 BGE-M3 FP16，1024 维，revision `5617a9f61b028005a4858fdac845db406aefb181` |
| dev 最终索引 | `idx_20261019T024947_292c353a8ff5` |

存储保护拒绝正式数据目录及其祖先/子目录，预览器和 UI 要求 dev 标记，避免误连正式实例。[环境记录](environment-check.json)保留正式前后快照摘要、dev 最终快照与后端身份。初始空库及导入后分别做一致性备份，SQLite integrity 为正常；仅提交[备份清单](backup-manifest.json)和[导入后清单](post-import-backup-manifest.json)，实际备份留本地。

## 3. 原件预览、外部预处理及编目

### 3.1 先保存系统原始输出

50 份**原 PDF**均先通过真实增强预览接口，上传文件名仅使用 SS/HU 编号，不向识别输入注入题名。50 次模型调用均为 `completed`，任务均完成。预览前后 dev 库均为空，正式馆藏快照也未变。

[系统输出](metadata-system-results.json)保存字段、出处、年份审核和 Crossref 候选；长 PDF 摘录仅保留哈希，原始完整回执留本地。[统计](metadata-metrics.json)先于外部编目，不能用最终库的补值倒算系统能力。

| 指标 | 原系统预览结果 |
| --- | --- |
| 题名 / 作者非空 | 各 50/50 |
| 页面年份校验后、外部查询前的 year 非空 | 5/50 |
| Crossref 后 year 非空 | 26/50（52%），新增 21 个 |
| 查询前 / 后 source_url 非空 | 3/50 → 24/50（48%），新增 21 个 |
| Crossref 状态 | completed 23、no_match 24、ambiguous 2、not_needed 1 |
| 47 篇参考版本年明确的比较 | 与参考一致 25、留空 21、日期口径差异 1（HU25） |
| 三篇版本年未确认 | HU11、HU12、HU13；不以原作年代填 |

题名规范化完全一致 49 篇；SS19 的系统题名额外包含正确的正式副标题，最终编目保留它，不登记为错误。作者及顺序规范化比较为 50/50 一致，其中一项最终编目存在格式差异。**参考书目由编码助手作外部 AI 辅助整理，并非独立人工金标准，因此不报告人工准确率 100%。** 无匹配、歧义和缺证据留空分别登记，不把每个空值都算缺陷。HU19 的 John/Anne Tedeschi 是译者，不追加为 Carlo Ginzburg 的共同作者。

### 3.2 外部 OCR 和编目不得混入算法效果

原文件不变，在应用之外用 Windows 英文 OCR 为 15 篇、278 页制作透明文字层副本，保存原件/派生双哈希、处理页、逐页字符和图像情况；见[预处理记录](preparation.json)。HU20 横置双页先明确旋转 270 度，再校验派生渲染与声明旋转后的原件一致。首次方向不佳的派生副本没有冒充最终输入，也没有登记为应用业务修复。OCR 文字质量尚未获得用户逐页人工复核。

原系统输出冻结后，编码助手在应用之外核对与修订，见 [metadata-review.json](metadata-review.json)：最终 year 非空 47、source_url 非空 50。22 处 year 调整中，21 处是补空，1 处是 HU25 的卷期年选择；26 处来源调整、14 处题名和1处作者格式调整均有前后值。此步骤不等于程序已自动完成，也不等于用户人工审核。

HU08 原件保留乱码文字层，作为已标注的正文负例实际入 dev 库，topics 包含“正文待核对”；因此 50 篇 ready 不代表 50 篇正文质量合格。SS06 实际批量入库使用外部 OCR 副本，其原件问题另行复现，不将预处理绕过算作应用修复。

## 4. 实际入库及验证结果

冻结计划 SHA256：`7244ce487d8f22ad6fc464a524ae777a20934c31aa0c12ea05f1e4019fca3e63`。50 个任务通过实际 DocumentJobs 与真实 BGE 服务导入独立 dev 库，0 → 50 篇、0 → 3,262 片段，集合增量符合计划。[计划](import-plan.json)、[回执](import-receipt.json)、[事件链](import-events.jsonl)分别保存；事件链末端为 `a51a8779e7f8fed8fc6f0db29986d877115c217acdb5281b53b101978d97dacf`。自动导入耗时 752.81 秒，不算人工工时。

| 检查 | 结果及解释 |
| --- | --- |
| 最新离线回归 | **450 passed**，0 失败、错误、跳过、预期失败；本 PR 120 新增 + 330 基线复用；不调用真实模型 |
| 50 篇文件身份和编目 | SHA、文献集合、字段语义相符，作者顺序严格比较；topics 按集合比较 |
| SQLite / 892 个物理页 / 3,262 个片段 | integrity、片段页码、文本偏移、长度及计数核对通过 |
| 题名关键词检索 top 5 | 50/50 命中目标文献 |
| 题名纯向量检索 top 5 | **48/50**；HU08、HU11 未命中 |
| 题名混合检索 top 5 | 50/50 命中目标文献 |
| 原文来源页端点 | 50/50 返回可用 HTML；并非逐页人工阅读验证 |
| SS01 重复导入 | already_present；dev 完整快照、索引及数量均不变，正式库不变 |
| Streamlit AppTest | 使用真实 dev API，无异常，存在 DEV 提示，显示 50 篇；不是人工点击录屏 |

[verification.json](verification.json)如实保留 `integrity_passed=true`、`smoke_all_passed=false`、`passed=false`；验证器完成全部 150 次后退出 1，失败并未被吞掉。[额外 top 20 诊断](retrieval-diagnostic.json)中 HU08 仍未命中，HU11 目标片段排在 14/15/16/19；扩大范围不能改写原 top 5 的失败。题名冒烟只验证特定路径，不代表一般检索、问答或人类阅读效果。

首轮验证器将 topics 的排序差异当成元数据错误，尚未进入检索即停止。确认仅为标签集合排序后，在 `fc60a06` 修正比较器，并新增两项测试保证作者顺序仍严格比较。[首次停止记录](verifier-attempt-01.json)及导入回执原始差异保留。此项属于测试工具修正，不计产品业务修复；首次 448 项和最终 450 项摘要[分别保留](offline-initial-summary.json)、[不回写](offline-final-summary.json)。

## 5. 新发现及范围

| ID | 发现 | 当前状态 |
| --- | --- | --- |
| ING-001 | SS06 原件 21 页仅封面可提取；20 页已有 SCANNED_PAGE_NO_OCR，但任务仍 done、文献 ready，仅1页产生2片段 | 已确认并可复现；正文覆盖未纳入就绪判断，**未修复** |
| ING-002 | HU08 视觉正文正常，文字层乱码；16页66片段仍 ready，真实向量检索未命中 | 已确认并可复现；正文可读性未得到保障，**未修复** |
| MQ-005 | HU25 PDF 卷期年2009，Crossref published-online为2010-03-20；补全2010后未将二者的口径差异汇总提示 | 日期口径/跨来源提示**改进项**；不判定2010虚构，未改业务规则 |
| RET-001 | HU08、HU11 题名向量 top5 未命中；HU11 正文正常，top20才找到 | 保留检索观察，需后续检索评测和归因，尚未修复 |

详细原因、复现及修复建议见 [findings.md](findings.md)。纯扫描 SS04 返回 NO_EXTRACTABLE_TEXT，是应用缺少全文 OCR 的已知边界，不重复计为新缺陷。以上正文发现单独归入 ING，不恢复 MQ-001/MQ-002 范围外的本机作者候选。MQ-003/MQ-004 的历史证据仍保留；本轮不把原作年、重印年、注册上线年混作单一正确答案。

## 6. 本机产物、复现与人工边界

本次实际文件位于 `D:/llm_exp/digital-library/workspace/validation/COL-002-20261019/`：原50 PDF在 `pdfs/`，15个派生副本与处理清单在 `derived/`，dev 数据在 `library/`，完整本机批次输入为 `input.json`、冻结计划为 `plan.json`。原始预览、回执及验证运行记录另存仓库忽略的 `reports/COL-002/`。机密配置只在原部署目录，不复制进证据。

当前界面：[dev 图书馆](http://127.0.0.1:19501/)。复现时先核对对应提交，使用新的输出目录及隔离库；现有 50 篇库用于展示与只读检查，不能用作“空库首次添加”的替代。以下在仓库根目录的 PowerShell 执行；`$privateEnv` 指向本机已有私有配置文件，命令不输出其内容。

```powershell
$trial = 'D:/llm_exp/digital-library/workspace/validation/COL-002-20261019'
$privateEnv = 'D:/llm_exp/digital-library/workspace/deployments/lib_management_v1_20261018/app/.env'
$frozenBusinessCommit = '20ec245051a783e55701ae4001418c45a93b6e8e'

# 确认端口空闲后启动已有 dev 库；首次空库才显式加 --initialize-empty-index。
& ./.venv/Scripts/python.exe -X utf8 tools/serve_validation_library.py `
  --env-file $privateEnv --data-dir "$trial/library" --port 19000

# 在另一个终端查看 dev 界面。
& ./.venv/Scripts/python.exe -X utf8 -m streamlit run tools/validation_ui.py `
  --server.port 19501 --server.address 127.0.0.1

# 仅在与原后端业务代码相符时复现只读检查；输出必须是新文件。
$backendCommit = (Invoke-RestMethod http://127.0.0.1:19000/validation/environment).code.commit
& ./.venv/Scripts/python.exe -X utf8 tools/verify_domain_trial.py `
  --run-dir reports/COL-002/import-01 --data-dir "$trial/library" `
  --review "$trial/metadata-review.json" --catalog docs/validation/COL-002/catalog.json `
  --expected-backend-commit $backendCommit --output reports/COL-002/verification-new.json

# 用全新隔离目录复现原件负例；解析真实PDF，向量为mock，不进行真实检索效果评价。
& ./.venv/Scripts/python.exe -X utf8 tools/check_domain_fulltext.py `
  --catalog docs/validation/COL-002/catalog.json --pdf-dir "$trial/pdfs" `
  --data-dir runtime/COL-002-negative-new --expected-app-commit $frozenBusinessCommit `
  --output reports/COL-002/negative-new.json

# 离线回归单独执行；不以它代替真实批次检测。
& ./.venv/Scripts/python.exe -X utf8 scripts/run_catalog_checks.py `
  --scope all --work-item COL-002 --output reports/COL-002/offline-new
```

已有服务运行时无需重复启动。重新启动会记录当时干净提交的身份，可能不同于本轮原进程的 `20ec245`；新验证记录须保留实际身份，不修改旧回执。只读验证器同时检查本次载入版本与当前工具版本间业务源码无差异。

首次预览工具为 `tools/preview_domain_trial.py`，冻结计划/实际添加工具为 `tools/catalog_batch.py plan/apply`；按 `--help` 传入原始 PDF 清单及本机批次输入，必须明确 `--api http://127.0.0.1:19000`、新输出位置、冻结 `--plan` 和已完成的 `--backup-ref`。完整PDF、数据及私有配置不在Git中，克隆源码本身不能重现真实实验。

本轮没有用户人工验收反馈。此前 COL-001 的三项人工抽查不能外推到这 50 篇；正文阅读顺序、OCR文字正确性、版本年份及检索相关性仍待人工复核。本轮成果与工作量见[贡献台账](contributions.md)。[证据清单](evidence-manifest.json)绑定便携记录及本机原始产物哈希，是内容校验而非数字签名。正式推广、演示视频制作和 PR 合并均不属于本次已完成事项。
