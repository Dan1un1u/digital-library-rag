"""Summarize the completed, measured deployment checks for the user."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import urllib.request

ROOT = Path(__file__).resolve().parents[1]


def read(name):
    return json.loads((ROOT / 'reports' / name).read_text(encoding='utf-8'))


conversion = read('fp16_conversion.json')
core = read('verification.json')
windows = read('windows_verification.json')
reference = read('fp32_comparison.json')
long = read('long_context.json')
environment = read('environment.json')
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
with opener.open('http://127.0.0.1:18080/health', timeout=10) as response:
    health = json.load(response)
if (core['failed'] or windows['failed'] or not reference['passed'] or not long['passed']
        or not long['official_tokenizer_parity'] or health['status'] != 'ready'
        or health['dtype'] != 'float16' or health['device'] != 'cuda:0'):
    raise RuntimeError('Deployment evidence is incomplete or a required check failed')
created = datetime.now(timezone.utc).isoformat()
(ROOT / 'reports/final_health.json').write_text(
    json.dumps({'created_at': created, **health}, ensure_ascii=False, indent=2), encoding='utf-8')
code_paths = [ROOT / 'config.json', ROOT / 'requirements-wsl.txt', ROOT / 'example_client.py',
              *ROOT.glob('*.ps1'), *ROOT.glob('app/*.py'), *ROOT.glob('scripts/*.py')]
code_manifest = [{'file': str(path.relative_to(ROOT)).replace('\\', '/'),
                  'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
                 for path in sorted(code_paths)]
(ROOT / 'evidence/deployment_code_manifest.json').write_text(
    json.dumps({'created_at': created, 'files': code_manifest}, indent=2), encoding='utf-8')
text = f'''BGE-M3 本地 FP16 部署与验证说明
生成时间（UTC）：{created}

状态：部署完成，服务运行中。
部署目录：D:/bge-m3-local/
运行环境：Ubuntu-22.04 / WSL2，新虚拟环境 .venv-wsl，只读复用现有 GPU 和 ML 包。
原有 D:/llm_exp/ 环境没有安装或升级本次新增服务依赖。

模型：BAAI/bge-m3
固定来源版本：{conversion['source_revision']}
实际参数量：{conversion['parameter_count']:,}（约 0.568B）
FP16 参数字节：{conversion['weight_storage_bytes']:,}
推理硬件：{health['gpu']}
实际权重精度 / 设备：{health['dtype']} / {health['device']}
输出：1024 维 dense 向量，CLS pooling，float32 L2 归一化。
原始权重已按官方 SHA256 校验，转换结果另存为 safetensors。

入口：
健康检查：http://127.0.0.1:18080/health
接口文档：http://127.0.0.1:18080/docs
向量接口：POST http://127.0.0.1:18080/v1/embeddings
模型名：BAAI/bge-m3（也接受 bge-m3-fp16）
无需云端 API Key，仅监听本机回环地址。

实际验证：
1. 核心接口检查 {core['passed']} 项通过，{core['failed']} 项失败。
   涵盖中英文语义样例、向量形状和归一化、异常输入、两个并发请求、16 条批处理。
2. Windows 与启动停止检查 {windows['passed']} 项通过，{windows['failed']} 项失败。
   证实 Windows 可调用、停止后端口关闭、重启为新进程、重启后继续推理。
3. 8192 token 输入成功，8193 token 返回 422；与官方分词器的 {long['tokenizer_samples']} 条样例一致。
4. 原始 FP32 与 FP16 的 {reference['samples']} 条中英文样本比较通过。
   最低余弦相似度：{reference['minimum_cosine']:.10f}。
   最大绝对差：{reference['maximum_absolute_difference']:.10f}。

本机性能样例：
短查询暖启动 HTTP 延迟中位数：{core['benchmark']['warm_single_query_median_ms']:.2f} ms（5 次样例）。
16 条、每条 {core['benchmark']['batch_characters_each']} 字的批处理：{core['benchmark']['batch_seconds']:.3f} 秒。
8192 token 单条请求：{long['long_input_seconds']:.3f} 秒。
模型加载后当前 CUDA allocated：{health['cuda_allocated_mib']:.2f} MiB。
8192 token 检查后 CUDA peak allocated：{long['health']['cuda_peak_allocated_mib']:.2f} MiB。
这些是本机开发检查，未代替正式检索质量评估，也不代表固定性能保证。

使用：
PowerShell 进入 D:/bge-m3-local/，运行 ./Start-BGE.ps1、./Status-BGE.ps1。
停止运行 ./Stop-BGE.ps1；复查接口运行 ./Verify-BGE.ps1。
未设置开机自启，重启 Windows 或终止 WSL 后需手动启动。
服务依赖 README.txt 列出的既有包路径；迁移、删除旧环境前需先迁移这些依赖。

范围：
本次部署独立 embedding 服务，图书馆源码和索引未接入本服务。
后续应编写图书馆本地向量适配器，统一重建馆藏向量和索引。
该模型不生成聊天回答，不包含 reranker、sparse 或 ColBERT 接口。

完整证据：reports/ 内的 JSON 与 evidence/ 中的来源及代码哈希记录。
详细操作和调用示例：README.txt、example_client.py。
'''
(ROOT / 'reports/部署与验证说明.txt').write_text(text, encoding='utf-8')
print(text)
