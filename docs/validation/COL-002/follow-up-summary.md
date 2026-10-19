# COL-002 测试发现：后续修复汇总

2026-10-19，用户授权先合并PR1，再依次修复PR2测试发现。PR1已合并，后续修复按工作项拆成独立Draft PR，均未合并或部署。

| 工作项 | 处置与候选结果 | 所属PR / base | 定向 / 完整回归 |
| --- | --- | --- | --- |
| ING-001 混合扫描仍就绪 | 同步已合入MQ基础后复验；真实SS06/SS14原件继续阻断，SS06既有OCR副本可导入 | [PR2](https://github.com/Dan1un1u/digital-library-rag/pull/2) / main | 18 / 486通过 |
| ING-002 非空乱码仍就绪 | 原始提取控制码密度门槛，异常页暂停导入、不写正文或向量，保留原文核对入口 | [PR3](https://github.com/Dan1un1u/digital-library-rag/pull/3) / PR2分支 | 新增18 / 504通过 |
| MQ-005 卷期年与上线年 | 接受有页眉卷期依据的年份；真实HU25保留2009，相关Crossref上线2010仍呈现、不覆盖 | [PR4](https://github.com/Dan1un1u/digital-library-rag/pull/4) / PR3分支 | 新增10 / 514通过 |
| RET-001 题名向量漏检 | 给正文向量加入题名上下文、固定索引表示；原50题名三模式top5从148/150到150/150 | [PR5](https://github.com/Dan1un1u/digital-library-rag/pull/5) / PR4分支 | 新增9 / 523通过 |

依赖链为 **main → PR2 → PR3 → PR4 → PR5**，用于复用已测基础；每个PR相对base仅包含本工作项增量。PR2不接收后三项业务代码，只汇总结果和链接。用户仅授权合并PR1，余下PR继续Draft。

## 证据与工作量

- PR1合并提交 `720f5840aa9519b7ca28b66c2e86e851ec85e8ec`，[合并回执](post-pr1-merge/pr1-merge.json)。不是部署记录。
- PR2基础复验：干净 `c127fa1`，[18目标/486完整、真实原件及HU25诊断](post-pr1-merge/README.md)。诊断确实捕获“模型读对2009但服务器清空”，没有把留空直接宣称完整修复。
- ING-002：干净 `a985039`，[1项原失败、18目标、504完整、真实50份扫描与3次任务](https://github.com/Dan1un1u/digital-library-rag/blob/fix/ing-002-text-layer-review/docs/validation/COL-002/ING-002/README.md)。只有HU08命中新编码门槛，其全部16页被标记；正常HU11可导入。49份未命中不等于人工合格。
- MQ-005：干净 `f9cbb96`，[1项原失败、10目标、514完整、真实Luna+Crossref](https://github.com/Dan1un1u/digital-library-rag/blob/fix/mq-005-issue-year/docs/validation/COL-002/MQ-005/README.md)。不继续要求正式发表日期或建设多版本出版系统。
- RET-001：干净 `e05b3b6`，[1项原失败、9目标、523完整、真实BGE固定语料比较](https://github.com/Dan1un1u/digital-library-rag/blob/fix/ret-001-title-vectors/docs/validation/COL-002/RET-001/README.md)。50篇/3262片段、查询及top5不变，vector48/50→50/50，keyword/hybrid仍50/50；5条正文控制前后均命中。

本轮后三项共 **37个新增参数展开用例 = 18 + 10 + 9**。最终523项包含PR2及更早的486项，不将不同阶段的完整回归数相加冒充新写测试。3个原业务红测、独立修复提交、目标与全量验证、输入哈希及真实实验分别保留；不编造工时或用户人工审核。

正式与历史dev实例 API18000/19000/19010 均只读对照，未重启、修改数据库、原PDF或索引。质量门槛的真实文件验证使用独立临时库和mock向量；RET-001另用真实本地BGE和单独候选索引，两者不混称。

## 尚需区分的边界

候选通过不等于正式服务已更新。HU08旧乱码正文仍需可靠OCR或更换版本，SS06/SS14原件的缺失文字没有自动生成；题名命中不能证明正文恢复。元数据与正文仍需用户抽查，一般语义检索质量还需独立标注评测。正式推广与旧数据复核、演示视频和剩余PR合并不在本轮冒充完成。
