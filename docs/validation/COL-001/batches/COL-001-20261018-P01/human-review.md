# 入库后的人工抽查记录

本批 11 份 PDF 已经由应用外的编码助手辅助复核并入库。用户反馈时应用的原始识别缺陷尚未修复。用户于 2026-10-18（Asia/Hong_Kong）通过聊天确认已完成下述三项抽查，未发现问题；本表按实际反馈范围登记。

## 建议先抽查三项

1. **FQ-ViT 作者与年份**：作者应为 Yang Lin、Tianyu Zhang、Peiqin Sun、Zheng Li、Shuchang Zhou，不能填单位 MEGVII Technology。馆藏 year 使用正式发表年 2022；所供 PDF 的 arXiv v4 修订日期是 2023-02-17，二者分别记录。正式年份依据：[IJCAI 官方记录](https://www.ijcai.org/proceedings/2022/bibtex/164)。
2. **Ascend 完整作者与顺序**：Yuhang Zhou、Zhibin Wang、Guyue Liu、Shipeng Li、Xi Lin、Zibo Wang、Yongzhong Wang、Fuchun Wei、Jingyi Zhang、Zhiheng Hu、Yanlin Liu、Chunsheng Li、Ziyang Zhang、Yaoyuan Wang、Bin Zhou、Wanchun Dou、Guihai Chen、Chen Tian，共 18 位。请对照首页，而不是只看识别结果。
3. **双栏正文顺序**：从 Ascend 或其他双栏论文选择一页，比较图书馆显示的片段与 PDF，观察是否串栏、漏段或错序。已经自动核对的页内字符偏移只能说明片段对应已抽取文本，不能证明抽取后的阅读顺序正确。

可在 [本机图书馆](http://127.0.0.1:18501/) 检索标题并打开原文。其他 9 篇也可以逐篇核对，完整值与修订见 [metadata-review.json](metadata-review.json)。

## 当前状态

| 检查项 | 检查人 / 反馈 | 状态 |
| --- | --- | --- |
| FQ-ViT 作者与正式年份 | 用户确认完成上述抽查，未发现问题 | passed（用户反馈） |
| Ascend 作者完整性与顺序 | 用户确认完成上述抽查，未发现问题 | passed（用户反馈） |
| 双栏正文抽查 | 用户确认完成上述抽查，未发现问题；具体文献与页码未提供 | passed（抽查范围内；用户反馈） |
| 其他文献逐篇人工复核 | 本次反馈不包含其余文献的逐篇核对 | pending |

## 反馈依据与边界

原问题要求核对 FQ-ViT 的 5 位作者及正式年份 2022、Ascend 的 18 位作者及顺序，并选择一页双栏正文检查是否串栏或漏段。用户回复原文：**“已完成上述抽查，未发现问题”**。结构化记录见 [human-review-response.json](human-review-response.json)。

双栏抽查具体文献与页码没有在回复中给出，保留为未报告，不补造页码。其余文献、其他页面和正式检索质量评测不在此次确认范围内。入库前的 metadata-review.json、导入回执及验证报告保持原样，后续人工反馈在本表与响应记录中追加，不回写历史执行状态。

本次抽查确认外部辅助修订后的数据在已检查范围内无误，不能代替程序修复验证。后续 2026-10-19 的 MQ-003 分支修复候选已通过离线及影子预览验证，正式实例尚未部署，详见 [修复报告](../../mq003-fix.md)；本次人工反馈不算作对该候选的人工验收。MQ-004 仍为补全改进项，MQ-001/MQ-002 本机观察不列项目缺陷。原始执行记录和结构化反馈保持原样。PR 暂不合并。
