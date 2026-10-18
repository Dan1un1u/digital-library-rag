# A：馆藏与内容处理交接

A 模块实现完整 PDF → 页面 → Chunk → SQLite 流程，遵守共同契约 1.0。LibraryStore 的全部约定方法已实现，不依赖 B/C/D。真实馆藏未提供；当前验收使用 3 个明确标记的合成 PDF 与异常测试样例。

## 环境与安装

建议 Python 3.11+；实际已验证 Python 3.13.5。直接依赖版本见 requirements.txt；未实测 Python 3.11。仓库尚无 D 的打包配置，使用 PYTHONPATH=src。

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r handoff/A/requirements.txt
PYTHONPATH=src .venv/bin/python -m pytest tests/ingestion -q
```

## 最小独立演示

仓库自带 tests/ingestion/samples 下 3 个合成 PDF、manifest.json，不是学术馆藏。

```sh
PYTHONPATH=src .venv/bin/python -m dlrag.ingestion.cli batch --db data/library.sqlite --files data/raw --manifest tests/ingestion/samples/manifest.json --options handoff/A/chunking_character.json
PYTHONPATH=src .venv/bin/python -m dlrag.ingestion.cli documents --db data/library.sqlite --files data/raw
PYTHONPATH=src .venv/bin/python -m dlrag.ingestion.cli chunks --db data/library.sqlite --files data/raw > data/chunks.json
PYTHONPATH=src .venv/bin/python -m dlrag.ingestion.cli report --db data/library.sqlite --files data/raw --output evaluation/ingestion/local
```

重新生成测试资料：`python3 tests/ingestion/synthetic.py --output tests/ingestion/samples`。重新生成会产生不同 PDF 字节/哈希，不应在冻结标注后重生成。单页、多页、跨页句子、重复页眉页脚与长段落均有覆盖。

## 单文件与真实资料批量导入

复制 metadata_template.json，人工填写元数据后执行：

```sh
PYTHONPATH=src .venv/bin/python -m dlrag.ingestion.cli ingest --db data/real-library.sqlite --files data/real-raw --pdf /path/to/paper.pdf --metadata /path/to/metadata.json --options handoff/A/chunking_character.json
PYTHONPATH=src .venv/bin/python -m dlrag.ingestion.cli batch --db data/real-library.sqlite --files data/real-raw --manifest /path/to/manifest.json --options handoff/A/chunking_character.json
```

manifest 为 JSON 数组，file 路径相对于 manifest 所在目录解析；格式：

```json
[{"file":"paper.pdf","metadata":{"title":"人工核验的标题","authors":[],"year":null,"topics":["信息检索"],"language":"unknown","source_url":null,"rights_note":"待人工确认"}}]
```

metadata 只接受 title/authors/year/topics/language/source_url/rights_note。作者、主题为字符串数组；年份可空；语言为 zh/en/mixed/unknown。缺标题用文件名并标待核验，缺权限说明写待人工确认。程序不猜作者或年份，也不声明资料已授权。

批量导入逐文件处理，失败项返回 error，其余继续；任一项失败时进程返回 1。源 PDF、数据库、tokenizer 缓存属于运行数据，不提交到 Git。

## 切块与计数

character 示例配置：每块最大 1200 字符，强制拆分长段时重叠最多 150 字符；token_count=null、char_count=实际字符数。明确按字符计数，不报告为 tokens。

token 示例配置：tiktoken:cl100k_base、tiktoken 0.14.0、最大 400 tokens、强制拆分时重叠最多 50 tokens。首次获取编码表可能联网，只下载编码表，不发送馆藏文本；设置 TIKTOKEN_CACHE_DIR 可指定缓存。离线时需预热编码表缓存。不可用时报 TOKENIZER_NOT_CONFIGURED，不静默切换字符模式。cl100k_base 是已支持的真实 tokenizer，不等同于所有 embedding 模型的分词器。

```sh
PYTHONPATH=src .venv/bin/python -m dlrag.ingestion.cli batch --db data/token-library.sqlite --files data/token-raw --manifest tests/ingestion/samples/manifest.json --options handoff/A/chunking_token.json
```

按段落优先、句子次之切分；必要时按精确子串长度预算拆分。不跨 PDF 页，页内偏移为 Python 字符半开区间；存储前验证 text == normalized_text[start:end]。稳定 Chunk ID 使用完整文件哈希、PDF 页序号与页内块序号。相同文件/配置/解析版本产生相同 ID。

一个库只允许一种切块配置，配置包含 tokenizer 名称和实际版本。B 建索引时应使用 Document.chunking_config 中的实际完整配置，避免遗漏默认值或实际 revision；character 模式 tokenizer=null。

## 状态、失败与重试

状态：uploaded → parsing → indexing。A 导入成功仍未建检索索引，不能标 ready；D 在 B 构建成功后再设置 ready。默认 list_documents/list_chunks 仅服务 ready；B 用 list_chunks(include_indexing=True) 取建库候选。

同一文件重复导入不新增记录或 Chunk；元数据冲突保留现有值并发出 warning。已有成功解析文件改配置时报 CHUNK_CONFIG_MISMATCH。坏 PDF、加密 PDF报 INVALID_PDF；全空或全扫描报 NO_EXTRACTABLE_TEXT；扫描页/空白页也有独立诊断。

解析失败保存 failed 与 code/message，页面和块事务回滚；相同失败文件再次 ingest 会报错并指引显式重试，不把 failed 当成功。调用 retry_document 或 CLI retry，例如修正错误计数模式后：

```sh
PYTHONPATH=src .venv/bin/python -m dlrag.ingestion.cli retry --db data/library.sqlite --files data/raw --doc-id d_实际完整哈希 --options handoff/A/chunking_character.json
```

仅允许重试未存过内容的解析失败。已有内容的索引失败由 D/B 重试构建索引。

## 离线重建与压缩包迁移

配置变动需要新数据库，不覆盖旧库；用原始馆藏 manifest 重建。CLI rebuild 拒绝已存在的目标 DB。

```sh
PYTHONPATH=src .venv/bin/python -m dlrag.ingestion.cli rebuild --db data/rebuilt.sqlite --files data/rebuilt-raw --manifest /path/to/manifest.json --options handoff/A/chunking_token.json
```

D 在 B 新索引验收后切换库/索引。切块改变后需重新核验题目证据 ID 和偏移，冻结测试集前完成。

关闭应用后一起复制 library.sqlite 与 raw 文件夹。SQLite 内保存受控文件名相对路径；目标电脑用新的 db_path/files_dir 实例化即可。已验证重启与目录迁移。本版 SQLite 不启用 WAL；D 需协调单进程导入、索引和查询的互斥锁。

## B/D 接入

```python
from dlrag.ingestion import LibraryStore
store = LibraryStore('data/library.sqlite', 'data/raw')
doc = store.ingest_pdf('tests/ingestion/samples/single.pdf',
    {'title': '合成测试资料', 'rights_note': '本项目生成的合成测试资料'},
    {'count_mode': 'character'})
