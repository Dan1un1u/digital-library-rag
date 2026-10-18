# 入库后的人工抽查记录

本批 11 份 PDF 已经由应用外的编码助手辅助复核并入库。应用的原始识别缺陷尚未修复。此表供用户对照原 PDF 独立抽查；未收到实际反馈前，不填写“人工通过”。

## 建议先抽查三项

1. **FQ-ViT 作者与年份**：作者应为 Yang Lin、Tianyu Zhang、Peiqin Sun、Zheng Li、Shuchang Zhou，不能填单位 MEGVII Technology。馆藏 year 使用正式发表年 2022；所供 PDF 的 arXiv v4 修订日期是 2023-02-17，二者分别记录。正式年份依据：[IJCAI 官方记录](https://www.ijcai.org/proceedings/2022/bibtex/164)。
2. **Ascend 完整作者与顺序**：Yuhang Zhou、Zhibin Wang、Guyue Liu、Shipeng Li、Xi Lin、Zibo Wang、Yongzhong Wang、Fuchun Wei、Jingyi Zhang、Zhiheng Hu、Yanlin Liu、Chunsheng Li、Ziyang Zhang、Yaoyuan Wang、Bin Zhou、Wanchun Dou、Guihai Chen、Chen Tian，共 18 位。请对照首页，而不是只看识别结果。
3. **双栏正文顺序**：从 Ascend 或其他双栏论文选择一页，比较图书馆显示的片段与 PDF，观察是否串栏、漏段或错序。已经自动核对的页内字符偏移只能说明片段对应已抽取文本，不能证明抽取后的阅读顺序正确。

可在 [本机图书馆](http://127.0.0.1:18501/) 检索标题并打开原文。其他 9 篇也可以逐篇核对，完整值与修订见 [metadata-review.json](metadata-review.json)。

## 当前状态

| 检查项 | 检查人 / 反馈 | 状态 |
| --- | --- | --- |
| FQ-ViT 作者与正式年份 | 尚未收到用户核对结果 | pending |
| Ascend 作者完整性与顺序 | 尚未收到用户核对结果 | pending |
| 双栏正文抽查 | 尚未收到用户核对结果 | pending |
| 其他文献逐篇人工复核 | 尚未执行 | pending |

请通过聊天回复发现的问题，注明文件、字段或页码；确认无误时也注明实际抽查范围。仅抽查两篇或一页，不等同于全部 11 篇完成独立人工审核。用户反馈只在实际收到后写入记录，PR 暂不合并。
