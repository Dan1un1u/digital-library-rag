# B：索引与检索交接

**接收方必读：交付内容不提供可用密钥。真实建库、向量检索及混合检索需要接收方自行配置硅基流动 API 密钥，或自行接入符合下述接口约定的等价嵌入服务/本地模型。此前开发使用的本地密钥配置已于 2026-10-15 删除，不能依赖开发者的密钥直接运行。**

已实现共同契约 1.0 的 `Retriever`，支持关键词、向量和混合检索、年份/主题过滤、完整索引快照、重启加载以及失败保留旧索引。真实嵌入使用硅基流动 `BAAI/bge-m3`，不需要在展示服务器安装模型或配置显卡。调用方式按用户明确选择采用外部接口。

## 运行环境

实际验证：Python 3.12.3；直接依赖见 `requirements.txt`。Python 3.11 尚未实测。D 尚未提供打包配置，暂用 `PYTHONPATH=src`。本机已配置的独立解释器是 `../.venv-a-review/bin/python`；以下命令均从仓库根目录执行。

新环境安装 B 的依赖：

```sh
python -m pip install -r handoff/B/requirements.txt
PYTHONPATH=src python -m pytest tests/retrieval -q
```

## 密钥和真实嵌入

接收方从自己的硅基流动账户取得 API 密钥，并在自己的环境中配置。仓库提供不含密钥的 `handoff/B/.env.example`，可按下面的步骤在本机使用：

```sh
cp handoff/B/.env.example .env
# 自行编辑 .env，在 SILICONFLOW_API_KEY= 后填入自己的硅基流动密钥。
```

环境变量支持 `SILICONFLOW_API_KEY`，也兼容 `SD_EMBEDDING_KEY`。可用 `--env-file .env` 指定接收方自己的配置文件；程序只解析键值，不执行其中的命令、不复制密钥到仓库。非空密钥依次取进程的 `SILICONFLOW_API_KEY`、进程的 `SD_EMBEDDING_KEY`、文件的 `SILICONFLOW_API_KEY`、文件的 `SD_EMBEDDING_KEY`，因此进程中的任一别名都优先于文件。Python 调用显式传入的 `api_key` 覆盖上述解析结果。

未配置有效密钥时，真实调用会明确报 `EMBEDDING_NOT_CONFIGURED`，不会借用开发者密钥或静默改成替身。已有有效索引的关键词检索和清单读取不需要模型调用；离线替身演示也不需要密钥，但不能代表真实语义检索效果。

默认接口为 `https://api.siliconflow.cn/v1/embeddings`，默认模型 `BAAI/bge-m3`、维度 1024、批次 16、超时 60 秒。模型可通过 `SILICONFLOW_EMBEDDING_MODEL` 或 `--model` 选择；替换模型须配置相应维度并重建索引，不能直接查询旧模型索引。

建库会把馆藏的规范文本块分批发送给硅基流动；查询会发送用户查询。不会上传原始 PDF、数据库、作者/年份等文献记录。此行为已经用户明确授权。HTTP 重定向被拒绝；鉴权失败、超时、限流和非法向量有明确错误，真实模式不静默使用替身。

公开配置、索引和错误中不包含密钥。模型服务未提供可固定的权重修订，`embedding_revision=null`、`revision_pinned=false`；这不能保证服务商未来换权重后仍兼容旧索引。更换服务商、模型、维度或输入处理后应重建；服务商升级时也须重新检查。不要将本地 Hugging Face 修订填成云服务修订。

### 自行使用等价替代

接收方可以自行使用其他云嵌入服务或本地多语言模型，向 `Retriever` 注入自己的适配器。适配器须提供 `encode(texts: list[str])`，按输入顺序返回可转为 NumPy 的 `n×d` 有限、非零数值矩阵；建议提供 `get_config()`，准确记录服务商、实际模型、修订和维度，不能包含密钥。已有硅基流动适配器不保证直接适用于其他服务，必要时自行实现对应服务的请求与响应转换。

替代模型应支持本项目的中英文语义检索；建库和查询必须使用相同的模型、维度及输入处理。更换服务商或模型后应重新建索引，不能直接让新模型查询旧向量。替代服务自己的密钥、运行环境及调用配置由接收方准备。

## 使用 A 的真实馆藏建索引

