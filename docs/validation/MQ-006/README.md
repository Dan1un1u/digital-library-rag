# MQ-006：六篇待分类文献的独立入库复验

本页记录首轮“补标签后入库”的修复。用户随后要求自动分类，后续实现与新的六篇增强识别复验见 [关键词与LLM辅助分类](llm-assistance/README.md)。以下原始执行记录与提交保持不变。

六篇原始PDF在空dev库中全部复现“已就绪、仍待分类”。修复后，缺少学科的原清单被拒绝；填写“自然科学”再导入，六篇全部就绪且分类正确。新增33项自动检查及558项全量回归通过。正式库和其他三个已有测试库均未改动。

## 原因与修复

原批次 `COL-001-20261018-P01` 记录了具体主题词，却未记录所属学科。上传页面会补入学科标签，但批次工具和后台允许不填。显示旧记录时依赖题名、主题词中的关键词推测，这六篇中的 NPU、FPGA、RNN、LLM 等词未命中。

修复将学科检查放到共用的 `require_discipline`：同步上传、异步上传、服务入库和批次计划/执行都需要在 `topics` 中明确填写一个学科。缺失返回 `DISCIPLINE_REQUIRED`，冲突返回 `DISCIPLINE_CONFLICT`，均在登记文献前处理；异步上传也不会创建无效任务。主题词保留，不自动推断学科。预览、历史记录读取和旧记录的分类回退仍可使用。

## 真实PDF对照

六份文件均从正式库只读导出，再复制到本轮输入目录；内容SHA256与原批次一致。两次对照均从各自的空库开始，合计100页、564个正文片段。使用原来已核对的题名、作者、年份等字段回放确认后的导入阶段，**没有重新测试增强识别模型的字段提取准确率**。

| 文献 | 修复前 | 修复后 |
| --- | --- | --- |
| Ascend / Squeezing Operator Performance Potential… | 就绪、待分类 | 就绪、自然科学 |
| CSB-RNN | 就绪、待分类 | 就绪、自然科学 |
| ENEC | 就绪、待分类 | 就绪、自然科学 |
| Is Your NPU Ready for LLMs? | 就绪、待分类 | 就绪、自然科学 |
| SpinQuant | 就绪、待分类 | 就绪、自然科学 |
| XY-Serve | 就绪、待分类 | 就绪、自然科学 |

每篇以完整题名分别做关键词、向量和混合检索，两阶段各18次均在前5项找到对应文献。这个结果验证入库后仍可检索，不代表一般相关性评测。

修复后的原清单先进行一次批次计划检查，再向两个上传接口各提交六次：全部按预期拒绝，空库与索引不变。为六篇的 `topics` 添加“自然科学”后再导入，逐项核对所有元数据、原文下载哈希、页数与分类；按学科过滤返回自然科学6篇、另外两类0篇。重复导入首篇后，馆藏和索引快照不变。实际页面的自动检查也显示总数6篇、自然科学6篇，无页面异常。

实际向量计算使用仓库外的FP16测试接线，模型为 `BAAI/bge-m3`，revision `5617a9f61b028005a4858fdac845db406aefb181`。该接线及个人配置没有提交；交付项目继续使用PR8恢复的硅基流动接口。本轮不调用问答、重排或增强识别服务。

## 提交与测试归属

| 阶段 | 干净提交 | 结果 |
| --- | --- | --- |
| 原PDF问题复现 | `7c5476a` | 6就绪、6待分类；18次题名检索命中 |
| 新用例修复前执行 | `d40c68c` | 33项：23失败、10项有效输入对照通过；无错误、跳过 |
| 修复后目标检查 | `193ec30` | 新增33项全部通过 |
| 修复后全量回归 | `193ec30` | 558项全部通过：新增33、继承525；无失败、错误、跳过 |
| 修复后真实PDF复验 | `193ec30` | 12次缺失学科拒绝；6就绪、0待分类；18次检索命中 |

