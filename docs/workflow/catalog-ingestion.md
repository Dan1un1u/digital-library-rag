# 馆藏添加与白盒测试流程

本流程将一次馆藏扩充作为可复核的工作单元。每批使用一个 `batch_id`，每份 PDF 使用内容 SHA256 标识，代码、元数据来源、执行记录和 PR 相互关联。

## 1. 登记输入与基线

- 由用户提供 PDF 本地目录；原始 PDF 保留在本机，不提交 Git。
- 记录来源、文件名、SHA256、文件大小和处理日期。来源及权利信息不明时如实填写，不推断许可。
- 记录入库前 `/health` 的文献数、片段数、`index_version`、`corpus_hash` 和模型身份。
- 运行前备份 SQLite，并保留当前索引指针和有效索引快照；备份保存在 Git 忽略的本机目录。

## 2. 识别候选并核对元数据

界面路径：**上传与管理 → 上传文献 → 选择 PDF**。

`POST /documents/metadata/jobs` 仅识别候选；通过 `GET /document-jobs/{job_id}` 查看进度。它不写入正式馆藏、不建立索引。

分支候选另提供“联网补全出版资料”，默认关闭。开启增强识别后可选择；修改选项后点击“重新识别文献信息”。同步及异步元数据接口均接受 `use_lookup=true`，缺省为 false。增强识别成功后，仅将题名和前两位作者姓名发送至 Crossref 查询期刊/会议注册记录，不发送 PDF；匹配唯一且题名、作者吻合时补缺失年份和 DOI 来源，已有值保留，差异显示待核对。来源区可打开各补全字段的出版记录。无匹配、歧义或查询失败时保留已有结果，缺项继续留空。管理员可用 `METADATA_LOOKUP_ENABLED=false` 关闭、`METADATA_LOOKUP_TIMEOUT_SECONDS` 设置超时。实现与验证见 [MQ-004](../validation/COL-001/mq004-enrichment.md)；目前尚未合并部署。

逐项对照 PDF 首页、出版信息及可核验的来源记录：

| 字段 | 核对要点 | 留痕 |
| --- | --- | --- |
| title | 主副标题完整，不用文件名或期刊名替代 | 页码、核对方式与改动前后值 |
| authors | 姓名完整、顺序正确，排除单位和邮箱 | 页码及有序作者列表 |
| year | 使用实际出版年，不使用文件创建时间或参考文献年份 | 出版信息所在页 |
| language/topics | 与文献内容一致 | 标注依据 |
| source_url/rights_note | 来源可核验，权利声明如实记录 | 原始来源与备注 |

自动识别、人工修订、自动检查分别记录。不得把模型输出直接标记为“人工审核通过”。无法确定的年份等信息保留空值，并记录待核对项。

## 3. 先计划、再导入

将核对后的字段写入本机批次清单。`tools/catalog_batch.py plan` 检查文件、哈希、清单和重复项，不写入馆藏。明确执行 `apply` 后，才调用现有上传任务接口。

界面操作为核对字段后点击“导入并建立索引”；对应 `POST /documents/jobs`。批次工具的输入清单保存在本机，仓库只提交清单模板和去除本地路径的审计结果。

工具使用示例（在仓库根目录执行）：

```powershell
.venv/Scripts/python.exe tools/catalog_batch.py plan runtime/COL-001/input.json --output runtime/COL-001/plan-v1.json
.venv/Scripts/python.exe tools/catalog_batch.py apply runtime/COL-001/input.json --plan runtime/COL-001/plan-v1.json --output runtime/COL-001/run-01 --backup-ref COL-001-backup-01
```

将 [catalog-batch.example.json](catalog-batch.example.json) 复制到本机忽略目录并填写；`pdf_path` 相对清单文件解析，也可填写绝对路径。先使用 `Get-FileHash -Algorithm SHA256` 固定文件哈希（JSON 中使用小写值）。`plan` 不发起网络请求，只检查文件头，不代替完整 PDF 解析。文件或元数据改变后必须生成新版计划，`apply --plan` 会拒绝与保存计划不一致的输入。

