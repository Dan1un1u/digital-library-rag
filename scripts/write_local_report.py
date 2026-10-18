"""Write a user-facing report from actual local integration evidence."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import requests

ROOT = Path(__file__).resolve().parents[1]
def read(name):
    return json.loads((ROOT / 'reports' / name).read_text(encoding='utf-8'))
integration, tests, index = read('local_models_integration.json'), read('pytest_summary.json'), read('local_bge_index.json')
if not integration['completed'] or integration['failed'] or tests['exit_code']:
    raise RuntimeError('Required verification is incomplete or failed')
http = requests.Session()
http.trust_env = False
health = http.get('http://127.0.0.1:18000/health', timeout=10).json()
if health['status'] != 'ready':
    raise RuntimeError('Library is no longer ready')
answer = integration['details']['qa_job']['answer']
diagnostics = answer['diagnostics']
stamp = datetime.now(timezone.utc).isoformat()
paths = [*ROOT.glob('*.ps1'), *ROOT.glob('scripts/*.py'), *ROOT.glob('app/src/**/*.py'),
         *ROOT.glob('app/src/**/*.txt'), *ROOT.glob('app/tests/**/*.py'), ROOT / 'app/.env.example']
manifest = [{'path': path.relative_to(ROOT).as_posix(),
             'sha256': hashlib.sha256(path.read_bytes()).hexdigest()} for path in sorted(paths)]
(ROOT / 'evidence/local_model_code_manifest.json').write_text(
    json.dumps({'created_at': stamp, 'files': manifest}, indent=2), encoding='utf-8')
text = f'''图书馆本地模型接入报告
生成时间（UTC）：{stamp}

状态：真实模式服务就绪，接口与界面保持运行。
界面：http://127.0.0.1:18501/
后端：http://127.0.0.1:18000/
部署副本：{ROOT.as_posix()}
原始 D:/lib_management_v1/ 项目未修改。

接入结果：
向量：本机 BGE-M3 FP16，1024 维，CUDA 推理。
回答：gpt-6-luna，经 http://127.0.0.1:8317/v1 调用。
重排：gpt-6-luna，LLM 相关性判断与严格 JSON 校验。
PDF 元数据候选：gpt-6-luna，接收前两页图像及文字。
代理程序位于 D:/cliproxyapi-local/，固定官方版本 8.0.33 并校验哈希。
OAuth 独立授权成功，未复制或修改既有桌面 Codex 的认证文件。
代理与 BGE 在本机；Luna 仍通过 OpenAI 服务使用订阅访问权限与额度。

索引：
文献 {index['manifest']['document_count']} 篇，片段 {index['manifest']['chunk_count']} 个。
向量输入合计 {index['embedding_statistics']['total_tokens']} tokens，{index['embedding_statistics']['requests']} 次本地请求。
重建耗时 {index['elapsed_seconds']:.3f} 秒。
来源修订：{index['manifest']['embedding_revision']}。
索引版本：{index['manifest']['index_version']}。
新索引记录本地 FP16 后端身份；旧索引快照保留。

验证：
自动测试 {tests['tests']} 项通过，{tests['failures']} 个失败、{tests['errors']} 个错误。
真实联调 {integration['passed']} 项通过，{integration['failed']} 项失败。
包括真实 BGE 向量/混合检索、Luna JSON、语义相关性重排、扫描 PDF 识别、
异步问答、双语检索、引用、要点覆盖及本地客户端口令的公开响应泄漏检查。
扫描 PDF 没有内嵌文字；随机标题及作者、2024 年份均由页面图像正确识别，候选仍需人工确认。

真实问答样例：
问题：{answer['query_plan']['original_query']}
状态：{answer['status']}。
回答结论 {len(answer['claims'])} 条，引用片段 {len(answer['evidence'])} 个。
规划回退：{diagnostics.get('planning_fallback')}。
双语检索：{diagnostics.get('multi_query')}。
重排：{diagnostics.get('rerank_method')}，状态 {diagnostics.get('semantic_rerank_status')}。
支持句定位：{diagnostics.get('sentence_grounding_status')}。
要点覆盖：{diagnostics.get('coverage_check_status')}。
主模型调用 {diagnostics['model_calls']} 次，额外重排调用 {diagnostics.get('rerank_model_calls')} 次。
单次问答总耗时：{answer['timings_ms']['total'] / 1000:.3f} 秒。
以上是本机接入样例，不构成通用准确率或性能结论。

修复与实际限制：
新增仅限回环地址的本地服务适配器，云端适配器继续要求 HTTPS。
Luna 参数与 Qwen 参数分开；图像内容保持 image_url 协议传递。
Luna 原先把整条 JSON 用户消息当作原问题，已明确提示中的 question 字段含义，
保留原有逐字校验；最终样例无需规划回退。
重排与句子定位支持分组批量调用和有界缓存，调用数单独记录。
联调中出现一次上游临时失败；随后直接请求恢复。客户端和代理未开启隐式重试或账号切换。
重排分数是模型判断，不是校准概率；效果需在正式测试集中与专用重排模型比较。
外部服务可用性取决于网络、账户权限及订阅额度。

启动、停止与复查见本目录“本地模型使用说明.txt”。
修改前源码、配置和数据库位于 evidence/before_local_models_20261018/。
详细报告：reports/local_models_integration.json、reports/pytest_summary.json、reports/local_bge_index.json。
'''
(ROOT / 'reports/本地模型接入报告.txt').write_text(text, encoding='utf-8')
print(text)