本机已下载 A 清单的 10 篇论文，原文件哈希全部一致；数据库位于 `data/arxiv_trial/library.sqlite`，受控文件位于 `data/arxiv_trial/raw`。A 代码仍保留在旁边的 `../lib_management_A/src`，无需修改其模块。

```sh
PYTHONPATH=src:../lib_management_A/src ../.venv-a-review/bin/python -m dlrag.retrieval.cli build --index-dir data/indexes --db data/arxiv_trial/library.sqlite --files data/arxiv_trial/raw --env-file .env --output data/retrieval_build_manifest.json
```

`--db/--files` 会调用 A 的 `list_chunks(include_indexing=True)`，并从文献记录取得完整实际切块配置。也可用独立 JSON 输入：

```sh
PYTHONPATH=src python -m dlrag.retrieval.cli build --index-dir data/indexes --chunks /path/to/chunks.json --chunking-config handoff/B/chunking_character.json --env-file /path/to/.env
```

不要重新生成合成 PDF 或改变 A 的切块参数来重用已冻结标注。运行数据不进入源码压缩包。根目录 `.gitignore` 随本次修复及源码包分发，排除 `/data/`、模型缓存、SQLite、密钥和 Python 生成文件，并保留 `.env.example`；D 合并时应一并保留这份基础规则，后续统一维护。

## 查询、重载与 C/D 接入

```sh
PYTHONPATH=src ../.venv-a-review/bin/python -m dlrag.retrieval.cli search --index-dir data/indexes --env-file .env --query '有没有不用逐字对上关键词，也能找出相关资料的方法？' --mode hybrid --top-k 5
PYTHONPATH=src ../.venv-a-review/bin/python -m dlrag.retrieval.cli search --index-dir data/indexes --query 'dual encoder' --mode keyword --year-from 2020 --year-to 2021 --topic arXiv实验 --top-k 5
PYTHONPATH=src ../.venv-a-review/bin/python -m dlrag.retrieval.cli manifest --index-dir data/indexes
```

命令中的 `--mode` 可选 `keyword/vector/hybrid`。每次调用先重载索引；关键词查询和清单读取不调用嵌入接口，因此可以不提供密钥。向量和混合查询需要网络与有效密钥。

```python
from dlrag.retrieval import Retriever
from dlrag.retrieval.embeddings import SiliconFlowEmbedding

backend = SiliconFlowEmbedding.from_env('/path/to/.env')
retriever = Retriever('data/indexes', backend, {})
manifest = retriever.load()
hits = retriever.search('如何把一句话表示成向量？', mode='hybrid', top_k=20)

# D 建库时注入 A 返回的完整配置，成功后再协调文献状态。
builder = Retriever('data/indexes', backend, {'chunking_config': document['chunking_config']})
new_manifest = builder.build(store.list_chunks(include_indexing=True))
```

`hits` 为片段级的完整 `RetrievalHit`；D 按首次出现顺序聚合文献，C 负责最后选择证据和查询改写。B 不修改文献状态；本机 10 篇文献仍为 `indexing`，由 D 在集成验收后设为 `ready`。

过滤年份包含边界，未知年份在设置年份范围时排除；主题取交集。两个检索分支都先过滤再排序。`scores` 包含 BM25、余弦、融合和重排序字段，未运行项为 null；这些分数不是答案置信概率。`matched_by` 标记片段进入的候选分支；`index_version` 表示本次使用的快照。

## 分词、融合及快照

统一词项处理为 NFKC 规范化、英文大小写折叠，保留 `BM25`、`BGE-M3` 等缩写/标识。连续中文使用相邻双字词项，孤立单字单独保留；不额外安装中文分词模型，也不自动翻译。正文、标题和主题以相同权重进入关键词索引。BM25 默认 `k1=1.5`、`b=0.75`。

向量按片段原文编码并归一化，查询使用同一适配器；小馆藏采用 NumPy 精确余弦计算。混合模式两分支默认各取 20，`top_k` 更大时扩大分支候选数；RRF 常数 60，以片段编号合并，同分按片段编号稳定排序。保留不同编号的重叠块，避免删除真实不同证据，最后由 C 控制重复内容。

每个版本保存 `manifest.json`、`chunks.json`、`lexical.json`、`vectors.npy`。完整写入成功后原子替换 `current.json`；构建或切换失败保留旧指针和内存快照，不删除旧版本。清单包含模型、维度、实际切块配置、词项处理版本、语料哈希和文件校验值。元数据变化也改变语料哈希，需要重建。

