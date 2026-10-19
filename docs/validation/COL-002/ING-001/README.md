# ING-001：混合扫描正文覆盖检查与 dev 修复验证

日期：2026-10-19（Asia/Hong_Kong）。工作项：[ING-001](../../../work-items/ING-001.md)。沿用 Draft PR #1，暂不合并。

归属调整：用户后续要求将ING独立到**PR2**，当前分支为`feat/ing-001-fulltext-gate`，以MQ的PR1分支为base。以上PR1及下文提交/环境数据是原执行身份，保持不变；新的分支检查单独归档，见[迁移说明](../pr2-migration.md)。

**修复候选已实现，并在独立 dev 验证通过；正式实例尚未部署。** 新导入的混合扫描 PDF 若存在疑似缺少文字层的正文页，会暂停导入、提示页码并保留原件，不再仅凭封面片段进入 ready/检索索引。原件完成应用外 OCR 后，以新文件身份重新上传可正常导入。本候选没有实现自动 OCR、乱码识别或旧库自动迁移。

完整离线回归 **468 passed**，其中本轮新增18项，本PR此前新增120项、原项目复用330项。真实 dev 对 SS06 原件、同一原件重复上传、SS14 同类原件均正确拦截，SS06 原有 OCR 副本21页均有片段。额外1次真实 Luna 元数据预览完成，未修改馆藏；实际索引使用本机 BGE FP16。原正式25篇/1821片段及原dev50篇/3262片段的完整快照均保持不变。

## 1. 原因与失败证据

原路径存在两个条件缺口：

1. `parse_pdf`只在**全部页均无文字**时拒绝PDF。SS06有文字封面，其余20页扫描正文没有文字层，仍返回21个页记录。
2. `LibraryStore`只要求产生片段，保存后进入indexing；重建成功即ready。没有将每页扫描诊断或覆盖情况转为导入前置检查。封面产生的2个片段足以让整篇文献成功。

原真实复现见[原始记录](../negative-reproduction.json)：SS06 SHA `a37b62fd92b1d1fe2264f0afc23c5c8f04198e4d157027d138bc65a75934cc5e`，21页、仅1页产生2片段、20页SCANNED_PAGE_NO_OCR，却done/ready。本轮不修改该证据。

先在干净提交 `f31adcdc366c8a634bac8d6b0d730871c029b19e` 加入合成回归，业务代码与原版本相同。期望422/待核对，实际200/ready，**1项测试失败**；[失败摘要](baseline-red-summary.json)及本地pytest/JUnit哈希保留。后续同一核心断言在修复版本正常通过，未用xfail隐藏它。

## 2. 修复行为与白盒路径

候选干净提交：`9f492912e1da7e025a134081f3dbc06cc41d1916`。业务、18项测试、真实dev复现工具在此版本冻结，所有正式执行前后工作区干净；后续证据归档不改写测试版本。

| 层次 | 变更及目的 |
| --- | --- |
| 页面解析 | `parser.py`更新为pymupdf-conservative-v3；在页边文字清洗后分析实际显示的栅格图像与剩余文字，而非只看PDF是否引用过图片资源 |
| 覆盖判断 | 新增[fulltext.py](../../../../app/src/dlrag/ingestion/fulltext.py)：大面积栅格页且文字稀少时标记SCAN_TEXT_LAYER_REVIEW_REQUIRED，保留具体页码 |
| 写入前检查 | `_parse_document`在切分前检查；`save_parsed_content`也检查，避免其他调用者绕过正常路径写入标记为待核对的部分正文 |
| 索引与失败状态 | 抛出FULLTEXT_REVIEW_REQUIRED；使用已有failed数据库状态，未保存部分页/片段、未开始索引，原有效索引继续服务；无数据库schema迁移 |
| 同步/异步接口 | 同步返回422及结构化页码；异步任务error保留已知错误码、页数及提示。未知/伪造提供方错误消息不直接回显 |
| 界面 | 文献管理对该错误显示“待核对正文（未加入检索）”、页码及下一步提示，原文入口保留；不会把ready改名来伪装解决问题 |