chunks = store.list_chunks(include_indexing=True)  # B 构建索引
# retriever.build(chunks) 成功后由 D 执行：
store.set_document_status(doc['doc_id'], 'ready')
source = store.get_file_path(doc['doc_id'])  # D 的受控文件服务
```

Chunk.document 元数据快照联表生成；printed_page 暂不推断，保存 null，不混用文件页序号。ProjectError 具有 code/message，D 可按属性映射。get_page、register_document、save_parsed_content 为扩展入口。

## 解析质量与候选题

保留原始文本、规范文本及解析版本。保守合并视觉断行和空白，不删除术语标点，不擅自合并断字。重复页边缘页眉页脚可移除；单页不自动移除。位置块检测双栏并标 MULTI_COLUMN_REVIEW_REQUIRED，排序使用 PyMuPDF 的位置顺序，不保证任意双栏语义顺序。图像页不启动 OCR，复杂表格不做语义推理。

report 导出 catalogue.csv、parsing_quality.csv；自动偏移检查与人工正文顺序复核明确分开。仓库 evaluation/ingestion 记录的是本次合成测试，不是真实学术资料质量。

```sh
PYTHONPATH=src .venv/bin/python -m dlrag.ingestion.cli questions --db data/real-library.sqlite --files data/real-raw --output handoff/A/candidate_questions.jsonl
```

命令生成 10 道 exact + 5 道 multi_document 草稿，空 ID、usable_for_evaluation=false，需人工按真实馆藏调整问题、填写要点与证据分组，再由 C 复核。重新运行会覆盖目标模板，请用新路径保留已标注文件。

剩余人工材料：确定馆藏范围与权限，先抽查 10 篇真实 PDF，再扩至 50–100 篇；核对作者/年份、双栏/页眉、正文顺序；补真实题目与片段标注，由 C 复核。这些未执行，没有用合成资料替代真实评估。

## 已完成的 arXiv 试验

现已下载并实际导入 10 篇 arXiv 论文：156 页、732 块，偏移及去重检查通过。位置：data/arxiv_trial；结果：evaluation/ingestion/arxiv_trial。parser v2 修复真实 PDF 中空字符导致的数据库长度检查失败。上文“真实馆藏未提供”为首次交付时状态；人工阅读顺序检查及真实题目标注仍待完成。
