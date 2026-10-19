# 硅基流动部署说明

真实模式使用最初项目的硅基流动服务。依照根目录 README 创建虚拟环境和本机 `app/.env` 后，填写自己的密钥即可配置服务；不需要开发者本机的 D 盘目录。

## 配置

保留 `app/.env.example` 中的原接口地址和模型配置：

```dotenv
APP_MODE=real
DATA_DIR=../runtime/real
API_BASE_URL=http://127.0.0.1:18000
SILICONFLOW_BASE_URL=https://api.siliconflow.cn/v1
SILICONFLOW_API_KEY=<自己的密钥>
EMBEDDING_MODEL=BAAI/bge-m3
EMBEDDING_DIMENSION=1024
EMBEDDING_REVISION=
LLM_BASE_URL=https://api.siliconflow.cn/v1
LLM_MODEL=Qwen/Qwen3-32B
LLM_API_KEY=
LLM_ENABLE_THINKING=false
LLM_CLIENT_FACTORY=dlrag.api.qa_factory:create_client
QA_RERANK_MODEL=Qwen/Qwen3-Reranker-4B
METADATA_API_MODEL=Qwen/Qwen3-VL-8B-Instruct
```

其余预算、超时和布尔配置沿用完整示例。模型名称是本项目预设，账户需要具备对应模型的调用权限。

`LLM_API_KEY` 留空时回退使用 `SILICONFLOW_API_KEY`；嵌入还保留原 `SD_EMBEDDING_KEY` 别名。增强识别和语义重排使用 `SILICONFLOW_API_KEY`。`LLM_PROVIDER`、`EMBEDDING_PROVIDER`、`QA_RERANK_PROVIDER`、`METADATA_API_PROVIDER` 只接受 `siliconflow`，也可在旧配置中全部省略。

云端嵌入服务没有项目可固定的权重修订，`EMBEDDING_REVISION` 留空。不要复制他人的私有 `.env`、本地模型修订、代理口令或订阅认证文件。

## 启动与数据路径

在仓库根目录运行：

```powershell
.\Start-Library.ps1 -Mode real
```

一键入口提供后端 18000 和界面 18501，只启动应用本身；`runtime/` 与 `logs/` 自动创建。真实模式的数据路径优先使用进程环境变量，其次为 `app/.env`，留空时使用本项目 `runtime/real/`。`DB_PATH`、`FILES_DIR`、`INDEX_DIR` 可分别指定；相对路径以 `app/` 为起点。MOCK 始终使用独立 `runtime/mock/`。

端口已被其他进程占用时，入口会停止本次启动并报错，不会终止其他应用。关闭项目用 `Stop-Library.ps1 -Mode real`，查询状态用 `Status-Library.ps1 -Mode real`。

原有应用启动脚本仍保留。若使用它们，在两个已激活项目虚拟环境的终端分别运行：

```powershell
.\app\scripts\start_api.ps1
.\app\scripts\start_ui.ps1
```

这组原有入口使用后端 8000、界面 8501，须同时将 `app/.env` 的 `API_BASE_URL` 改为 `http://127.0.0.1:8000`。不要混用两组入口的地址。

## 导入与索引

新克隆不包含真实 PDF 和索引。启动空库时，健康检查显示索引未就绪是正常的；按使用手册导入获准使用的 PDF，并核对元数据与正文后再提问。

改用另一嵌入服务、权重、精度或输入预处理配置后，旧索引不能直接沿用。先停止后端，在同一份配置与数据目录下重建：

```powershell
.\Stop-Library.ps1 -Mode real
Push-Location app
try {
    & ..\.venv\Scripts\python.exe scripts/seed_demo.py --mode real --rebuild-only
} finally {
    Pop-Location
}
.\Start-Library.ps1 -Mode real
```

重建会调用已配置的真实嵌入服务。不要将旧演示数据目录作为默认迁移目标；维护自己的馆藏副本与备份。

## 验证范围

DEP-001 验证原配置装配、四项云端 HTTP 契约、HTTPS 校验、无本机服务依赖的启动入口和隔离数据路径。离线请求使用拦截响应，没有使用成员真实密钥；启动验证不调用模型，因此不代表硅基流动账户、网络或模型当前可用性已在线验收。
