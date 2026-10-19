# PR1 复验：日期对应收录版本

结论：**按用户 2026-10-19 明确的新标准，PR1 代码候选验收通过**。本结论是本地代码审核与验证结论，不是 GitHub 外部审阅人的 Approve；PR 保持 Draft、暂不合并，现有服务未更新。

## 标准与修改

year 表示当前收录 PDF 的版本年份。明确的 arXiv 版本戳、公开/修订日期可使用，不要求正式发表；正式版可使用对应的出版/版权日期。无日期证据可留空。详见[标准变更](../collected-version-year-policy.md)。

本轮代码提交 `ffaf5eed86bcff04b790a03244febc771c6b415a`、`06183046e6700a4587a839c79088db6540d34e89`：

1. 更新增强识别提示和服务器校验；依据页面上下文解释日期类型，当前版本戳/修订优先。仅有目标会议年份、否定日期或参考文献年份不能通过，保留初始值时也执行同一校验。
2. 校验读取 PDF 原始文字顺序，避免坐标排序将旋转排版的 arXiv 页边戳打散。模型仍使用前两页图像和有界文字预览。
3. Crossref 继续补相关出版来源。只有页面出版版式及 DOI 对应、外部可用出版年份一致，才补缺失版本年；版本不明时呈现相关出版日期供核对，不强填或覆盖已有值。
4. 界面改为“版本年份”，显示日期依据；保留人工核对、修改和确认导入。

不修改本机规则范围、ING 业务、PR2、现有馆藏、数据库或索引，不引入多版本出版管理结构。

## 验证结果

最终测试与实验均绑定干净提交 **`06183046e6700a4587a839c79088db6540d34e89`**，源码确认来自 MQ 独立工作目录，执行前后干净。后续文档归档不改变被测源文件。

| 验证 | 结果 | 证据 |
| --- | --- | --- |
| PR 新增回归集合 | 128 通过，0 失败/错误/跳过 | [摘要](new-summary.json) |
| 完整继承回归 | 458 通过 = PR 新增 128 + 原项目复用 330 | [摘要](all-summary.json)、[输出](all-pytest.txt) |
| MQ 定向集合 | 102 项包含在上述集合中；43 日期、59 书目补全 | 同上；不另加到总测试数 |
| 原 7 个验收场景按新标准重放 | 7/7，通过实际同步预览接口；预览未入库 | [接口回放](acceptance-replay.json) |
| 真实 Luna 原 PDF 预览 | 3/3 通过；没有书目查询或导入 | [真实预览](live-preview.json) |
| 历史缺字段候选 + PDF 版本依据 + 真实 Crossref | 3/3 通过；独立于真实模型运行 | [补全回放](crossref-replay.json) |
| 馆藏隔离与只读对照 | 正式 API18000、原 dev API19000、ING 候选 API19010 的快照未变 | 接口/补全回放的快照摘要；真实模型预览另对照正式 manifest |

本轮较之前的 440 项额外增加 **18** 个参数展开用例，并调整既有日期断言；不能把全部 458 项作为本轮新写测试。新集合中仍含此前 26 项入库验证。测试未冒充用户人工复核或演示视频。

真实 Luna 返回及页面证据：

| 所供 PDF | 当前版本依据 | 候选年份 |
| --- | --- | --- |
| FQ-ViT | arXiv:2111.13824v4，17 Feb 2023 | 2023 |
| I-BERT | arXiv:2101.01321v3，8 Jun 2021 | 2021 |
| SpinQuant | arXiv:2405.16406v4，20 Feb 2025 | 2025 |

三个日期均由 Luna 输出，服务器归类为 version 并与页面文字对应；没有用 arXiv 编号前缀推算年份。原 FQ-ViT 入库值 2022 不在本轮回写。

真实 Crossref 回放沿用最初的缺字段候选，添加从同一 SHA256 PDF 读取的版本上下文：ENEC 的缺年保持空值，EQ-ViT 的缺年保持空值并补相关 DOI，PackQViT 保留 2023 并补相关 DOI。前两者没有直接套用外部正式出版年；这是新政策下的预期行为。ENEC 的当前 PDF 本身有 2026 版本戳，但此项实验只测试历史缺字段输入的书目补全，不冒充重新调用 Luna。

原 7 场景中，预印本公开 2023、arXiv v4 2023 现合法；正式版 2025 保留。目标会议年份两例、完整/截短否定日期两例均留空，初始值也不能旁路。

年份模块语句/分支覆盖为 **97.20% / 92.86%**，书目模块 **100.00% / 96.55%**。覆盖率不是元数据识别准确率；前两页缺证据、扫描页读图及人工确认仍按现有能力处理。

## 失败留痕与审核意见

首轮干净 `ffaf5ee` 完整回归为 **457 通过、1 失败**。拒绝畸形候选时新增了原本不存在的空 year 字段，违反既有接口约定；后续 `0618304` 恢复“仅清空已有字段”。保留[首次摘要](first-all-summary.json)和[首次失败输出](first-all-failure.json)。最终重跑没有跳过或改写该既有用例。

此前 `840f9c1` 的原验收仍留在本机 `reports/PR1-acceptance-20261019/`，它按旧的正式发表年要求判定，不回写为通过。新标准下不再把 FQ-ViT 2023 本身当作缺陷。MQ-003 与 MQ-004 当前代码候选均达到本轮约定标准，没有发现阻止该候选验收的遗留问题；正式部署、用户审阅及后续系统测试另行开展。

机读结论：[verdict.json](verdict.json)。GitHub 最终状态另在本机保留，PR1 仍以 main 为 base；PR2 不追加本轮 MQ 代码。GitHub 未配置托管检查和外部审阅时，不把本地通过描述成平台审批。

## 复现

在本工作目录的独立 Python 环境中，输出目录必须是全新的目录：

```powershell
.venv/Scripts/python.exe -X utf8 scripts/run_catalog_checks.py --scope new --output reports/version-review-new --tokenizer-cache runtime/tokenizer-cache
.venv/Scripts/python.exe -X utf8 scripts/run_catalog_checks.py --scope all --output reports/version-review-all --tokenizer-cache runtime/tokenizer-cache
.venv/Scripts/python.exe -X utf8 tools/review_version_year.py --output reports/version-review-replay --protected-api http://127.0.0.1:18000 --protected-api http://127.0.0.1:19000 --protected-api http://127.0.0.1:19010
```

真实预览使用 `tools/probe_metadata_year.py`，需本地 PDF 清单、匹配的 SHA256、私有配置和全新输出目录；PDF 与凭据不入 Git。真实书目回放的输入与输出、版本证据和日期决策保存在上述独立 JSON，查询超时配置 20 秒，无自动重试。原始运行日志和覆盖率原件保留在 MQ 工作目录 `reports/PR1-version-year-20261019/`。
