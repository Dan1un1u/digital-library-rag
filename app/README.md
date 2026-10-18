# 专题数字图书馆

> 已修复 **v1.5.1 页面切换与任务进度重置**：新任务及主/二级页面切换会清除上一轮进度；更换或移除 PDF 会清除旧识别预填。详见[修改文档 v1.5.1](docs/changes/v1.5.1_页面切换与任务进度重置.md)。

> 已更新 **v1.5 API 辅助识别与上传进度**：图像与文字联合识别完整标题、作者等信息；识别和导入均显示阶段进度与用时。详见[修改文档 v1.5](docs/changes/v1.5_API辅助识别与上传进度.md)。全量自动测试 307 项通过。

> 已更新 **v1.4 馆藏展示与上传界面**：学科分类饼图、PDF 首页封面资源卡片、上传优先的管理页面及二级系统设置。详见[修改文档 v1.4](docs/changes/v1.4_馆藏展示与上传界面优化.md)。全量自动测试 300 项通过。

> 已部署 **v1.3 回答覆盖与相关性修复**：机制补充查询、语义重排、问题要点检查、独立句子定位，以及完整机制论文。详见[修改文档 v1.3](docs/changes/v1.3_回答覆盖与相关性修复.md)。

A/B/C/D 已合并：PDF 入库、三种检索、单轮证据问答、FastAPI、Streamlit 和评估入口。2026-10-18 根据 `lib_management_D_v2_20261017.zip` 更新并在本机复测。

**工程链路已可运行，正式质量验收仍未全部完成。** 307 项自动测试通过；原始 12 篇真实论文已建索引（853 块，BAAI/bge-m3），后续上传的文献按当前馆藏显示。60 道候选题尚未人工复核和冻结，真实语义指标不能计分。最新上传验证见 v1.5 修改文档，界面验证见 v1.4，问答开发验证见 v1.3，历史核验见[需求核验报告](evaluation/reports/update_20261018/requirements_review.md)。

## 环境与安装

完整工程支持 Python 3.11–3.12，本机实际使用独立 `.venv` 的 Python 3.12.15。NumPy 固定 1.26.4，因此完整工程不支持 Python 3.13；C 原先的 `handoff/C/.venv` 仅用于其独立开发，不用于启动本应用。

本机已安装，直接使用 `.venv/Scripts/python.exe`。换机器时先安装 Python 3.11/3.12，确认 `python --version` 后，从含 pyproject.toml 的项目根目录执行：

```powershell
python -m venv .venv
.venv/Scripts/python.exe -m pip install -e ".[dev]"
# 仅首次配置且不存在 .env 时复制，保留已有配置。
if (-not (Test-Path -LiteralPath .env)) { Copy-Item .env.example .env }
$env:PYTHONUTF8='1'
$env:TIKTOKEN_CACHE_DIR="$PWD/data/tokenizer-cache"
.venv/Scripts/python.exe -m pytest -q
```

首次运行 A 的 token 模式测试可能下载 tiktoken 编码表；普通 mock 演示采用明确的字符模式。依赖锁定于 pyproject.toml，本机完整安装清单见 `evaluation/reports/update_20261018/requirements-lock.txt`。

## 离线演示与启动

`.env.example` 为无密钥 mock 示例，本机 `.env` 当前为 real；real/mock 数据分目录。运行离线演示时显式指定模拟目录：

```powershell
$env:APP_MODE='mock'
$env:DATA_DIR="$PWD/data/mock"
.venv/Scripts/python.exe scripts/seed_demo.py
.venv/Scripts/python.exe -m dlrag.api.main
```

另开一个终端，仍从项目根目录执行：

```powershell
.venv/Scripts/python.exe -m streamlit run src/dlrag/ui/app.py --server.address 127.0.0.1 --server.port 8501 --server.headless true --browser.gatherUsageStats false
```

