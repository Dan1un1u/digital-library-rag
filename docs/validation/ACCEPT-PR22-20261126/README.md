# PR22 入库失败恢复验收

日期为 2026-11-26（Asia/Hong_Kong）。main 基线为 `7a47698cced0123eda32697e3412c82017e6c84d`，验收源码为干净提交 `908abec7f7e853e2cff3cddb882879feb2b698ea`。PR22 包含的功能见 [ING-003](../../work-items/ING-003.md)。

## 本轮发现与修正

在初始 PR 提交 `d5a502493a81967e569e4fc4a1f33c6c50d2b507` 中，浏览器提交成功后，恢复面板会折叠，成功提示和历史记录仍在页面内但被隐藏。给面板启用带键的展开状态后，重新渲染时保留用户展开的状态。中英文用例新增了提交后展开状态断言，修正前两项均失败，修正后两项均通过。

## 真实样本复测

使用历史 COL-002 样本 SS06，Michael Spence 的 *Job Market Signaling*。两个文件的完整哈希均与[原目录记录](../COL-002/catalog.json)一致。

| 文件 | SHA-256 |
| --- | --- |
| 21 页扫描原件 | `a37b62fd92b1d1fe2264f0afc23c5c8f04198e4d157027d138bc65a75934cc5e` |
| 历史 OCR 版 | `f4cea8a098f6ead6f125e0c82af2fce4891908b9fa12f4a9ec7d642bd9dca7f8` |

- 使用独立 SQLite、原文目录和索引。API 与 Streamlit 分别运行在本机 dev 端口 58620、58621。入库和解析使用真实 PDF，向量服务为 mock。
- 提交原件后返回 `FULLTEXT_REVIEW_REQUIRED`，指出第 2–21 页。原件没有检索片段，下载字节与历史原件相同。
- 在 Chrome 文献管理页打开第 21 页的定位链接，通过文件控件选择现有 OCR 版并提交。成功后面板保持展开，显示已恢复、历史记录和修正版链接。修正版入库 21 页、55 个片段，下载哈希与输入一致。
- 正文查询 `signaling costs` 在关键词、向量、混合三种模式均命中第 1 页以后的正文。重复提交相同文件后只有一条修正版记录，索引版本一致。重启 dev 后仍能回查原件、修正版和关联。
- SQLite 完整性和外键检查通过。正式馆藏的只读对照前后均为 175 篇、16,699 个片段，索引版本和语料哈希一致。

## 自动回归与证据

**8 项专项及 662 项既有回归全部通过。** 先前问题复现日志、正式复测日志和截图保存在本机独立验收目录。

| 文件 | SHA-256 |
| --- | --- |
| `panel-red.log` | `1240d674bc80d0f4b2cab46cf3f397050feec7476c6ca75541d587d4eb4ca3a5` |
| `fixed-target-pytest.log` | `d969bcd8e5b38973ef1b86243edc136a77a1bd9a1ccda7e66f3c99edd243fef3` |
| `fixed-inherited-pytest.log` | `5d39b6ebe942ad8af95315b0096d915bd0d6ac05d29de25d5634e94138efdb80` |
| `browser-replay-gcjo3bwh/receipt.json` | `3bd2b001483bc77578395813ca3a982987e072cddb46d828103572333567fb29` |
| `browser-replay-gcjo3bwh/01-problem-page.png` | `940fbd9f2241e937dea61b3255b220e18f871cffe731fcfa84bb14b2f61e4907` |
| `browser-replay-gcjo3bwh/02-recovered.png` | `9524a32f2e11954dc6e6d94434a47157a2745a909d845decd6eab00b8e1380d5` |
