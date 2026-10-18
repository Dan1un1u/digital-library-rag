# 专题数字图书馆

基于 PDF 馆藏的文献检索、元数据候选识别和带原文引用的问答原型。应用使用 FastAPI 与 Streamlit，支持关键词检索、向量检索及混合检索。

当前版本已接入本机 BGE-M3 FP16 和通过 CLIProxyAPI 调用的 GPT-6 Luna。

| 功能 | 当前实现 |
| --- | --- |
| 文献解析与入库 | 按页提取、字符切分、SQLite 馆藏管理 |
| 文献与查询向量 | 本机 BGE-M3 FP16，1024 维 |
| 查询规划与证据回答 | GPT-6 Luna，结构化输出与引用校验 |
| 候选重排、支持句定位、要点关联 | GPT-6 Luna 的结构化相关性评分 |
| PDF 元数据候选识别 | 前两页图像与文字联合识别，保留人工核对 |
| 交互界面 | 馆藏浏览、搜索问答、PDF 上传与管理 |

Luna 推理使用云端服务和订阅账户的权限、额度；CLIProxyAPI 和 BGE 在本机运行。LLM 重排分数属于模型判断，需要通过正式测试集评估，不能直接等同于专用重排模型的性能。

## 目录

```text
app/                    应用源码、自动测试、评估入口及原有文档
scripts/                本机部署控制、索引重建及联调检查
services/bge-m3/        独立 BGE 服务的部署源码快照
services/cliproxyapi/   CLIProxyAPI 官方发行包下载校验与本机控制脚本
tools/                  源码导出和发布前检查
Start-Library.ps1        启动本机部署
Run-Tests.ps1            运行离线自动测试
```

服务目录保存部署脚本，不包含第三方可执行文件、模型权重或认证文件。独立服务实际路径默认是 `D:/bge-m3-local/` 和 `D:/cliproxyapi-local/`；服务脚本及本机联调脚本含这些路径，换机器时需要调整。

## 环境与离线演示

应用支持 Python 3.11–3.12，现有部署使用 Python 3.12。以下命令在 Windows PowerShell 的仓库根目录执行：

```powershell
py -3.12 -m venv .venv
& .\.venv\Scripts\python.exe -m pip install -e ".\app[dev]"

foreach ($folder in @('logs', 'reports', 'evidence', 'runtime')) {
    New-Item -ItemType Directory -Path $folder -Force | Out-Null
}
if (-not (Test-Path -LiteralPath 'app/.env')) {
    Copy-Item -LiteralPath 'app/.env.example' -Destination 'app/.env'
}

& .\.venv\Scripts\python.exe app/scripts/seed_demo.py --mode mock --data-dir "$PWD/runtime/mock"
.\Start-Library.ps1 -Mode mock
```

离线演示界面为 `http://127.0.0.1:18502/`，后端为 `http://127.0.0.1:18001/`。演示使用合成 PDF、明确标记的模拟向量和脚本问答，验证流程与界面。

## 真实模式

先分别准备独立 BGE 服务与 CLIProxyAPI，并在官方登录页完成单独授权。应用配置写入本机 `app/.env`：

```dotenv
APP_MODE=real
EMBEDDING_PROVIDER=local_bge
EMBEDDING_BASE_URL=http://127.0.0.1:18080/v1
EMBEDDING_MODEL=BAAI/bge-m3
EMBEDDING_DIMENSION=1024
EMBEDDING_REVISION=5617a9f61b028005a4858fdac845db406aefb181

LLM_PROVIDER=cliproxyapi
LLM_BASE_URL=http://127.0.0.1:8317/v1
LLM_MODEL=gpt-6-luna
LLM_API_KEY=<本机代理的客户端口令>
LLM_REASONING_EFFORT=none
LLM_CLIENT_FACTORY=dlrag.api.qa_factory:create_client
LLM_CONTEXT_WINDOW_TOKENS=262144
LLM_MAX_OUTPUT_TOKENS=2600
LLM_TIMEOUT_SECONDS=120

QA_RERANK_PROVIDER=llm
QA_RERANK_MODEL=gpt-6-luna
QA_RERANK_TIMEOUT_SECONDS=90
METADATA_API_PROVIDER=cliproxyapi
METADATA_API_MODEL=gpt-6-luna
METADATA_API_TIMEOUT_SECONDS=90
```

使用 Luna 时移除 `LLM_ENABLE_THINKING`，使用独立的 `LLM_REASONING_EFFORT` 配置。导入有权使用的 PDF 后，统一重建真实向量索引，再启动：

```powershell
.\Start-Library.ps1 -Mode real
```

界面为 `http://127.0.0.1:18501/`，后端为 `http://127.0.0.1:18000/`。启动入口先确认两项本地服务就绪，再启动图书馆；未设置开机自启。

本机代理口令不同于 OpenAI 平台签发的 API Key。OAuth 凭证只由 CLIProxyAPI 的独立认证目录保存，应用只接收本机代理的客户端口令。

## 验证状态

2026-10-18 的现有部署验证结果：

- 330 项离线自动测试通过。
- 16 项真实联调检查通过，覆盖真实向量/混合检索、Luna 文本与图像输入、LLM 重排、双语检索、带引用问答、支持句定位、要点覆盖及原文访问。
- 已为当时馆藏的 14 篇文献、935 个片段建立本机 BGE 索引。

这些是部署与开发验证；正式检索质量评测仍需人工复核数据集。仓库保留少量自制合成 PDF 作为测试夹具，实际文献和索引未上传。

```powershell
.\Run-Tests.ps1
```

`scripts/verify_local_integration.py` 会调用真实 Luna 并使用订阅额度，当前馆藏断言对应上述 14 篇、935 个片段；扩大或更换馆藏后需要更新该检查。

## 数据与本机部署

仓库不保存 `.env`、OAuth 凭证、GitHub 令牌、模型权重、真实 PDF 馆藏、数据库、索引、虚拟环境或运行日志。重新克隆后需要配置本机环境与数据。

这份源码来自已完成本地模型接入的独立部署副本；本机运行实例仍位于：

`D:/llm_exp/digital-library/workspace/deployments/lib_management_v1_20261018/`

进一步操作见[本地模型使用说明](本地模型使用说明.txt)、[BGE 部署说明](services/bge-m3/README.txt)和[CLIProxyAPI 部署说明](services/cliproxyapi/README.txt)。`app/README.md` 与 `app/docs/` 保留原项目的接口、模块交接和历史版本说明。

馆藏扩充使用[入库与白盒验证流程](docs/workflow/catalog-ingestion.md)和[COL-001 工作项](docs/work-items/COL-001.md)，通过独立分支、Draft PR 和提交绑定的执行证据记录贡献。实际文献批次完成并复核后再决定合并。
