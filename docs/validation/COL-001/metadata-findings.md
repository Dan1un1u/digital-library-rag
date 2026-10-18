# 真实 PDF 批次发现的元数据问题

关联批次：`COL-001-20261018-P01`。本文件记录**现有程序的识别问题及能力限制**，不是已修复清单。

本次编目分为三层：本机规则候选 → 应用内 Luna 辅助识别候选 → **应用之外，由本次编码助手执行的 AI 辅助审核与修订**。最后一层包含对 PDF 首页图像的检查、作者文本支持断言和官方书目记录查证，并非应用已经具备的自动审核能力，也不是用户人工审核。

用户指出：“这属于测试发现的问题。如果没有你，识别错误仍然需要人工干预审核。”因此保留错误候选、问题状态、外部修订和入库值；不得将修订后的正确值倒算成程序最初识别正确。用户随后确认指定三项人工抽查未发现问题，范围见 [人工反馈](batches/COL-001-20261018-P01/human-review.md)；这次确认针对修订后的数据，不关闭原识别缺陷，其余逐篇人工复核仍保持 pending。

## 问题与影响

| ID | 观察阶段与实际表现 | 影响 | 当前处置与状态 |
| --- | --- | --- | --- |
| MQ-001 | 本机候选把 FQ-ViT 的单位 `MEGVII Technology` 当作作者，漏掉 5 位实际作者 | API 不可用或关闭时错误作者可能进入编目 | 本批 API 增强后得到作者名单，再经外部核对；**本机规则缺陷未修复** |
| MQ-002 | 本机候选在多行/分栏作者中遗漏：Ascend 1/18、EQ-ViT 2/12、I-LLM 2/7、XY-Serve 1/12；PackQViT 为 0/7 | 元数据完整性不足，影响作者检索和贡献归属 | 本批 API 增强补全，外部对照首页核对；**本机路径仍存在限制** |
| MQ-003 | 应用内增强识别把 FQ-ViT 的 arXiv 修订日期 2023 当作 year；正式发表年为 2022 | 即使开启增强识别，仍可能录入错误出版年 | 外部查证 IJCAI 官方 BibTeX 后改为 2022，记录 PDF 版本日期；**应用年份语义校验未修复** |
| MQ-004 | 增强候选仍缺 ENEC 的 year、EQ-ViT 的 year/source_url、PackQViT 的 source_url | 需要额外查证或人工补充 | ENEC 根据所供预印本日期填 2026；EQ-ViT 查 Crossref 出版记录为 2024；PackQViT 补官方书目链接。**保守留空属于能力边界，不把所有空值计作错误** |

MQ-002 的分母来自本次外部辅助核对名单，尚非独立人工金标准；只能描述这 11 份指定 PDF 的观察结果，不能推算总体准确率。外部来源：[FQ-ViT 官方 BibTeX](https://www.ijcai.org/proceedings/2022/bibtex/164)、[EQ-ViT 出版者 DOI 注册记录](https://api.crossref.org/works/10.1109/TCAD.2024.3443692)、[PackQViT 官方会议记录](https://papers.neurips.cc/paper_files/paper/2023/hash/1c92edb990a05f2269f0cc3afbb4c952-Abstract-Conference.html)。

## 最小复现与未修复测试

`app/tests/ingestion/test_metadata_known_issues.py` 提供两个不依赖真实 PDF、密钥或模型服务的合成输入：

- MQ-001：`author_names("MEGVII Technology")` 当前返回一名“作者”，期望返回空列表。
- MQ-003：仅含 arXiv 修订日期的年份候选被 `merge_candidates` 接受；应保留未知出版年，待明确出版信息或权威记录确定。

两项使用 `xfail(strict=True)` 标注**已知且尚未修复的失败**。这不是测试通过或问题关闭；JUnit 中它们属于 skipped/pytest.xfail，运行摘要单独记录 expected_failures。去掉 xfail 标记运行，断言会失败；未来修复后严格模式的 XPASS 会要求同步更新缺陷状态。

修复前继续保留导入前审核。后续修复应加强机构/人名区分、分栏作者完整性、日期种类与出处，并基于这些失败用例验证，另记录真实 PDF 复测结果。本次不以外部辅助改值代替程序修复。
