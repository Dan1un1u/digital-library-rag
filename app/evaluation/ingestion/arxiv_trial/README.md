# 10 篇 arXiv PDF 本地实验

2026-10-12 实际下载 10 篇公开 arXiv PDF；来源、作者、标题及年份从对应摘要页 citation 元数据获取。PDF 在 data/arxiv_trial/source；SQLite 在 data/arxiv_trial/library.sqlite；受控副本在 data/arxiv_trial/raw。下载的是当时摘要页提供的版本，文件 SHA256 已记录在 catalogue.csv。

最终结果：10/10 导入成功，156 页，732 块。字符模式 max_chars=1200、overlap_chars=150；所有块偏移切片校验与逐文献重复导入校验通过。文献状态均为 indexing，尚未建立 B 的检索索引。

首次 3 篇失败，原始记录保存在 initial_results.json。真实论文文本块带有空字符，SQLite length 在空字符处截断而 Python len 继续计数；parser v2 清除规范文本中的空字符，保留原始提取文本，并增加回归测试。显式重试后全部成功。results.json 与 summary.json 是最终结果。

大量论文具有双栏布局，已标记 MULTI_COLUMN_REVIEW_REQUIRED；parsing_quality.csv 的正文顺序仍待人工复核。通过偏移与去重检查不等于全文阅读顺序正确。

重跑：

```sh
python3 evaluation/ingestion/arxiv_trial/download.py --output data/arxiv_trial/source
PYTHONPATH=src python3 evaluation/ingestion/arxiv_trial/run.py
```

网页许可链接及来源说明记录于本地 manifest 和 catalogue；这次是本地解析实验，不据此声明全部 PDF 可以重新公开分发。源码交付 ZIP 不含实际 PDF 或数据库。
