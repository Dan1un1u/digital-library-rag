"""Presentation-only translations; stored metadata and API IDs stay unchanged."""
from contextlib import contextmanager
from contextvars import ContextVar
import re

_language = ContextVar('dlrag_interface_language', default='zh')

MESSAGES = {
    '<div class="library-hero"><small>EXPLORE THE COLLECTION</small><h2>从一篇文献，开启新的发现</h2><p>浏览学科馆藏，阅读原始文献，让每一次提问都有据可依。</p></div>': '<div class="library-hero"><small>EXPLORE THE COLLECTION</small><h2>Discover more, one document at a time</h2><p>Browse subject collections, read original documents and find sources for every question.</p></div>',
    '专题数字图书馆': 'Digital Library',
    '专题数字图书馆 · 您的文献工作台': 'Digital Library · Your research workspace',
    '查找文献 · 依据原文提问 · 核对每一条引用': 'Find documents · Ask questions grounded in sources · Check every citation',
    '### 📚 阅读与发现': '### 📚 Read and discover',
    '功能': 'Navigation', '馆藏展示': 'Collection', '搜索与问答': 'Search and Q&A',
    '上传与管理': 'Upload and manage', '馆藏导航': 'Browse collection', '管理导航': 'Manage library',
    '馆藏文献分类': 'Collection by subject', '热门电子文献资源': 'Featured documents',
    '上传文献': 'Upload documents', '文献管理': 'Manage documents', '系统设置': 'System settings',
    '自然科学': 'Natural sciences', '社会科学': 'Social sciences', '哲学与人文科学': 'Philosophy and humanities',
    '全部': 'All', '待分类': 'Unclassified', '学科': 'Subject', '篇数': 'Documents',
    '筛选文献': 'Filter documents', '起始年份': 'From year', '结束年份': 'To year', '不限': 'Any',
    '主题（逗号分隔）': 'Topics (comma-separated)', '信息检索,数字图书馆': 'information retrieval,digital libraries',
    '年份须为整数，且起始年份不能大于结束年份。': 'Enter whole years; the start year must not be later than the end year.',
    '作者未标注': 'Authors not provided', '年份未标注': 'Year not provided', '主题未标注': 'Topics not provided',
    '来源：': 'Source: ', '来源': 'Source', '作者': 'Authors', '标题': 'Title',
    '语言': 'Document language', '中文': 'Chinese', '英文': 'English', '中英混合': 'Chinese and English', '未确定': 'Unknown',
    '馆藏文献': 'Documents in collection', '{p0} 篇': '{p0} docs',
    '#### 馆藏的三个方向': '#### Three areas in the collection',
    '**自然科学** · 数学、物理、生物、计算机与技术等。': '**Natural sciences** · Mathematics, physics, biology, computing and technology.',
    '**社会科学** · 经济、社会、政治、教育与管理等。': '**Social sciences** · Economics, sociology, politics, education and management.',
    '**哲学与人文科学** · 哲学、历史、文学与艺术等。': '**Philosophy and humanities** · Philosophy, history, literature and the arts.',
    '统计范围为当前筛选结果。优先使用学科标签；旧资料按题名和主题辅助归类。': 'Counts reflect the current filters. Subject tags take priority; older records also use title and topic keywords.',
    '另有 {p0} 篇待分类，未计入饼图。': '{p0} unclassified documents are excluded from the chart.',
    '浏览所属学科': 'Browse by subject', '当前显示 {p0} 篇文献': 'Documents shown: {p0}',
    '暂无已分类文献，上传时可指定所属学科。': 'No classified documents yet. Choose a subject when importing a document.',
    '暂无可用文献，请在“上传与管理”添加 PDF。': 'No documents yet. Add a PDF in Upload and manage.',
    '精选馆藏推荐 · 封面采用文献 PDF 首页，点击封面阅读原文。当前未统计阅读热度，展示顺序不代表访问量排名。': 'Browse selected documents by their PDF covers. Select a cover to read the original. The order does not represent readership rankings.',
    '阅读原文 ↗': 'Read original ↗', '阅读原文': 'Read original', 'PDF 首页': 'PDF first page',
    '想查找或了解什么？': 'What would you like to find or understand?', '操作': 'Action', '搜索': 'Search', '问答': 'Q&A',
    '搜索方式': 'Search mode', '关键词检索': 'Keyword search', '语义检索': 'Semantic search', '混合检索': 'Hybrid search',
    '用于“搜索”操作；问答会自动组织检索。': 'Used for Search. Q&A organizes retrieval automatically.',
    '提交': 'Submit', '{p0} 篇文献 · {p1} 个片段': 'Documents: {p0} · Passages: {p1}', '最佳排名：{p0}': 'Best rank: {p0}',
    '片段 {p0} · {p1} · PDF 第 {p2} 页': 'Passage {p0} · {p1} · PDF page {p2}',
    '打开该页': 'Open page', '页号按 PDF 文件计数；定位由浏览器决定，未实现高亮。': 'Pages are counted from the start of the PDF. Your browser controls page navigation; this link does not highlight text.',
    '**回答进度**': '**Answer progress**', '排队等待': 'Queued', '等待馆藏读取': 'Waiting for the collection',
    '理解问题与生成中英文检索词': 'Understanding the question and preparing retrieval queries',
    '检索相关文献': 'Finding relevant documents', '重排并选择正文及相邻证据': 'Ranking and selecting source passages',
    '模型正在整合回答': 'Generating the answer', '修复回答格式与引用': 'Checking answer structure and citations',
    '核验引用与问题要点覆盖': 'Validating citations and coverage', '定位支持回答的原文句子': 'Locating supporting source sentences',
    '核对回答与问题要点的关联': 'Checking coverage of the question', '处理完成': 'Completed', '处理失败': 'Failed',
    '已用时 {p0:.1f} 秒': 'Elapsed: {p0:.1f} s', '正在等待模型返回，期间会持续更新用时。': 'Waiting for the model; elapsed time will keep updating.',
    '请在左侧阅读回答；原文证据可展开核对。': 'Read the answer on the left. Expand its evidence to check the original.',
    '提交问答后，这里会显示后台实际处理阶段。': 'Submit a question to see the current processing stage here.',
    '本次等待超过 5 分钟，请检查后端状态。任务可能仍在后台处理。': 'This request has taken more than five minutes. Check the service status; it may still be processing.',
    '系统理解': 'How the question was understood', '检索表达：': 'Retrieval query: ', '英文检索表达：': 'English retrieval query: ',
    '意图：': 'Intent: ', '查找': 'Find', '解释': 'Explain', '比较': 'Compare', '需要澄清': 'Clarification needed',
    '请选择': 'Choose an option', '补充说明': 'Additional details', '补充后重新提问': 'Ask with these details',
    '当前馆藏证据不足，无法据此给出可靠结论。': 'The collection does not contain enough evidence for a reliable answer.',
    '检索去重 {p0} 个片段 · 重排候选 {p1} 个 · 选入上下文 {p2} 个 · 最终引用 {p3} 个': '{p0} unique passages · {p1} ranking candidates · {p2} context passages · {p3} cited passages',
    '### 回答': '### Answer', '回答范围：': 'Scope: ', '问题要点与回答范围': 'Question coverage and answer scope',
    '可对照正文中的相关说明': 'See the corresponding explanation in the answer', '；仍有缺口：': '; remaining gap: ',
    '资料缺口：': 'Missing evidence: ', '**核对原文**': '**Check the sources**', '[{p0}] 查看原文': '[{p0}] View source',
    '[{p0}] {p1} · PDF 第 {p2} 页': '[{p0}] {p1} · PDF page {p2}',
    '此回答未包含句子定位信息，重新提问后可使用句子高亮。': 'This answer has no sentence locations. Ask again to enable sentence highlights.',
    '打开 PDF 原文件（尝试定位该页）': 'Open original PDF (at this page)', '查看高亮原文与 PDF 原页': 'View highlighted source and PDF page',
    'PDF 文件第 {p0} 页。回答角标按当前结论定位；此处汇总本片段的引用句子。': 'PDF page {p0}. Answer citations select the supporting sentences; this view collects the sentences cited from this passage.',
    '**相关文献**': '**Related documents**', '说明：': 'Note: ', '错误标识：': 'Error code: ',
    '运行模式、模型和索引信息集中在此处，供维护时查看。': 'View the current service mode, models and index for maintenance.',
    '当前运行模式：': 'Service mode: ', '真实服务（REAL）': 'Live services (REAL)', '演示服务（MOCK）': 'Demo services (MOCK)',
    'MOCK 使用合成资料和脚本问答，仅用于演示流程。': 'MOCK uses synthetic documents and scripted answers to demonstrate the workflow.',
    '模式切换说明': 'Changing service mode',
    '运行模式由后端启动配置决定。修改 APP_MODE 为 real（真实）或 mock（演示），并使用对应的 DATA_DIR 后重启后端；真实服务还需配置模型密钥。': 'Service mode is set when the backend starts. Set APP_MODE to real or mock, choose the matching DATA_DIR and restart the backend. Live services also require model credentials.',
    '切换前请等待当前问答和上传完成。两种模式使用各自的数据目录。': 'Wait for active questions and uploads to finish before changing service mode. Each mode uses its own data directory.',
    '当前模型：': 'Models: ', '当前索引：': 'Index: ', '暂无': 'None', '详细运行配置': 'Detailed configuration',
    '查看已上传文献及其处理状态。': 'Review uploaded documents and their processing status.', '共 {p0} 篇文献': '{p0} documents',
    '所属学科：': 'Subject: ', ' · 状态：': ' · Status: ', '文献处理未完成': 'Document processing did not complete.',
    '上传 PDF': 'Upload a PDF', '选择 PDF，自动识别标题和作者；核对文献信息后，即可加入馆藏。': 'Choose a PDF, review the suggested metadata and add it to the collection.',
    '增强识别（推荐）': 'Enhanced recognition (recommended)',
    '使用已配置的 API 辅助识别；学科先按关键词判断，未匹配时由 LLM 辅助分类。会发送 PDF 前两页的图像和文字；关闭后仅在本机识别。': 'Use the configured API to identify metadata. Subjects use keywords first, then LLM assistance when needed. Text and images from the first two PDF pages are sent to the service. Turn this off for local recognition only.',
    '联网补全出版资料': 'Look up publication details',
    '增强识别成功后，将题名和前两位作者姓名发送至 Crossref 查询期刊或会议出版记录，不发送 PDF。补充相关出版来源；仅确认同一出版版本时补缺失年份。年份应对应当前 PDF，预印本可填公开或修订年份。结果需核对。修改选项后请点击重新识别。': 'After enhanced recognition, look up the title and first two authors in Crossref. The PDF is not sent to Crossref. Related publication sources may be added; a missing year is filled only when it matches this version. Review the results and run recognition again after changing this option.',
    '上传 PDF（单份最大 {p0} MB）': 'Upload PDF (up to {p0} MB)', '重新识别文献信息': 'Recognize again',
    '重新预填当前文件的信息，会替换表单中的识别字段。': 'Run recognition again for this file. Suggested fields in the form will be replaced.',
    '识别结果与来源': 'Suggestions and their sources', '关键词匹配': 'Keyword match', '已有学科标签': 'Existing subject tag',
    'LLM 辅助分类': 'LLM-assisted classification', '自动分类': 'Automatic classification',
    '暂未确定所属学科，可在下方选择，或开启增强识别后重新识别。': 'No subject was identified. Choose one below, or turn on enhanced recognition and try again.',
    'PDF 第 {p0} 页 · ': 'PDF page {p0} · ', '版本年份': 'Version year',
    'PDF 自带信息': 'Embedded PDF metadata', '首页标题排版': 'First-page title layout', '首页文字': 'First-page text',
    '正文日期候选': 'Date found in the document', '正文中的文献标识': 'Identifier in the document', '前两页文字': 'Text from the first two pages',
    'API 页面识别（待核对）': 'API page recognition (review suggested)', '外部出版记录（待核对）': 'Publication record (review suggested)',
    '卷期年份': 'Journal issue year', '文件版本戳': 'File version date', '修订日期': 'Revision date', '预印本公开日期': 'Preprint release date',
    '投稿日期': 'Submission date', '接收日期': 'Acceptance date', '出版日期': 'Publication date', '版权年份': 'Copyright year',
    '印刷出版日期': 'Print publication date', '在线出版日期': 'Online publication date', '日期依据：': 'Date source: ',
    '查看该字段的出版记录': 'View publication record', '相关出版记录日期：': 'Related publication dates: ',
    '未提供': 'Not provided', '；未自动用作当前版本年份。': '; not used automatically as the year of this version.',
    '核对相关出版记录': 'Check related publication record',
    '现有信息与外部记录存在差异，已保留现有值，请核对后修改。': 'The publication record differs from the current values. Current values were kept; review them before editing.',
    '：当前为 ': ': current value ', '，出版记录为 ': '; publication record value ',
    '标题（留空则标待核验）': 'Title (leave blank if not yet verified)', '作者（每行一位）': 'Authors (one per line)',
    '版本年份（可留空）': 'Version year (optional)', '所属学科': 'Subject area', '请选择文献所属学科': 'Choose a subject area',
    '来源链接（可选）': 'Source URL (optional)', '使用说明': 'Usage and rights note', '待人工确认': 'Add a usage or rights note if known',
    '导入文献': 'Import document', '请先选择 PDF 文件。': 'Choose a PDF first.', '请选择文献所属学科。': 'Choose a subject area.',
    '文献已加入馆藏：': 'Added to the collection: ', '年份须为整数或留空。': 'Enter a whole year or leave it blank.',
    '等待处理': 'Queued', '已接收 PDF': 'PDF received', '读取文献信息': 'Reading document metadata', '准备页面图像': 'Preparing page images',
    'API 正在识别标题、作者等信息': 'Recognizing title, authors and other metadata', '查询出版资料，补全缺失信息': 'Looking up missing publication details',
    '校验识别结果': 'Checking suggestions', '等待馆藏处理': 'Waiting to update the collection', '解析文献正文': 'Parsing document text',
    '处理文献，准备搜索': 'Preparing the document for search', '保存文献信息': 'Saving document metadata', '处理未完成': 'Processing did not complete',
    '处理中': 'Processing', '正在提交 PDF…': 'Submitting PDF…', '已用时 {p0:.1f} 秒 · 按实际处理阶段显示进度': 'Elapsed: {p0:.1f} s · Progress follows the current processing stage',
    '本机识别完成，增强识别未成功': 'Local recognition completed; enhanced recognition was unavailable',
    '处理超过 5 分钟，后台可能仍在继续，请到文献管理查看结果后再重试。': 'Processing has taken more than five minutes and may still be running. Check Manage documents before retrying.',
    '先在另一个终端启动后端：python -m dlrag.api.main': 'Start the backend in another terminal: python -m dlrag.api.main',
    '部分服务暂不可用，可在“上传与管理 → 系统设置”查看详情。': 'Some services are unavailable. See Upload and manage → System settings for details.',
    '可阅读': 'Ready to read', '正在建立检索': 'Building search index', '待核对正文（未加入检索）': 'Text review required (not searchable)',
    '文献原文': 'Original document', '引用原文': 'Cited source', '打开 PDF 原文件': 'Open original PDF', 'PDF 原页预览': 'PDF page preview',
    '对应 PDF 页面及可定位的支持句子高亮': 'PDF page with located supporting sentences highlighted',
    '该引用未包含句子定位信息。请重新提问以生成句子级高亮。': 'This citation has no sentence locations. Ask again to generate sentence-level highlights.',
    '黄色区域为该角标选中的支持句子；下方为对应 PDF 原页。': 'Yellow marks the supporting sentences selected by this citation. The original PDF page appears below.',
    '提取原文已精确高亮；PDF 文字层定位成功 {p0}/{p1} 句。未匹配句子请核对下方提取原文。': 'The extracted source is highlighted exactly; {p0}/{p1} sentences were located on the PDF page. Check the extracted text for any remaining sentences.',
    'PDF 文件第 {p0} 页': 'PDF page {p0}', '查看引用 {p0} 的原文': 'View source for citation {p0}',
}