构建、加载、查询使用实例互斥锁，D 还应按共同规格维护应用层单进程锁。不要启用多个工作进程。坏向量、错误模型、损坏文件或非法配置明确报错；加载失败不覆盖已经载入的内存快照。

`corpus_hash` 表示规范文本和元数据的语料身份；`artifacts` 表示各落盘文件的完整性。本版 `chunks.json` 正好以同一规范序列化写入，因此其文件哈希与 `corpus_hash` 相等；保留两者以满足各自的契约字段用途。

## D 的错误映射

所有模块异常均为本模块的 `ProjectError`，具有字符串属性 `code/message`。D 按属性映射，不要求与其他模块的异常类相同。以下为非问答接口的接入映射，错误体使用共同结构 `{"error":{"code":"...","message":"..."}}`。

| 错误码 | 建议 HTTP 状态 | 含义 |
|---|---:|---|
| `INVALID_REQUEST` | 422 | 查询、过滤、切块、评估参数或适配器配置非法 |
| `INDEX_NOT_READY` | 503 | 索引缺失、损坏，或评估期间发生版本切换 |
| `EMBEDDING_NOT_CONFIGURED` | 503 | 缺密钥、鉴权失败或缺嵌入适配器 |
| `EMBEDDING_MISMATCH` | 503 | 当前模型、维度或检索配置与索引不兼容 |
| `INDEX_BUILD_FAILED` | 500 | 无法构建、写入或切换索引；旧有效索引保持可用 |
| `EMBEDDING_UNAVAILABLE` | 503 | 嵌入接口连接、超时、限流或服务拒绝请求 |
| `EMBEDDING_INVALID_RESPONSE` | 503 | 嵌入接口响应、模型身份或向量数值非法 |

`INVALID_REQUEST` 在 B 中沿用共同参数校验语义，并明确映射 422；错误码字符串属于接口边界，不依赖 D 的 Python 实现。D 装配时可直接按此表对齐。消息经过处理，不包含上游响应正文或密钥。

## 独立替身演示及评估

```sh
PYTHONPATH=src python -m dlrag.retrieval.cli demo --index-dir /tmp/lib-management-b-demo --backend fake --query BM25 --mode hybrid
PYTHONPATH=src ../.venv-a-review/bin/python -m dlrag.retrieval.cli evaluate --index-dir data/indexes --env-file .env --questions handoff/B/candidate_questions.jsonl --output evaluation/retrieval/arxiv_trial
```

替身只用于接口、排序和故障测试；演示明确标记为 `fake`。真实模式须显式使用服务适配器，不会自动退出或进入替身。评估输出每题三模式完整结果、耗时、索引版本及指标表。指标及耗时按 `split` 与 `mode` 分别汇总，不合并开发集和测试集；`metrics.csv` 含 `split` 列，`summary.json` 包含各集合题数。只出现一个集合时仅写该集合；空题集保留表头，不生成成绩行。直接调用 `evaluate` 与命令行均要求整数 `top_k` 为 10–50，避免把不足 10 条的检索结果报告成 Recall@10。

已运行 15 道中文日常表达候选题的真实服务实验。候选题附有真实文献/片段编号与参考要点，但属于 AI 提议标注，全部 `usable_for_evaluation=false`、待 D 人工复核；正式 Hit@5、Recall@5/10 因而留空。未指定该扩展字段的共同题集，可按其提供的真实标注计算指标；明确标记不适用的题永不计分。仅用开发集调参，不把返回结果当作命中，不把编号存在当作语义支持。

## 中英文需求及剩余事项

B 任务书第 19 行提到中英文语料及 BGE-M3，第 60 行要求中文分词和英文缩写；总说明书有中文提问及英文检索表达。规格没有要求整库翻译或独立的跨语言达标分数。当前中文问题到英文片段的匹配由多语言向量完成；纯关键词不自动解决词汇翻译，C 可按职责改写查询并保留失败回退。

真实实验已出现关键词分支为空、向量匹配到不同相关论文、以及高排名片段偏离候选标注的情况，见 `evaluation/retrieval/analysis.md`。多语言模型能够运行不代表每题正确。正式成绩、题集冻结、A 的正文顺序复核、C/D 完整集成尚待相应成员完成。
