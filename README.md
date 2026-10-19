# 专题数字图书馆

基于 PDF 馆藏的文献检索、元数据候选识别和带原文引用的问答原型。应用使用 FastAPI 与 Streamlit，支持关键词检索、向量检索及混合检索。

真实模式沿用最初项目的硅基流动接口。成员使用自己的服务密钥；项目不需要部署本机模型服务或登录个人订阅代理。图文操作见[使用手册](docs/user-guide/使用手册.md)及[Word 版](docs/user-guide/专题数字图书馆使用手册.docx)。

| 功能 | 配置示例中的模型 | 接口 |
| --- | --- | --- |
| 文献与查询向量 | BAAI/bge-m3，1024 维 | `/embeddings` |
| 查询规划与证据回答 | Qwen/Qwen3-32B | `/chat/completions` |
| 候选与支持句重排 | Qwen/Qwen3-Reranker-4B | `/rerank` |
| PDF 元数据增强识别 | Qwen/Qwen3-VL-8B-Instruct | `/chat/completions`，含页面图像 |

这些是项目预设名称；实际可调用的模型与权限以成员的服务账户为准。切换模型时须核对上下文上限，切换嵌入配置后须重建索引。

## 首次安装

支持 Python 3.11–3.12。以下命令在 Windows PowerShell 的仓库根目录执行，路径可自行选择：

```powershell
py -3.12 -m venv .venv
& .\.venv\Scripts\python.exe -m pip install -e ".\app[dev]"
if (-not (Test-Path -LiteralPath 'app/.env')) {
    Copy-Item -LiteralPath 'app/.env.example' -Destination 'app/.env'
}
```

`.env`、PDF 馆藏、数据库、索引、运行日志和虚拟环境均不提交 Git。新克隆不包含馆藏；空库启动后显示索引尚未就绪，需要先导入文献。

## 使用硅基流动真实服务

编辑本机 `app/.env`，保留示例的模型、地址和工厂配置，并至少修改：

```dotenv
APP_MODE=real
DATA_DIR=../runtime/real
API_BASE_URL=http://127.0.0.1:18000
SILICONFLOW_API_KEY=<填入自己的硅基流动密钥>
```

`LLM_API_KEY` 可以留空，问答会沿用 `SILICONFLOW_API_KEY`。四项 `*_PROVIDER` 默认均为 `siliconflow`；旧配置没有这些新增字段也能使用。具体配置、原有启动方式及索引迁移见[硅基流动部署说明](docs/deployment/siliconflow.md)。

```powershell
.\Start-Library.ps1 -Mode real
.\Status-Library.ps1 -Mode real
.\Stop-Library.ps1 -Mode real
```

界面为 `http://127.0.0.1:18501/`，后端为 `http://127.0.0.1:18000/`。启动入口只管理本项目的后端和界面，首次启动自动创建日志与运行目录。真实模式尊重 `app/.env` 中的数据路径，进程环境变量优先；相对路径以 `app/` 为起点。

## 离线演示

无需服务密钥，使用合成 PDF、模拟向量和脚本问答演示流程：

```powershell
& .\.venv\Scripts\python.exe app/scripts/seed_demo.py --mode mock --data-dir "$PWD/runtime/mock"
.\Start-Library.ps1 -Mode mock
```

界面为 `http://127.0.0.1:18502/`，后端为 `http://127.0.0.1:18001/`。MOCK 始终使用独立的 `runtime/mock/`，不混入真实模式的库和密钥；模拟结果不能作为真实模型效果。

## 测试与工作追溯

```powershell
.\Run-Tests.ps1
```

离线测试使用合成夹具和临时库，结果保存在本工作目录的 `reports/`。测试与修复任务使用独立分支、工作目录和 PR，见[任务隔离流程](docs/workflow/test-task-isolation.md)及[入库与白盒验证流程](docs/workflow/catalog-ingestion.md)。

- [DEP-001 本机接入移出交付项目及硅基流动兼容验证](docs/validation/DEP-001/README.md)
- [COL-001 用户指定馆藏与元数据修复记录](docs/validation/COL-001/README.md)
- [COL-002 跨学科检测与后续修复记录](docs/validation/COL-002/README.md)
- [UI-001 问答进度修复验收](docs/validation/UI-001/acceptance-20261019.json)
- [DOC-001 原版图文手册验收](docs/user-guide/acceptance-20261019.json)

PR1–PR7 已合并；历史记录中的“候选”“尚未合并”、模型名称和端口保留当时身份，不代表当前源码或旧实例的部署状态。历史验证曾使用开发者个人环境；其原始输入哈希、失败记录、截图和结果不改写，也不作为当前云端在线验收成绩。

## 项目目录

```text
app/                 应用源码、原有接口文档、测试与配置示例
scripts/             项目启停、离线测试及通用检查入口
tools/               馆藏验证与文档生成工具
docs/deployment/     硅基流动部署说明
docs/validation/     按工作项隔离的历史与新增验证记录
```

个人环境的模型权重、代理程序、认证文件和接入脚本在各自本机维护，不属于项目发布内容。保留的原接口文档见 `app/README.md` 与 `app/docs/`。