def normalize_language(value):
    return value if value in ('zh', 'en') else 'zh'


def get_language():
    return _language.get()


def set_language(value):
    return _language.set(normalize_language(value))


@contextmanager
def use_language(value):
    token = set_language(value)
    try:
        yield
    finally:
        _language.reset(token)


def t(message, **values):
    translated = MESSAGES.get(message, message) if get_language() == 'en' else message
    return translated.format(**values) if values else translated


def labels(options):
    """Freeze widget labels at render time, including callbacks outside that context."""
    return {option: t(option) for option in options}.get


ERRORS = {
    'INVALID_REQUEST': 'Check the required fields, year range and search parameters.',
    'UNSUPPORTED_FILE': 'Only PDF files are supported.', 'UPLOAD_TOO_LARGE': 'The file exceeds the configured upload limit.',
    'INVALID_PDF': 'The PDF could not be read. Use a nonempty, unencrypted PDF.',
    'NO_EXTRACTABLE_TEXT': 'The PDF has no extractable body text. Run OCR or use a text-based copy before importing.',
    'FULLTEXT_REVIEW_REQUIRED': 'Some pages may be scanned and have no usable text layer. Review them and run OCR before importing.',
    'TEXT_LAYER_REVIEW_REQUIRED': 'Some pages have an unreadable text layer. Review the original pages, run OCR or use a corrected copy.',
    'DISCIPLINE_REQUIRED': 'Choose a subject area: Natural sciences, Social sciences, or Philosophy and humanities.',
    'DISCIPLINE_CONFLICT': 'Choose exactly one subject area.', 'NOT_FOUND': 'The requested item does not exist or has expired.',
    'MODEL_TIMEOUT': 'The model request timed out. Try again later.', 'MODEL_UNAVAILABLE': 'The model service is unavailable. Check the service status and try again.',
    'MODEL_NOT_CONFIGURED': 'The model service is not configured. Check its credentials and settings.',
    'EMBEDDING_NOT_CONFIGURED': 'The embedding service is not configured.', 'EMBEDDING_UNAVAILABLE': 'The embedding service is unavailable.',
    'EMBEDDING_INVALID_RESPONSE': 'The embedding service returned an invalid response.', 'EMBEDDING_MISMATCH': 'The embedding configuration does not match this index. Rebuild the index with the configured service.',
    'INDEX_NOT_READY': 'The search index is not ready or has changed. Import documents or refresh the request.',
    'INDEX_BUILD_FAILED': 'Index building failed. The previous working index is still available.',
    'MODULE_NOT_AVAILABLE': 'A required service module is unavailable. Check the service configuration.',
    'CONNECTION_ERROR': 'Cannot connect to the backend. Check that it is running and that the address is correct.',
    'OUTPUT_VALIDATION_FAILED': 'The service returned an invalid result. Check the service configuration and try again.',
    'INTERNAL_ERROR': 'Processing failed. Check the service status and try again.',
}


