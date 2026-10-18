BGE-M3 本地 FP16 向量服务

部署位置：D:/bge-m3-local/
WSL 路径：/mnt/d/bge-m3-local/
运行平台：现有 Ubuntu-22.04 / WSL2，使用 RTX 5070 Ti Laptop GPU。

本目录包含模型、服务代码、新虚拟环境、日志、测试与启动脚本。
它没有在 D:/llm_exp/ 下创建新项目；现有环境只作为依赖来源读取。

一、服务入口
健康与硬件状态：http://127.0.0.1:18080/health
API 文档：http://127.0.0.1:18080/docs
模型列表：http://127.0.0.1:18080/v1/models
向量接口：POST http://127.0.0.1:18080/v1/embeddings

只监听 127.0.0.1，不需要云端 API Key。服务启动后，模型加载和推理均使用本地文件。
该服务只生成 dense 文本向量；没有大模型生成、重排序、sparse 或 ColBERT 输出。

二、Windows 下使用
PowerShell：

Set-Location -LiteralPath 'D:/bge-m3-local'
./Start-BGE.ps1
./Status-BGE.ps1
./Verify-BGE.ps1
./Stop-BGE.ps1

启动脚本通过 WSL 加载模型并后台运行；无需保持可见的控制台。
未设置开机自启；重启 Windows 或终止 WSL 后，重新运行 Start-BGE.ps1。
首次加载也会读取复用环境中的依赖，可能需要约 1～2 分钟；脚本会等待就绪。
只运行一个服务进程。启动和停止均检查所属进程与身份，不结束其他项目进程。
端口冲突时明确报错。

三、调用示例
以下 Python 可在 Windows 或 WSL 中运行，环境需装有 requests：

import requests
client = requests.Session()
client.trust_env = False
response = client.post(
    'http://127.0.0.1:18080/v1/embeddings',
    json={
        'model': 'BAAI/bge-m3',
        'input': ['数字图书馆支持文献检索。', 'A digital library supports literature search.'],
        'encoding_format': 'float'
    },
    timeout=60
)
response.raise_for_status()
vectors = [item['embedding'] for item in response.json()['data']]
print(len(vectors), len(vectors[0]))

预期输出：2 1024。
还可运行本目录 example_client.py，查看两段中英文文本的向量相似度。

四、模型与精度
上游：BAAI/bge-m3，官方 Hugging Face 仓库。
版本：5617a9f61b028005a4858fdac845db406aefb181。
source_manifest.json 记录下载文件哈希；大型权重与官方 LFS SHA256 对照。
models/bge-m3-source/ 保存原始 FP32 权重与配置。
models/bge-m3-fp16/ 保存转换后的 float16 safetensors 权重和 tokenizer。
FP16 转换保留 dense encoder，包括其原有 pooler 参数；实际向量取最后层 CLS。
服务在 CUDA 上以 FP16 运行；CLS 向量以 float32 做 L2 归一化并转成 JSON 数字返回。
输出浮点数不代表模型权重是 FP32；/health 会显示实际权重精度与 GPU。
分词器使用官方 XLM-RoBERTa 配方；显式关闭不适用于该模型的 Mistral 正则修补。

五、环境复用
当前激活环境：.venv-wsl/，Python 3.10。
通过该环境的 reused_gpu_readonly.pth 引用已有 GPU 和 ML 包：
/mnt/d/llm_exp/htp-research/workspace/tools/python-gpu-cu128-v1/lib/python3.10/site-packages
/mnt/d/llm_exp/htp-research/shared/env/base-v1/python-env/lib/python3.10/site-packages

PyTorch 2.9.1+cu128、Transformers 4.57.6、CUDA 12.8 等直接复用。
FastAPI、Uvicorn 及缺少的接口依赖安装在本目录 .venv-wsl 中。
这些引用路径是运行依赖，移动或删除被引用的旧环境前需先迁移依赖。
精确版本与包位置记录在 reports/environment.json 和 reports/requirements-installed.txt。

维护时从本目录的虚拟环境执行 pip，不要向被引用环境中安装或升级包。
cache/unused-windows-setup/ 是未采用的 Windows 安装准备资料，不用于启动服务。

六、请求限制与显存控制
模型输出维度固定为 1024，不支持任意缩减 dimensions。
每次请求最多 64 条文本；每条最多 8192 个实际 tokenizer tokens（包含特殊 token）。
超过长度会返回 422，明确要求先切分；不会静默截断。
默认最多每小批 4 条，并按 padding 后 token 数控制小批大小。
GPU 推理由锁串行执行；不因收到多个 HTTP 请求而重复加载模型。
显存不足返回 503，不静默改用 CPU 或模拟向量。
可在 config.json 调整批量大小，再重启服务；长文本应先减小批量。

七、验证与证据
reports/fp16_conversion.json：实际参数量、FP16 权重字节、输出文件 SHA256。
reports/environment.json：实际 Python、GPU、依赖位置和 FP16 矩阵运算检查。
reports/verification.json：真实接口、中文/英文语义样例、校验、并发与耗时。
reports/fp32_comparison.json：原始 FP32 编码器与 FP16 服务的小样本数值比较。
reports/long_context.json：8192 token 输入与超长拒绝边界的真实 GPU 检查。
reports/windows_verification.json：Windows 访问与启动停止脚本的实际检查。
需要复查长度边界时，可运行 ./Verify-Long-Context.ps1。
logs/：下载、安装、转换与服务日志。

语义样例及延迟只属于本机开发验证，不代表正式检索质量评测或固定性能保证。

八、与图书馆项目的关系
本次仅部署独立向量服务，没有修改图书馆源码、数据库或既有索引。
图书馆后续需要增加本地 embedding 适配器，再连接本接口。
即便模型名和维度相同，切换云端到本地后也建议统一重新生成馆藏向量并重建索引，
同时保存新的模型来源、预处理与索引身份，避免混用。
文字回答模型及语义重排服务仍是单独组件。

九、上游文档
模型：https://huggingface.co/BAAI/bge-m3
官方代码：https://github.com/FlagOpen/FlagEmbedding