`mixed-scan-coverage-v1`的启发式条件固定为：可见栅格图像的**并集面积至少占页面50%**，清洗后非空白字符数不超过40；低分辨率灰度渲染中，像素值小于240的比例至少0.003且有明暗变化。重叠图片不累加面积，图像坐标按页面旋转还原，裁剪到可见范围。

此规则用于定位**疑似缺失文字层**：正常文字页、已有足够OCR文字的扫描页、纯空白页、纯白栅格页、小图片/重叠小图不会因这一条件被拦截。图版等大面积无字图片也可能进入保守核对；当前没有“勾选直接放行”的例外入口，需要核对并提供适合检索的文件。超过40字符的部分OCR可能仍漏掉，不能将通过此门槛等同于全文完整性或OCR准确性认证。

## 3. 真实 dev 实验

使用全新隔离库 `D:/llm_exp/digital-library/workspace/validation/ING-001-20261019/candidate-library/`，API `http://127.0.0.1:19010`，后端标记准确返回`9f49291`。正式API18000与原50篇dev API19000仅作只读保护对照。候选初始为空，复现工具拒绝错误存储身份、非当前干净版本或非空初始库。

输入仍是COL-002冻结原件及原有OCR副本；逐项核对原件/派生SHA，没有重做OCR或换文件冒充原输入。导入表单书目沿用外部AI辅助参考，不算本轮模型自动识别结果。[live-dev.json](live-dev.json)记录50份只读重扫、9个任务及逐步结果。

| 实际任务 | 结果及判断 |
| --- | --- |
| SS01正常文字原件 | done/ready，29页、107片段，用作原有效索引锚点 |
| SS06原件真实Luna增强预览 | completed；与导入前后候选完整快照一致。说明元数据识别成功仍须独立检查正文 |
| SS06混合扫描原件 | error/FULLTEXT_REVIEW_REQUIRED，提示2–21页；保存原件和失败记录，0正文页/0片段落库，索引与ready文献集合不变 |
| 同一SS06原件重复上传 | 保留待核对错误，无新增正文、无索引处理阶段、有效索引不变 |
| SS14同类原件 | error/FULLTEXT_REVIEW_REQUIRED，提示3–25页；0正文页/0片段落库，有效索引不变 |
| SS04纯扫描原件 | NO_EXTRACTABLE_TEXT，维持已知全文OCR边界，不另算新修复 |
| SS06原有外部OCR副本 | done/ready，21页均产生片段，共55片段；与原件SHA不同，原件失败状态不被悄悄改成ready |
| HU08乱码原件对照 | 仍done/ready、16页66片段，显式标签“正文待核对”；**ING-002仍开放**，不把非空乱码算作本轮已修复 |
| SS06 OCR副本重复上传 | 完整候选快照相同，无新增、索引不变 |

候选最终共6条登记：3条ready、3条failed；真实索引为3篇/228片段。对修正副本题名执行keyword/vector/hybrid各一次，均在top5找到SS06；这是3次路径冒烟，不是总体检索质量评测，也不覆盖原COL-002的RET-001失败。

### SS14是扩大检测得到的同类发现

对原50篇实际入库文件逐项只读运行新检查，49份未触发此门槛，**SS14触发**。SS14为Leon Festinger的*A Theory of Social Comparison Processes*，25页；清洗后仅2页有文字，3–25页疑似无正文文字层。编码助手查看第3页渲染，确认图像中存在密集可读正文，并非空白页；这是应用外AI辅助目视核对，不是用户人工验收。

该发现归入ING-001同一类，不另计一个重复缺陷。旧50篇库未自动迁移，SS14的旧ready记录和原检测统计完整保留，后续推广需单独复核/补做OCR并重新编目。49份未触发不能写成49篇全文质量已合格。当前候选也未给SS14自动补全文字。

## 4. 离线测试、界面及原件访问

[完整回归](offline-all-summary.json)：468 passed，0failed/error/skipped/xfail，138项本PR新增 + 330基线复用。分组为COL-001已有110、COL-002已有10、ING-001新增18。本轮新增覆盖同步阻断、异步错误、无部分写入/无索引更新、重复与显式重试、外部OCR副本、空白/小图/重叠图片/矢量页、旋转/平铺扫描、仅有页码、错误消息约束与管理界面提示。

