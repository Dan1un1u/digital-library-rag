# D 验收记录

日期：2026-10-16（Asia/Singapore）。范围：D 的本地独立开发与 A/B 参考接入；后续正式联调尚未进行。没有 Git 提交/推送/PR，没有调用真实嵌入或 LLM。

## 环境与执行

Windows，Python 3.12.14；共同契约 1.0。Python 3.11 未实测。直接依赖见 requirements.txt，完整已安装版本见 requirements-lock.txt/environment.json。A 35 个、B 26 个归属文件逐字节比对全部一致（source_inventory.json）。

实际执行：

```text
uv pip install --python <本地独立环境> -e ".[dev]"   （指定工作区缓存）
python -m pip install -e ".[dev]" --no-build-isolation --no-index
python -m pip check
python -m pytest -q --basetemp=<工作区临时目录> --tb=short --junitxml=handoff/D/test_results.xml
python scripts/seed_demo.py
python scripts/seed_demo.py --rebuild-only
python scripts/run_evaluation.py --collect --dataset evaluation/dataset/questions.jsonl
python scripts/run_evaluation.py --dataset evaluation/dataset/questions.jsonl --mode mock
python scripts/run_evaluation.py --dataset evaluation/dataset/questions.jsonl --mode real
python -m dlrag.api.main
python -m streamlit run src/dlrag/ui/app.py --server.address 127.0.0.1 --server.port 8501 --server.headless true --browser.gatherUsageStats false
```

安装及 pip check 成功。最终全量测试 **149 passed，2 warnings，18.41 秒**，其中 A/B 原有 107 项、D 新增 42 项。两条警告分别为 Starlette 的 httpx 测试客户端弃用提示、重复 PDF 保留原元数据的预期提示。XML 原记录在 test_results.xml。临时目录和异步事件循环受 Codex Windows 沙箱限制，本次将临时目录设于工作区，并在允许本地事件循环的宿主环境运行；没有跳过测试。

最初 UI 实测发现 PyArrow 26 与 B 固定的 NumPy 1.26.4 二进制不兼容；已显式锁定 PyArrow 19.0.1、pandas 2.2.3 后全量复测通过。不能用单独 pip check 代替运行时测试。

## 功能验收

| 项目 | 状态 | 证据与边界 |
|---|---|---|
| 可安装 src 工程、统一配置与模型 | 通过 | 安装、导入、模型边界与显式 APP_MODE；无密钥可导入 |
| API 核心路径和统一错误体 | 通过 | tests/integration/test_api.py；包括完整 /ask 错误结构 |
| 真实 A/B 合成 PDF 入库→索引→检索→文件 | 通过 | A/B 真代码、fake embedding；引用 quote/页序与 /chunks 相符 |
| 完整真实 A/B/C 问答链路 | 未执行 | C 缺失，当前问答是 D 脚本替身，不能称真实端到端完成 |
| 重复文件、坏/空 PDF、超限、非法参数 | 通过 | 去重不新增；failed 管理状态；422/413/415；临时文件清理 |
| 三模式、年份/主题过滤与文献聚合 | 通过 | 真实 B 代码，mock embedding；best_rank/preview 与最优片段一致 |
| 引用编号、展开和澄清选择 | 通过 | Streamlit AppTest 操作页面、提问、点击 [1] 原文；选择构成新请求 |
| 无答案、无密钥、模拟超时 | 通过 | 无 claims；real 配置不足 503；真实模式注入超时保持错误，不回退 |
| 重建失败与重试 | 通过 | 旧版本仍可检索，新文献 indexing 带错误；重试后 ready |
| 问答与重建互斥 | 通过 | 事件同步测试保证完整问答结束前重建不会进入 |
| 应用重启加载 | 通过 | 新建服务实例加载原 SQLite/索引，版本和查询保持 |
| 后端/UI 实际启动 | 通过 | startup_smoke.json；8000/8501 健康返回 200，问答和 PDF 200，核验后停止 |
| PDF 浏览器 #page 跳转 | 未人工验收 | 自动核对链接页号/原文件；需课堂浏览器实际验证，UI 提供手动页号 |
| PDF 高亮 | 未实现（可选） | 界面明确提示 |
| 45 题汇总与 mock 工具执行 | 通过 | A/B/D 各 15，C 缺；dev 36/test 9 仅候选划分；无真实质量分数 |
| 约 60 题人工复核及冻结 | 未完成 | 当前 45 道候选均不可计分；D 15 道模板待 B 复核 |
| real 总体实验 | 未执行（预期拒绝） | 退出码 2，原因 A001 尚未复核；real_evaluation_not_executed.json |
| 人工语义支持、引用覆盖/正确率 | 未评估 | 仅输出人工表格，未以 ID 存在率充当支持率 |

## 评估记录

mock 执行 45 题，接口错误 0；dev 36 题，中位 0.700 ms，P95 1.183 ms；test 9 题，中位 0.679 ms，P95 0.748 ms。仅为本机替身与微小合成库的工具耗时，不是实际模型延迟或问答质量。Hit/Recall/证据覆盖和人工指标全部 null；汇总见 mock_evaluation_summary.json。

## 仍需人工/后续联调

C 的 QAEngine、实际 LLM 客户端工厂和依赖；真实模型配置与允许使用的馆藏；A↔C、B↔D 标注复核；近义题分组、锁定 dev/test/索引；全链路真实实验；课堂浏览器页跳转与展示排练。当前没有代替用户执行跨组通知或安排定时任务。