33项新增用例覆盖六篇题名及代表性主题词、两个上传入口、三种有效学科、学科冲突、批次plan/apply、绕过服务调用、旧记录读取、重复导入和其他字段保留。继承的有效入库样本补上学科，原有断言继续执行，没有删除或放宽测试。

目标检查中，共用学科检查模块语句覆盖率93.33%、分支覆盖率83.33%；全量回归中上传路由语句与分支均100%。共用模块未覆盖的是直接调用时主题字段类型错误的保护分支，API和批次先由现有元数据模型校验类型。覆盖明细见 [comparison.json](comparison.json)。

调试时也发现旧入库样本缺少新必填标签、子进程字符编码设置，以及一处测试导入缺失；这些探索执行的结果和哈希均保留在comparison中，修正后才运行上述干净提交的正式检查。两个重复入库提醒和测试客户端的弃用提示是预期警告。报告中原有 `manual_review` / `manual_retrieval_review=pending` 字段保持原样，不将自动检查写成人工验收。

## 可复核材料

- [修复前结果](baseline/result.json)、[原始计划](baseline/plan.json)、[回执](baseline/receipt.json)、[事件链](baseline/events.jsonl)
- [修复前失败用例](red/pytest.txt)、[目标检查](target/summary.json)、[全量回归](regression/summary.json)，各目录附JUnit与完整测试输出
- [缺失学科12次拒绝](missing-discipline.json)
- [修复后结果](corrected/result.json)、[修订计划](corrected/plan.json)、[回执](corrected/receipt.json)、[事件链](corrected/events.jsonl)
- [全部字段、原文及已有库验证](final-verification.json)、[实际页面检查](ui-verification.json)
- [汇总、环境、覆盖率及证据哈希](comparison.json)

两次批次事件链末端分别为 `74688995748d41beee5bdc6739ff247b6285ee1ae1ea1385069cc49405cfedf9` 和 `0a4ee79d612a06822332c56ceb002cceb9b1d78303cdaeed2a70a340314b6ea9`。原始执行结果保留在本机；发布版result是去掉个人配置路径、未使用问答配置后的摘录，附原件哈希，未改写执行提交。PDF、正文、数据库、索引和密钥均不入Git。

## 重跑方式

在干净提交安装项目及测试依赖后，可运行离线检查：

```powershell
python scripts/run_catalog_checks.py --work-item MQ-006 --scope new --output reports/MQ-006-rerun/target
python scripts/run_catalog_checks.py --work-item MQ-006 --scope all --output reports/MQ-006-rerun/regression
```

真实PDF复验使用 `tools/probe_discipline_ingestion.py`。按[批次模板](../../workflow/catalog-batch.example.json)准备六份PDF和本机清单，SHA256与baseline/plan.json对应；对照原元数据，再生成只增加自然科学标签的修订清单。使用已配置的项目服务启动器创建独立空库，设置专用端口和标识：

```powershell
python tools/serve_validation_library.py --env-file runtime/test.env --data-dir runtime/MQ-006-rerun/library --port 19040 --initialize-empty-index
```

在另一个终端先执行 `--phase missing`，再执行 `--phase corrected`。前者保持空库，后者导入六篇。清单与输出目录均使用新的本机路径；原PDF未随仓库分发，需要自行取得相同输入。修复前的baseline应在 `7c5476a` 的独立工作目录及另一个空库运行。示例：

```powershell
python tools/probe_discipline_ingestion.py --phase missing --manifest runtime/MQ-006-rerun/original-manifest.json --api http://127.0.0.1:19040 --output reports/MQ-006-rerun/missing
python tools/probe_discipline_ingestion.py --phase corrected --manifest runtime/MQ-006-rerun/corrected-manifest.json --api http://127.0.0.1:19040 --output reports/MQ-006-rerun/corrected
```

本轮分支为 `fix/mq-006-discipline`，PR以PR8分支为base，仅提交MQ-006；保持Draft，未合并。正式库仍保留原记录，本轮修复和六篇重新导入仅发生在独立dev库。