def error_message(error):
    if get_language() == 'zh':
        return error.get('message') or '请求无法处理'
    message = ERRORS.get(error.get('code'), 'The operation could not be completed. Check the document and service status, then try again.')
    pages = error.get('fulltext_review', {}).get('suspect_pages', [])
    if pages:
        message += ' PDF pages: ' + ', '.join(map(str, pages)) + '.'
    elif error.get('message'):
        # Historical stored review messages carry page numbers in their text.
        found = re.search(r'第\s*([\d、,，–—\-\s]+)\s*页', error['message'])
        if found:
            message += ' PDF pages: ' + found.group(1).replace('、', ', ').replace('，', ', ') + '.'
    return message


def system_message(message):
    if get_language() != 'en':
        return message
    if message in MESSAGES:
        return MESSAGES[message]
    for source in sorted(SYSTEM_MESSAGES, key=len, reverse=True):
        message = message.replace(source, SYSTEM_MESSAGES[source])
    return message if not re.search(r'[\u4e00-\u9fff]', message) else 'Review this suggestion against the PDF before importing.'


SYSTEM_MESSAGES = {
    '自动识别结果仅供预填，请核对后再导入；未识别的字段留空。': 'Review the suggested metadata before importing. Unidentified fields are left blank.',
    '作者候选可能因多行、分栏或 PDF 元数据不完整而遗漏，请核对完整名单和顺序。': 'Line breaks, columns or incomplete PDF metadata can omit authors. Check the full list and its order.',
    '已结合前两页图像进行 API 辅助识别；所有字段仍为待核对候选，尤其请核对作者顺序，以及年份是否对应所收录版本。': 'API recognition used the first two page images. Review the suggested fields, especially author order and the year of this PDF version.',
    'API 辅助未配置，已保留本机识别结果，可手动修改。': 'API assistance is not configured. Local suggestions are retained and can be edited.',
    'API 未提供可用候选，已保留本机识别结果。': 'The API returned no usable suggestions. Local suggestions were retained.',
    'API 请求超时': 'The API request timed out', 'API 鉴权未通过': 'API authentication failed',
    'API 请求频率受限': 'The API rate limit was reached', 'API 服务或网络暂不可用': 'The API or network is unavailable',
    'API 返回格式或候选结果不正确': 'The API returned an invalid suggestion',
    '，已保留本机识别结果；可点击重新识别或手动修改。': '; local suggestions were retained. Run recognition again or edit them.',
    '没有可提取文字，未启用 OCR；仅能使用 PDF 自带元数据或手动填写。': 'No text could be extracted. OCR is not enabled; use embedded PDF metadata or fill in the fields.',
    '未可靠识别标题，请手动填写；留空将使用文件名并标注待核验。': 'No reliable title was identified. Enter it yourself, or leave it blank to use a filename marked for review.',
    '未可靠识别作者，请手动填写。': 'No reliable authors were identified. Enter them from the PDF.',
    '年份为正文日期候选，请确认是否为正式出版年份。': 'This year was found in the document. Check that it describes this version.',
    '检测到多个不同年份，未自动选择出版年。': 'Several years were found; no year was selected automatically.',
    '版本年份待核对：': 'Review the version year: ', '出版年份待核对': 'Review the publication year',
    '页面没有可对应到所收录版本的日期说明': 'no date could be linked to this PDF version',
    '没有提供版本年份候选': 'no version year was suggested', '摘录无法与所指页面的正文证据对应': 'the excerpt could not be verified on that page',
    '年份类型、页码或范围不合法': 'the date type, page or year range is invalid', '所指页面没有可核对的文字或图像': 'the cited page has no verifiable text or image',
    '候选年份与当前版本的日期依据不一致': 'the suggested year differs from the date evidence for this version',
    '同类版本日期存在不同年份，需要核对': 'conflicting years were found for the same date type',
    '；已留空，可根据所收录文件核对后填写。': '; the field was left blank so you can check the PDF and fill it in.',
    '书目补全需要可靠的题名与作者，请核对后重试或手工补充。': 'Publication lookup needs a reliable title and author list. Review them, then retry or fill in the details.',
    '书目查询未找到唯一、题名和作者均吻合的出版记录；缺失字段保持为空，请核对。': 'No unique publication record matched both the title and authors. Missing fields were left blank.',
    '外部书目查询未完成，已保留识别结果；可稍后重试或手工补充。': 'Publication lookup did not complete. Suggestions were retained; retry later or fill in the details.',
    '管理员已关闭外部书目补全，可手动补充缺失字段。': 'Publication lookup is disabled. You can fill in missing details yourself.',
    '已依据题名和作者吻合的 Crossref 出版记录补全候选字段；DOI 可作为相关出版来源，年份还须与所收录版本对应，请核对后导入。': 'Matching Crossref records supplied additional suggestions. A DOI may identify a related publication; check the year against this PDF version before importing.',
    '外部出版日期未能确定对应所收录版本；版本年份继续留空。相关记录仅供核对，可按文件上的日期手动填写。': 'Publication dates could not be linked to this PDF version, so its year was left blank. Use the records for comparison and check the date in the file.',
    '现有字段与外部书目存在差异，未自动覆盖，请核对后选择。': 'The publication record differs from the current fields. Values were not overwritten; review them before choosing.',
}
