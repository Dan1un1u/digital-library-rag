# PR1：MQ范围整理与拆分复验

用户于2026-10-19要求：PR1保留MQ修复，本轮ING移至PR2，今后按测试任务隔离。

PR1当前为`feat/catalog-ingestion-audit` → `main`，保留MQ-003收录版本年份证据校验（2026-10-19按用户新要求调整，见[新验收报告](version-year/README.md)）、MQ-004选择式书目补全及它们依赖的原COL-001入库追溯与验证基础。COL-002数据/工具/证据和ING-001修复均移出PR1最终差异，迁往独立依赖PR2。本轮未合并或部署。

清理提交`b0e3e8d8ea762cf1bdcf3521157ed499b309e18d`反向移出7个混入提交，不强推、不改写历史；`app/`、`tools/`、`scripts/`均与MQ阶段`5273c33`一致。除原MQ内容外，只新增用户要求的AGENTS.md任务规则及隔离流程，不新增ING业务或测试。

在独立工作目录`D:/digital-library-worktrees/mq-fixes`及独立`.venv`重跑：**440 passed，0失败/错误/跳过/预期失败**。本PR新增110项，基线复用330项。测试绑定干净`b0e3e8d`，执行前后干净，见[本次摘要](pr1-split-summary.json)。只读共享第三方依赖，各自临时库、tokenizer缓存和报告均独立；不沿用ING目录的editable源码。

MQ业务功能本轮未改变，因此不重复调用真实模型、不重新添加文献。旧MQ真实Luna/Crossref预览及用户反馈仍保留原身份。正式25篇/1821片段、原50篇dev及ING历史候选仅作只读对照，不重启或迁移服务。

后续规则见[测试任务隔离](../../workflow/test-task-isolation.md)。PR2以PR1分支为base，只呈现ING增量，不能把继承的MQ修复算作PR2新工作；PR1仍以main为base。两份PR均保持Draft、暂不合并。原始ING历史提交仍在Git历史中，最终审阅以各自相对base的差异为准。