后端 [健康检查](http://127.0.0.1:8000/health) 和 [接口文档](http://127.0.0.1:8000/docs)，界面为 [本机 8501](http://127.0.0.1:8501)。也可使用 `scripts/start_api.ps1` 与 `scripts/start_ui.ps1`。始终只运行一个后端进程；停止时在各自终端按 Ctrl+C。

mock 使用真实 A/B 实现、合成 PDF、fake embedding 和 D 的脚本问答，界面明确标记。试用“BM25”“那个系统”“证据不足”“超时”可以重现四种状态。mock 不代表真实问答质量。

## 上传时自动识别

在“管理与实验”页选择PDF，会自动识别并预填标题、作者、年份候选、语言与来源；核对或修改后再点击“导入并建立索引”。作者每行一位。识别在本机完成，不调用外部模型；预览不写馆藏、不建索引。换文件自动重新识别，同一文件保留人工修改，失败可点“重新识别文献信息”。

当前切分为按页、段落优先的字符策略：每块最多1200字符；段落边界优先，其次句末，仅强制切断长段/长句时最多重叠150字符。另支持真实tokenizer模式，当前未启用。完整规则、识别限制与新预览接口见[PDF自动识别与切分策略](docs/pdf_import.md)。

## 切换真实模式

C 的 QAEngine 与 SiliconFlowLLM 已接入，工厂是 `dlrag.api.qa_factory:create_client`。停止 mock 后端，在本机私有环境或 `.env` 中设置：

```dotenv
APP_MODE=real
DATA_DIR=data/real_arxiv
SILICONFLOW_API_KEY=<自己的嵌入密钥>
LLM_API_KEY=<自己的生成密钥，可留空以复用 SILICONFLOW_API_KEY>
LLM_BASE_URL=https://api.siliconflow.cn/v1
LLM_MODEL=Qwen/Qwen3-32B
LLM_ENABLE_THINKING=false
LLM_CLIENT_FACTORY=dlrag.api.qa_factory:create_client
LLM_TIMEOUT_SECONDS=90
LLM_MAX_OUTPUT_TOKENS=1800
LLM_CONTEXT_WINDOW_TOKENS=32768
QA_CONTEXT_BUDGET_TOKENS=24000
QA_SEMANTIC_RERANK_ENABLED=true
QA_RERANK_MODEL=Qwen/Qwen3-Reranker-4B
```

`EMBEDDING_MODEL=BAAI/bge-m3`、`EMBEDDING_DIMENSION=1024`，云模型修订留空。更换模型须核对上下文并重建不兼容的向量索引。真实模式缺模型/索引明确返回未就绪，不回退 mock。

本机已有十二篇公开论文：原十篇加 Transformer 与 Longformer 两篇机制论文。原十篇可按以下命令恢复；新增两篇的来源、元数据与导入记录见 v1.3 文档：

```powershell
.venv/Scripts/python.exe evaluation/ingestion/arxiv_trial/download.py --output data/arxiv_src
.venv/Scripts/python.exe scripts/seed_real.py --source data/arxiv_src --data-dir data/real_arxiv
.venv/Scripts/python.exe -m dlrag.api.main
```

建库会将规范片段发送给嵌入服务；问答会将问题及最多60个候选片段发送给重排服务，将选中片段发送给生成服务，再将各条结论及其引用片段中的句子发送给重排服务定位支持句。不会整库上传 PDF 或数据库。资料的再分发权限和正文顺序仍需人工核验。本机 `.env` 未保存密钥，重启 real 需要自行注入。

检索现有匹配索引时 keyword 不需要服务调用；向量/混合检索与建库需要网络及嵌入密钥。已有索引的模型身份配置仍须一致。

## 评估与检查

```powershell
.venv/Scripts/python.exe scripts/run_evaluation.py --collect --dataset evaluation/dataset/questions.jsonl
.venv/Scripts/python.exe scripts/run_evaluation.py --dataset evaluation/dataset/questions.jsonl --mode mock
.venv/Scripts/python.exe scripts/run_evaluation.py --dataset evaluation/dataset/questions.jsonl --mode real
```

当前为 60 道未审核候选，最后一条命令应拒绝并保存 `not_executed.json`，不是正式成绩。按[标注指南](evaluation/dataset/annotation_guide.md)完成交叉复核、近义题分组及索引冻结后，才能运行真实评分。比较三模式用 `--retrieval-mode keyword/vector/hybrid`，比较基础 RAG 用 `--planning-enabled false/true`；其他参数须固定。

额外的真实开发链路检查（需配置 real 密钥，输出文件必须不存在）：

```powershell
.venv/Scripts/python.exe scripts/verify_real_deployment.py --data-dir data/real_arxiv --output evaluation/reports/real_smoke_new.json
```

它检查三模式、真实 C 响应、引用与受控原 PDF，不计算人工语义成绩。引用 ID 能解析不等于结论受原文支持，歧义识别和比较题仍有失败案例。回答角标可打开来源页，在提取原文和 PDF 原页预览中高亮支持句子；无法可靠定位 PDF 文字层时明确提示。原文件入口的 `#page` 跳转仍取决于浏览器，可按界面提供的 PDF 文件页号手动定位。

## 记录与交接

- [v1.3 回答覆盖与相关性修复](docs/changes/v1.3_回答覆盖与相关性修复.md)：机制检索、语义重排、问题要点核对、服务端句子定位和新增机制论文。
- [v1.2 引用角标跳转与句子高亮](docs/changes/v1.2_引用角标跳转与句子高亮.md)：按结论定位支持句子，提供原文及 PDF 原页高亮。
- [v1.1 连贯回答与实时进度](docs/changes/v1.1_连贯回答与实时进度.md)：自然段回答、逐句引用与实际阶段进度；完整测试 257 项通过。
- [最新需求核验](evaluation/reports/update_20261018/requirements_review.md)：逐项需求、实测结果和未完成项。
- [D 接手说明](handoff/D/README.md)、[验收记录](handoff/D/acceptance.md)。
- [C 工作报告](handoff/C/report.md)、[C 接口说明](handoff/C/README.md)。
- [演示步骤](docs/demo.md)、[展示安排](docs/presentation_outline.md)。
- [函数级历史说明](docs/项目结果与搭建说明.md)：保留早期设计解释，当前状态以上述新报告为准。

索引失败时保留旧版本，新文献保留 indexing 与错误；先停止后端，再在同一配置下运行 `scripts/seed_demo.py --rebuild-only` 后重启。当前应用仅用于本地可信课堂，未公开部署。运行数据在 data/，旧文件备份在 `data/update_20261018/before_update.zip`；未创建 Git 提交或推送。
