# D 当前集成验收记录

> 后续功能更新：已增加PDF本地元数据识别、预填和确认入库，新预览接口不写库；最新全量测试233项通过（19项新增）。见[识别与切分说明](../../docs/pdf_import.md)。下文214项为前一轮部署合并验收记录。

更新日期：2026-10-18，Asia/Shanghai。本机独立Python3.12.15环境，依据用户提供的D v2部署包合并后复测。最新逐项需求矩阵、命令和缺口见 [部署更新与需求核验](../../evaluation/reports/update_20261018/requirements_review.md)。

| 验收项 | 本次结果 | 证据 |
|---|---|---|
| 源码合并与备份 | 完成，92文件合入，五份纯尾空行差异保留 | archive_comparison.json、merge_manifest.json；data/update_20261018/before_update.zip |
| A/B/C/D装配 | 完成，real为dlrag.qa.engine.QAEngine，mock明确为D脚本 | real_smoke.json、startup_smoke.json |
| 安装与依赖 | 通过，Python3.12.15，pip check无冲突 | requirements-lock.txt、environment_current.json |
| 全量自动测试 | 214 passed，2 warnings，14.43秒 | tests.xml |
| mock seed与重建 | 通过，2篇合成资料、3块，旧版保留 | data/mock，startup_smoke.json |
| 后端和界面实际启动 | 8000/8501返回200，核验后已停止 | startup_smoke.json |
| mock四状态 | answered/needs_clarification/insufficient_evidence/error | startup_smoke.json；timeout为503 |
| 真实馆藏恢复 | 10/10文件哈希与A历史一致 | corpus_integrity.json |
| 真实建库 | 10篇ready、732块、bge-m3/1024维 | real_seed.json |
| 真实三模式 | keyword/vector/hybrid均200，各5条 | real_smoke.json |
| 真实问答与引用 | 两题answered，原文/文献/PDF页一致，原文件200 | real_smoke.json |
| 真实歧义澄清 | 未通过开发样例；规划校验失败回退后返回不足 | “那个系统怎么样？” |
| 真实比较问题 | 本次返回不足，尚未形成有双方支持的比较 | real_comparison_smoke.json |
| 60候选汇总 | 完成，四组各15，dev44/test16 | evaluation/dataset/questions.jsonl |
| mock60题工具 | 通过，接口错误0，质量指标null | evaluation_runs/mock |
| 冻结后的正式真实评估 | 未执行；未审核题A001被按预期拒绝 | evaluation_runs/real/*/not_executed.json |
| 人工语义/正文顺序/来源核验 | 未完成，不冒充人工签名 | requirements_review.md |
| 实际浏览器PDF页定位 | 未人工验收，界面提供页号与文件 | browser_pdf_page_navigation_verified=false |

本表中的JSON/XML和环境文件位于 evaluation/reports/update_20261018。D原2026-10-16验收原文保存在history/acceptance_20261016.md，2026-10-17联调原记录保存在integration_c_20261017.md；它们不是本机新执行结果。当前没有创建Git提交、推送、PR或公网部署。