核对尚未完成时保留 `review.status=pending`。完成 PDF 自动核对可填 `ready/automated_pdf_check`，人工核对才填 `ready/human_pdf_check`，并登记页码或记录 ID 作为 evidence。工具只校验声明格式，不能证明核对实际发生。`metadata_before` 可保存识别候选，工具据此输出字段改动；候选缺失时不虚构改动。

`--backup-ref` 是已完成备份的记录 ID；工具不会代替数据库备份。对运行中的 SQLite 使用 SQLite backup API，不能只复制可能带 WAL 的主数据库文件。当前索引快照保留在本机。每次 `apply` 必须使用新的输出目录，包含 `plan.json/before.json/events.jsonl/after.json/receipt.json`。断线或超时可能意味着后台任务仍在运行，应先按 job_id 检查，不自动重投或覆盖证据。批次不是整体数据库事务，前面成功的文件不会因后面的失败自动撤销。

默认只接受可信本机 HTTP 服务、每份不超过 25 MiB 的 PDF；整个批次先校验再上传。一次只由一个操作人执行，期间避免其他入库或重建操作；馆藏集合出现额外变化时工具会将结果标记为 incomplete。回执不自动包含 PDF 路径，但元数据与核对备注仍需检查后再提交。

事件使用 `event_sha256` 和 `previous_sha256` 串联，PDF 内容哈希独立使用 `sha256`。末端哈希须随 PR 等独立记录保存才能帮助发现后续修改；哈希链不具备数字签名的身份认证作用。

## 4. 观察内部处理路径

| 阶段 | 代码入口 | 应观察的结果 |
| --- | --- | --- |
| 文件类型与大小 | `api.routes.temporary_pdf` | 类型不符返回 415；超过大小限制返回 413 |
| 任务与进度 | `api.document_jobs.DocumentJobs` | queued → file_received → 解析/建索引 → done 或 error |
| 去重与登记 | `LibraryStore.register_document` | SHA256 相同复用 doc_id；不覆盖已有元数据 |
| 正文解析 | `parser.parse_pdf` | 页码可追溯；无正文/加密/损坏文件明确失败 |
| 按页切分 | `chunker.chunk_pages` | text 等于页内半开区间；不跨页；字符计数不冒充 token |
| 事务写入 | `LibraryStore.save_parsed_content` | 校验失败不留下半套 pages/chunks |
| 向量与索引 | `Services.rebuild` → `Retriever.build` | 本地 BGE 身份匹配，完整新快照后才切换 current.json |
| 可检索状态 | `Services.ingest` | 完成索引后 ready；失败保留旧有效索引 |

当前配置是每块最多 1200 字符、强制断开时最多重叠 150 字符，不应写成“1200 token”。扫描 PDF 的标题识别成功，也不意味着正文已有 OCR。

## 5. 验证并保存证据

- 对每份 PDF 核对 `doc_id == "d_" + SHA256`、状态、页数和元数据。
- 比较入库前后集合差异；预期新增数按唯一 PDF 内容计算，不按文件名计算。
- 记录每份文件对应的 job_id、doc_id、索引版本和处理结果。
- 用题名或正文关键短语验证可检索，再打开原文核对页码与片段。
- 对重复导入、建索引失败与恢复等内部路径执行定向白盒测试，并报告语句、分支覆盖情况及未覆盖项。

真实文献入库属于真实环境联调；白盒测试通过隔离数据库、合成 PDF 和故障注入检验内部决策。两类证据分别记录，不能用模拟向量结果声称真实检索质量达标。

## 6. 形成贡献与 PR

记录链：`工作项 → 来源文件 SHA256 → 元数据修订 → 用例 → 执行证据 → 测试代码提交 → PR`。

贡献按实际新增的工具、用例、已检查的文献及发现的问题记录。既有 330 项测试是基线，不能算成本次新写的 330 项测试；不以拆分提交数量代替工作量。

一个 PR 应形成可独立复核的完整工作单元：流程说明、可复现工具、测试与结果、数据批次记录、未解决问题。先保留 Draft 状态；满足工作项中的完成条件、核对数据后再申请合并。本次不自动合并。

用例与执行口径见 [COL-001 白盒测试说明](../validation/COL-001/README.md)。证据汇总放在 `docs/validation/`；`runtime/`、`reports/`、实际 PDF 和数据库始终在 Git 忽略范围内。
