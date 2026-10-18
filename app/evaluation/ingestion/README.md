# A 解析记录

这里的 catalogue.csv、parsing_quality.csv 与两份 synthetic_*_import.json 均来自 3 个明确标记的合成测试 PDF，生成器及实际样本位于 tests/ingestion。字符模式为 7 块，token 模式为 6 块。

parsing_quality.csv 的偏移结果由程序核验。body_order 保留 pending_human_review；它不代表人工正文阅读顺序验证。diagnostics 中的双栏、空页或扫描提示应在真实资料导入后逐页检查。

真实资料到位后先抽查 10 篇，人工填写来源与权限；用 CLI report 输出到新的目录，保留当前合成记录。候选题模板在 handoff/A/candidate_questions.jsonl，未标注、不应用于成绩统计。

命令与真实执行记录见 handoff/A/README.md、acceptance.md。
