# 标注与冻结规则（共同契约 1.0）

目前 questions.jsonl 是候选汇总，不是最终测试集；A/B/C/D 的候选来源均保留，共 60 道；C 的 15 道已汇入。D 的 15 道为模板（10 multi_document + 5 unanswerable），没有编造真实 doc_id/chunk_id。所有候选暂为 usable_for_evaluation=false，禁止计算正式成绩。

## 复核与配额

A↔C、B↔D 交叉复核；D 的 reviewer 指派 B，但尚无人完成复核。全组目标 60 题：exact 10、vague 15、clarify 10、multi_document 15、unanswerable 10。汇总工具只按规范化文本去完全重复；近义、翻译、措辞改写须由人分配相同 paraphrase_group，并检查不跨 dev/test。首次 split 仅是候选安排；最终冻结后 test 不用于调参。

## 单题检查

1. 核验问题属于冻结馆藏覆盖的领域，不依靠模型常识补足参考答案。
2. exact 是明确术语/对象；vague 是意图明确但表达日常；clarify 是存在不同合理解释；multi_document 需要至少两篇独立来源支撑比较；unanswerable 是馆藏不足而非检索恰好失败。
3. 填写 reference_points、真实 relevant_doc_ids/relevant_chunk_ids，打开原 PDF 检查页序、清洗顺序及原文。每个片段必须来自本轮冻结索引，不能借用 A/B 历史试验中未移交的运行数据。
4. evidence_groups 每组对应一个必要要点，组内是可替代支持片段，组间都需要覆盖。不能用泛泛相关的片段充数；多文献题必须跨文献核查。
5. 澄清题写 clarification_expectation 的追问对象与允许选项；无答案题的文献、片段和证据组数组留空，并人工检查确实不可从本馆藏得到结论。
6. 标记 review_status=approved、reviewer=实际复核人、usable_for_evaluation=true。保留复核意见，禁止只为获得分数放行。

## 冻结

停止导入和元数据修改，记录 /health.manifest 的 index_version 与 corpus_hash；每题填 frozen_index_version、frozen_corpus_hash。脚本在 real 模式拒绝未批准、缺参考、引用不存在、组跨 split 或冻结版本不一致的数据。IDs 校验只证明对象存在，人工仍需保证语义支持。切块/清洗/元数据改变须重新标注并生成新的冻结版本。

## 实验与人工指标

固定同一份 JSONL（SHA256）、split、馆藏、模型和配置，分别运行 keyword/vector/hybrid；只在比较组件处变化。基础 RAG 与规划版本仅切换 --planning-enabled false/true。比较不同报告前核对 environment.json 中 dataset_sha256、manifest 与公开配置。

自动指标：Hit@5、Recall@5/10（完整参考块集合）、检索前 20 条的 evidence_groups 覆盖率。没有参考证据的题不纳入这些指标，分母为零返回 null。检索失败/网络失败单列，报告失败数；期望业务状态命中率另列，不把失败样本当成功。dev/test 分开，mock 的质量指标全部 null。

human_review.csv 以 claim—evidence 关系为单位：完整支持/部分支持/不支持，核验引文是否确实蕴含结论；另按 claim 记录是否得到充分支持及参考要点评分。引用支持正确率=完整支持关系/已人工评审关系；引用覆盖率=得到充分支持的可核验结论/已评审且需要证据的结论。未评审项不填零、不计算为通过。D 当前脚本仅输出人工表格，人工指标标“未评估”，需完成全量评审后由组员汇总。
