# PR12 验收记录

2026-10-20，用户要求审核 PR12，通过后合并。本次结论为通过，未发现阻断合并的问题。验证基线为 main `8174362c38fcd62b722b5133692c7e9662355b87`，受审功能提交为 `d4ef5c463faebab24a2dc421f2493e20a0b028ec`；其后仅补充本次验收记录和授权状态。

## 审查结果

- 使用手册的 OOXML 差异仅涉及字体及东亚语言设置。正文、13 幅内嵌图片、字号、边距、章节和页面设置保持一致。
- 成品 Word 和生成器重建结果的 302 处字体声明符合要求，148 个文本运行均有显式字体。中文使用微软雅黑，代码保留 Consolas；无 MS Gothic、MS Mincho 或主题字体覆盖。重复应用字体处理不会继续改变 OOXML。
- 本机 Word 与受审提交的 Word 字节一致。PDF 的 SHA-256 与原交付记录一致；PDF 的 146 个正文段落均能与 Word 对应。
- 对该份 WPS 导出的 PDF 重新执行打包的 `render_docx.py` 图像渲染流程（Poppler，140 DPI），逐页检查全部 11 页。字体、表格、图注、页眉页脚和页码显示正常，未发现缺字、截断、重叠或空白页。此次没有重新执行办公软件导出，生成器重建与交付 PDF 的检查分别记录。
- PDF 仅嵌入 MicrosoftYaHei、MicrosoftYaHei-Bold 和 Consolas，三者均已嵌入。
- `app/`、`scripts/` 和 `.github/` 相对 main 无差异，因此本次不重复执行应用功能测试；正式实例及 175 篇馆藏未作修改。

## 检查边界与追溯

GitHub 当前未配置该提交的检查任务或状态，不能写成 CI 通过。默认 `git diff --check` 对原有四份验证 JSON 的 Windows CRLF 换行发出告警；仅把 CR 视作行结束符重新检查时通过，没有其余行尾空格或空行问题。原记录不改写。

[结构检查](structural-check.json)、[PDF 字体与逐页图像哈希](pdf-check.json)、[验收结论](acceptance.json)、[发布检查](publish-audit.json)。原始 DOC-002 证据仍保留在 [DOC-002](../DOC-002/README.md)。辅助脚本、渲染页及原始告警存放在本机独立验收目录，未作为交付程序依赖。

本次合并只涵盖 PR12；PR13–PR15 保留各自待审状态。
