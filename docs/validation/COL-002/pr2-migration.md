# PR2：ING内容迁移与测试隔离

2026-10-19用户要求PR1只留MQ，本轮ING迁到PR2，后续测试任务不得混杂。

## 差异边界

- PR1：`feat/catalog-ingestion-audit` → `main`，保留MQ-003/MQ-004、COL-001基础、原440项测试与历史验证。
- PR2：`feat/ing-001-fulltext-gate` → `feat/catalog-ingestion-audit`，增加ING-001和所需COL-002测试语料/工具/证据。它是依赖PR，继承MQ公共基础，相对base不再次提交MQ修复。
- PR2移除对COL-001元数据台账的跨任务追加；MQ-005仅保留在原COL-002观察资料中，不在PR2实施修复。ING-002、RET-001同样继续开放。

PR1采用反向提交`b0e3e8d`移出7个混入提交，源文件恢复至MQ阶段`5273c33`；只增加用户要求的隔离规则。PR2从清理后PR1起步，用`cherry-pick -x`保留来源地重放：

| 原提交 | PR2重放提交 | 内容 |
| --- | --- | --- |
| 20ec245 | 776493d | COL-002数据与独立dev工具 |
| da0fdc1 | e48da76 | 完整验证、原件负例与UI入口 |
| fc60a06 | 65833eb | topics集合比较，保护作者顺序 |
| 3ef02a3 | f6e0817 | 50篇独立检测证据 |
| f31adcd | 62c6c80 | ING-001原业务红测 |
| 9f49291 | b944b97 | ING-001修复、18项用例与真实复现工具 |
| f731374 | f15dfd6 | ING-001原因、真实dev与验证记录 |

不强推、不改写原提交；原报告内的SHA、模型调用、输入、失败和人工状态保持原样，不因重放而冒充重新执行真实实验。

## 测试与环境

两个工作目录和Python环境分别位于`D:/digital-library-worktrees/mq-fixes/`与`D:/digital-library-worktrees/ing-001/`，各自绑定本目录`app/src/dlrag`，仅共享只读第三方依赖和模型服务。测试使用各自临时数据和`reports/PR-SPLIT-20261019/`，不互写输出。

原`D:/digital-library-rag`保持拆分前`f731374`文件树，切至`archive/pre-pr-split-20261019`冻结，不改变正在使用它的历史服务代码；本轮不重启服务、不重跑Luna/BGE真实实验、不重复入库。正式18000、原50篇dev19000和ING候选19010作只读快照对照。

PR2测试入口现在明确区分目标与继承回归：

```powershell
# 只运行本工作项18项，不顺带跑MQ或COL-002用例。
& ./.venv/Scripts/python.exe -X utf8 scripts/run_catalog_checks.py `
  --work-item ING-001 --scope new --output reports/PR-SPLIT-20261019/ing-targeted

# 完整继承回归，单独保存，不将450项复用算作本轮新增。
& ./.venv/Scripts/python.exe -X utf8 scripts/run_catalog_checks.py `
  --work-item ING-001 --scope all --output reports/PR-SPLIT-20261019/ing-all
```

统计区分：ING-001本工作项18项；PR2总增量28项（COL-002基线10 + ING-001的18）；PR2继承440项（MQ/COL-001的110 + 原项目330）。全量应为468项，原先“本PR138新增”是拆分前历史统计，不再用于新PR2归因。新统计不回写旧JSON。

迁移后的干净版本检查与证据将在执行完成后补充。两份PR保持Draft，暂不合并；PR2依赖关系不等于已允许合并PR1。