[实际dev界面AppTest](ui-check.json)无异常，验证DEV标记、两处“待核对正文”、2–21及3–25页提示，6个原文入口；测试前后候选快照不变。另[实际原文HTTP检查](source-access.json)确认6份存储文件（包括3个被拦截原件）均HTTP200且SHA吻合，不只是检查链接存在。没有用户人工浏览或录制演示视频。

独立候选Streamlit网页的后台启动动作被自动审批拒绝，工具仅返回`blocked by policy`，未给出更具体原因；没有重试该动作或声称19510已提供网页。用已运行的候选API19010及AppTest完成验证。原50篇dev网页19501仍对应原基线后端，不能当作本候选已部署的界面。

两个调试前置错误另记在[执行说明](execution-notes.json)：一次未给CLI子进程设置PYTHONUTF8，另一次AppTest相对路径按调用脚本目录解析。均是调试/运行器问题，未计作业务修复，未覆盖正式468项及原始失败证据。既有Starlette/httpx弃用与重复文件元数据保留警告仍保留。

## 5. 复现及贡献边界

复现工具：[probe_fulltext_gate.py](../../../../tools/probe_fulltext_gate.py)。在仓库根目录，确认干净候选版本、独立端口空闲、模型服务就绪，使用新隔离存储及新输出位置；不要向原50篇库或正式库重复写入。

```powershell
$frozen = 'D:/llm_exp/digital-library/workspace/validation/COL-002-20261019'
$trial = 'D:/llm_exp/digital-library/workspace/validation/ING-001-replay'
$privateEnv = 'D:/llm_exp/digital-library/workspace/deployments/lib_management_v1_20261018/app/.env'

# 独立终端运行候选后端；首次空库才初始化索引。
& ./.venv/Scripts/python.exe -X utf8 tools/serve_validation_library.py `
  --env-file $privateEnv --data-dir "$trial/library" --port 19010 --initialize-empty-index

# 在另一终端执行；输入原文件必须仍与冻结SHA一致。
& ./.venv/Scripts/python.exe -X utf8 tools/probe_fulltext_gate.py `
  --catalog docs/validation/COL-002/catalog.json --source-dir $frozen `
  --data-dir "$trial/library" --output reports/ING-001/live-replay

& ./.venv/Scripts/python.exe -X utf8 scripts/run_catalog_checks.py `
  --scope all --work-item ING-001 --output reports/ING-001/offline-replay
```

目前19010候选服务已运行，重放须先选另一端口并同时给服务及probe传入匹配端口/`--api`，或在明确停止旧候选后再使用原端口。既有正式18000及原dev19000继续只读。真实输入、OCR副本、模型回执全文、数据库/索引及私有配置均不上传Git；克隆源码不包含实验数据。

| 本轮贡献 | 可追溯量及归因 |
| --- | --- |
| 原因分析与失败复现 | 原真实SS06失败不回写；新增1个核心回归先在原业务逻辑失败，再在候选通过 |
| 业务候选 | 页面图像/文字联合检查、保存前门槛、同步/异步错误和管理界面说明；没有新增OCR引擎或修改LLM模型 |
| 新写测试 | 18项；首次红测包含在最终18项中，不额外算第19项 |
| 复用回归 | 此前120项PR测试及330项基线，共450项；最终468不是本轮新写468项 |
| 真实执行 | 50文件只读重扫、9个任务（8导入/重复任务 + 1增强预览）、3次修正副本题名检索、6次原文HTTP核验、1次实际dev AppTest |
| 扩大检测 | 发现SS14同类正文覆盖问题，原数据保持不变；不重复计作新缺陷编号 |
| 外部工作 | 沿用原OCR副本、外部参考书目及编码助手目视核对，不记为应用自动补全或人工验收 |
| 仍待完成 | 用户审阅、正式部署与旧数据复核；ING-002/MQ-005/RET-001继续开放；暂不合并PR |

[证据清单](evidence-manifest.json)记录便携文件、原失败证据和本地完整任务回执的SHA。哈希用于内容校验，不能当作数字签名或用户验收证明。不编造人工工时，也不以提交数/代码行数直接替代课程研究贡献。
