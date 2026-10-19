# 图文使用手册

面向日常读者、馆藏维护者与课堂演示者。原项目已有根README、本地模型说明及历史mock演示脚本，本工作项DOC001补充完整的中文图文操作手册。

- [在线阅读 Markdown](使用手册.md)
- [下载可编辑 Word](专题数字图书馆使用手册.docx)
- [首版截图与操作核验记录](verification.json)
- [当前文档验收与输出哈希](acceptance-20261019.json)

手册13页，14幅原始浏览器截图。内容包括打开系统、学科与封面浏览、三种检索、筛选、结果定位、增强识别、版本年份、人工编目、正文质量门禁、独立问答、引用高亮、故障处理、视频演示顺序与工作追溯。Word与Markdown以相同正文生成；Word只在两幅图的版面中裁去无关部分，原始截图不改动。

本机当前阅读用PDF保存在工作目录`reports/user-guide-accepted/`，首版保留在`reports/user-guide/`，均不提交到Git。Word可复建：使用Codex工作区依赖中的Python执行`tools/build_user_guide.py --source docs/user-guide/使用手册.md --output docs/user-guide/专题数字图书馆使用手册.docx`。

主功能实拍基于main `b9565b4`，问答环节加载[UI001独立修复PR6](https://github.com/Dan1un1u/digital-library-rag/pull/6)。PR6已验收合入main；文档PR7随后同步main并改以main为base，差异只包含手册、配图、文档生成器和导航，UI代码不计入文档工作量。本轮不部署既有正式实例。

实拍环境为独立API19020、UI19520，复用只读模型与已授权模型服务，不复用正式馆藏。3篇正常资料通过现有接口准备，FQ-ViT在浏览器中完成增强预览、人工格式字段填写及真实导入，最终4篇可检索；另经现有接口准备2篇异常原件展示正文审核状态。接口准备与浏览器实际操作在记录中分别标明，不称为全程手工导入。

文档生成与核验使用工作区提供的Python、python-docx和Poppler。本机缺少LibreOffice，初次标准渲染失败日志保留于本机`reports/guide-render-initial.txt`；随后使用已安装的Microsoft Word导出PDF，再接入标准`render_docx.py`的逐页栅格化流程。13页图像均经实际查看，未发现溢出、遮挡、丢字或孤立尾段。文档检查不重新计作自动业务测试或总体质量评测。

馆藏文件、数据库、索引、模型配置、认证信息及QA中间页图不提交。verification.json冻结首版截图及首版输出哈希，本轮保留该历史记录与14幅原图；文档中的候选状态改为拍摄时状态，当前Word、PDF与正文哈希另见acceptance-20261019.json。截图不是正式实验成绩，也不构成用户逐篇人工复核声明。
